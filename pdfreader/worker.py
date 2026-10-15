"""Code that runs inside worker processes.

PyMuPDF holds the GIL while rendering, so rendering and text extraction run
in separate processes to keep the GUI perfectly smooth. This module must not
import Qt: it is imported by every spawned worker.
"""
from __future__ import annotations

import re
from collections import OrderedDict

TEXT_FLAGS = None  # resolved lazily (needs pymupdf)
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS.sub(" ", text.replace("­", ""))


class _DocCache:
    def __init__(self, fitz):
        self.fitz = fitz
        self.docs: OrderedDict[int, tuple] = OrderedDict()  # id -> (version, doc, dls)

    def get(self, spec):
        doc_id, version, path, password = spec
        entry = self.docs.get(doc_id)
        if entry is not None and entry[0] == version:
            self.docs.move_to_end(doc_id)
            return entry[1], entry[2]
        if entry is not None:
            self._close(doc_id)
        doc = self.fitz.open(path)
        if doc.needs_pass and password:
            doc.authenticate(password)
        dls: OrderedDict[int, object] = OrderedDict()
        self.docs[doc_id] = (version, doc, dls)
        while len(self.docs) > 6:
            self._close(next(iter(self.docs)))
        return doc, dls

    def _close(self, doc_id):
        entry = self.docs.pop(doc_id, None)
        if entry is not None:
            entry[2].clear()
            try:
                entry[1].close()
            except Exception:
                pass

    def close(self, doc_id):
        self._close(doc_id)


def _display_list(doc, dls, page):
    dl = dls.get(page)
    if dl is None:
        dl = doc[page].get_displaylist(annots=True)
        dls[page] = dl
        while len(dls) > 16:
            dls.popitem(last=False)
    else:
        dls.move_to_end(page)
    return dl


def _page_chars(fitz, page):
    """Normalized page text plus a bbox (visual coords) for every character."""
    m = page.rotation_matrix
    raw = page.get_text("rawdict", flags=TEXT_FLAGS)
    chars: list[str] = []
    boxes: list[tuple] = []
    last_space = True
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    c = ch["c"]
                    if c == "­":
                        continue
                    if c.isspace():
                        if last_space:
                            continue
                        c = " "
                        last_space = True
                    else:
                        last_space = False
                    chars.append(c)
                    r = fitz.Rect(ch["bbox"]) * m
                    boxes.append((r.x0, r.y0, r.x1, r.y1))
            # line break -> single space
            if not last_space:
                chars.append(" ")
                boxes.append(boxes[-1] if boxes else (0, 0, 0, 0))
                last_space = True
    return "".join(chars), boxes


def _merge_boxes(boxes):
    """Merge character boxes that sit on the same line into rectangles."""
    rects = []
    for x0, y0, x1, y1 in boxes:
        if x1 <= x0 and y1 <= y0:
            continue
        if rects:
            rx0, ry0, rx1, ry1 = rects[-1]
            h = max(ry1 - ry0, y1 - y0, 1)
            same_line = abs(((y0 + y1) / 2) - ((ry0 + ry1) / 2)) < h * 0.5
            if same_line and x0 <= rx1 + h and x1 >= rx0 - h:
                rects[-1] = (min(rx0, x0), min(ry0, y0), max(rx1, x1), max(ry1, y1))
                continue
            # vertical text: same column
            w = max(rx1 - rx0, x1 - x0, 1)
            same_col = abs(((x0 + x1) / 2) - ((rx0 + rx1) / 2)) < w * 0.5
            if same_col and y0 <= ry1 + w and y1 >= ry0 - w:
                rects[-1] = (min(rx0, x0), min(ry0, y0), max(rx1, x1), max(ry1, y1))
                continue
        rects.append((x0, y0, x1, y1))
    return rects


def worker_main(conn):
    global TEXT_FLAGS
    import pymupdf as fitz

    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    TEXT_FLAGS = (
        fitz.TEXT_PRESERVE_WHITESPACE
        | fitz.TEXT_MEDIABOX_CLIP
        | fitz.TEXT_CID_FOR_UNKNOWN_UNICODE
    )
    cache = _DocCache(fitz)

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        kind = msg[0]
        if kind == "quit":
            return
        if kind == "close":
            cache.close(msg[1])
            continue
        job_id = msg[1]
        try:
            if kind == "render":
                _, _, spec, page, scale, clip, invert = msg
                doc, dls = cache.get(spec)
                dl = _display_list(doc, dls, page)
                mat = fitz.Matrix(scale, scale)
                if clip is None:
                    pix = dl.get_pixmap(matrix=mat, alpha=False)
                else:
                    pix = dl.get_pixmap(matrix=mat, alpha=False, clip=fitz.Rect(*clip))
                if invert:
                    pix.invert_irect(pix.irect)
                conn.send(("img", job_id, pix.width, pix.height, pix.stride, bytes(pix.samples)))
            elif kind == "index":
                _, _, spec, pages = msg
                doc, _ = cache.get(spec)
                out = []
                for p in pages:
                    try:
                        txt = doc[p].get_text("text", flags=TEXT_FLAGS)
                    except Exception:
                        txt = ""
                    out.append((p, normalize(txt).strip()))
                conn.send(("index", job_id, out))
            elif kind == "rects":
                _, _, spec, page, pattern, re_flags = msg
                doc, _ = cache.get(spec)
                text, boxes = _page_chars(fitz, doc[page])
                rx = re.compile(pattern, re_flags)
                hits = []
                for mt in rx.finditer(text):
                    s, e = mt.span()
                    if e <= s:
                        continue
                    hits.append(_merge_boxes(boxes[s:e]))
                conn.send(("rects", job_id, page, hits))
            else:
                conn.send(("err", job_id, f"unknown job {kind}"))
        except Exception as exc:  # report and keep serving
            try:
                conn.send(("err", job_id, repr(exc)))
            except Exception:
                return
