"""Document model: a thread-safe wrapper around a PyMuPDF document."""
from __future__ import annotations

import itertools
import os
import shutil
import tempfile
import threading
from collections import OrderedDict

import pymupdf as fitz
from PySide6.QtCore import QObject, Signal

# Flags used for every text extraction so that the search index and the
# per-character geometry always produce identical strings.
TEXT_FLAGS = (
    fitz.TEXT_PRESERVE_WHITESPACE
    | fitz.TEXT_MEDIABOX_CLIP
    | fitz.TEXT_CID_FOR_UNKNOWN_UNICODE
)

_doc_ids = itertools.count(1)


class PasswordRequired(Exception):
    pass


class PdfDocument(QObject):
    """Holds one open PDF.

    All access to the underlying ``fitz.Document`` must happen while holding
    ``self.lock`` because the renderer and the search engine use the document
    from worker threads.
    """

    # Emitted when the page structure changed (pages added/removed/rotated).
    structureChanged = Signal()
    # Emitted when the content of a single page changed (annotations).
    pageChanged = Signal(int)
    # Emitted when the modified flag toggles.
    modifiedChanged = Signal(bool)
    # Emitted when the outline (bookmarks) changed.
    outlineChanged = Signal()

    def __init__(self, doc: fitz.Document, path: str | None, title: str | None = None,
                 password: str | None = None):
        super().__init__()
        self.id = next(_doc_ids)
        self.lock = threading.RLock()
        self.doc = doc
        self.path = path
        self._title = title
        self._modified = False
        self._dl_cache: OrderedDict[int, fitz.DisplayList] = OrderedDict()
        self._words_cache: OrderedDict[int, list] = OrderedDict()
        self._links_cache: dict[int, list] = {}
        self.page_rev: list[int] = []
        self._rev_counter = itertools.count(1)
        self.undo_stack: list[tuple[int, int]] = []  # (page, annot xref)
        self.password = password
        # Worker processes read the file from disk. ``_disk_version`` is the
        # content version the file at ``path`` corresponds to; after edits a
        # snapshot file is written for the workers.
        self.content_version = 0
        self._disk_version = 0 if path else -1
        self._snapshot: tuple[int, str] | None = None
        self._reset_geometry()

    # ------------------------------------------------------------------ open
    @classmethod
    def open(cls, path: str, password: str | None = None) -> "PdfDocument":
        doc = fitz.open(path)
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                doc.close()
                raise PasswordRequired(path)
        if not doc.is_pdf:
            # XPS/EPUB/CBZ etc. are converted so that annotations work.
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            doc = fitz.open("pdf", pdf_bytes)
            return cls(doc, None, os.path.basename(path))
        return cls(doc, os.path.abspath(path), password=password)

    @classmethod
    def from_bytes(cls, data: bytes, title: str) -> "PdfDocument":
        return cls(fitz.open("pdf", data), None, title)

    def close(self):
        self._remove_snapshot()
        with self.lock:
            self._dl_cache.clear()
            self._words_cache.clear()
            try:
                self.doc.close()
            except Exception:
                pass

    # ------------------------------------------------------------ properties
    @property
    def title(self) -> str:
        if self._title:
            return self._title
        if self.path:
            return os.path.basename(self.path)
        return "Без имени.pdf"

    @property
    def page_count(self) -> int:
        return len(self.page_sizes)

    @property
    def modified(self) -> bool:
        return self._modified

    def set_modified(self, value: bool = True):
        if value != self._modified:
            self._modified = value
            self.modifiedChanged.emit(value)

    def _reset_geometry(self):
        with self.lock:
            sizes = []
            rot = []
            for page in self.doc:
                r = page.rect  # already reflects /Rotate
                sizes.append((r.width, r.height))
                rot.append(page.rotation)
            self.page_sizes = sizes
            self.page_rotations = rot
            self.page_rev = [next(self._rev_counter) for _ in sizes]
            self._dl_cache.clear()
            self._words_cache.clear()
            self._links_cache.clear()

    def bump_page(self, index: int):
        with self.lock:
            self.content_version += 1
            self.page_rev[index] = next(self._rev_counter)
            self._dl_cache.pop(index, None)
            self._links_cache.pop(index, None)
        self.pageChanged.emit(index)

    # --------------------------------------------------------------- workers
    def worker_spec(self) -> tuple:
        """(id, version, path, password) describing the current content."""
        if self._disk_version == self.content_version and self.path:
            return (self.id, self.content_version, self.path, self.password)
        if self._snapshot is None or self._snapshot[0] != self.content_version:
            from .paths import temp_dir
            path = os.path.join(temp_dir(), f"doc{self.id}_v{self.content_version}.pdf")
            with self.lock:
                self.doc.save(path, garbage=0)
            self._remove_snapshot()
            self._snapshot = (self.content_version, path)
        return (self.id, self.content_version, self._snapshot[1], None)

    def _remove_snapshot(self):
        if self._snapshot:
            try:
                os.remove(self._snapshot[1])
            except OSError:
                pass  # still open in a worker; cleaned up on exit
            self._snapshot = None

    # ------------------------------------------------------------- rendering
    def display_list(self, index: int) -> fitz.DisplayList:
        """Return a cached display list. Caller must hold the lock."""
        dl = self._dl_cache.get(index)
        if dl is None:
            dl = self.doc[index].get_displaylist(annots=True)
            self._dl_cache[index] = dl
            while len(self._dl_cache) > 24:
                self._dl_cache.popitem(last=False)
        else:
            self._dl_cache.move_to_end(index)
        return dl

    def rotation_matrix(self, index: int) -> fitz.Matrix:
        with self.lock:
            return fitz.Matrix(self.doc[index].rotation_matrix)

    # ------------------------------------------------------------------ text
    def words(self, index: int) -> list:
        """Words of a page in *rotated* (visual) page coordinates."""
        with self.lock:
            w = self._words_cache.get(index)
            if w is None:
                page = self.doc[index]
                raw = page.get_text("words", flags=TEXT_FLAGS, sort=False)
                m = page.rotation_matrix
                w = []
                for x0, y0, x1, y1, text, b, l, n in raw:
                    r = fitz.Rect(x0, y0, x1, y1) * m
                    w.append((r.x0, r.y0, r.x1, r.y1, text, b, l, n))
                self._words_cache[index] = w
                while len(self._words_cache) > 64:
                    self._words_cache.popitem(last=False)
            return w

    def page_text(self, index: int) -> str:
        with self.lock:
            return self.doc[index].get_text("text", flags=TEXT_FLAGS)

    def links(self, index: int) -> list:
        """Links with ``from`` rect converted to visual coordinates."""
        with self.lock:
            links = self._links_cache.get(index)
            if links is None:
                page = self.doc[index]
                m = page.rotation_matrix
                links = []
                for ln in page.get_links():
                    ln = dict(ln)
                    ln["vrect"] = fitz.Rect(ln["from"]) * m
                    links.append(ln)
                self._links_cache[index] = links
            return links

    def resolve_link_target(self, link: dict) -> tuple[int, float | None] | None:
        """Return (page, y in visual coords) for an internal link."""
        kind = link.get("kind")
        page = link.get("page", -1)
        if kind == fitz.LINK_NAMED and link.get("name"):
            with self.lock:
                try:
                    res = self.doc.resolve_names().get(link["name"]) or {}
                    page = res.get("page", -1)
                except Exception:
                    page = -1
        if page is None or page < 0 or page >= self.page_count:
            return None
        y = None
        to = link.get("to")
        if to is not None:
            try:
                with self.lock:
                    p = fitz.Point(to) * self.doc[page].rotation_matrix
                y = p.y
            except Exception:
                y = None
        return page, y

    # -------------------------------------------------------------- outline
    def toc(self) -> list:
        with self.lock:
            try:
                return self.doc.get_toc(simple=False)
            except Exception:
                return []

    def set_toc(self, toc: list):
        with self.lock:
            self.doc.set_toc(toc)
        self.set_modified(True)
        self.outlineChanged.emit()

    # ---------------------------------------------------------- annotations
    def _to_unrotated(self, index: int, rect_or_point):
        page = self.doc[index]
        return rect_or_point * page.derotation_matrix

    def add_text_markup(self, index: int, rects: list, kind: str, color) -> int | None:
        """Add highlight/underline/strikeout over visual-coordinate rects."""
        if not rects:
            return None
        with self.lock:
            page = self.doc[index]
            quads = [self._to_unrotated(index, fitz.Rect(r)).quad for r in rects]
            if kind == "highlight":
                annot = page.add_highlight_annot(quads)
            elif kind == "underline":
                annot = page.add_underline_annot(quads)
            elif kind == "strikeout":
                annot = page.add_strikeout_annot(quads)
            else:
                annot = page.add_squiggly_annot(quads)
            annot.set_colors(stroke=color)
            annot.update()
            xref = annot.xref
        self._after_annot(index, xref)
        return xref

    def add_note(self, index: int, point, text: str, color=(1, 0.82, 0.2)) -> int:
        with self.lock:
            page = self.doc[index]
            p = self._to_unrotated(index, fitz.Point(point))
            annot = page.add_text_annot(p, text, icon="Comment")
            annot.set_colors(stroke=color)
            annot.set_info(title=os.environ.get("USERNAME", ""))
            annot.update()
            xref = annot.xref
        self._after_annot(index, xref)
        return xref

    def add_freetext(self, index: int, rect, text: str, fontsize: float = 12,
                     color=(0, 0, 0)) -> int:
        with self.lock:
            page = self.doc[index]
            r = self._to_unrotated(index, fitz.Rect(rect))
            annot = page.add_freetext_annot(
                r, text, fontsize=fontsize, fontname="helv", text_color=color,
                rotate=page.rotation,
            )
            annot.update()
            xref = annot.xref
        self._after_annot(index, xref)
        return xref

    def add_ink(self, index: int, strokes: list, color, width: float = 2.0) -> int | None:
        strokes = [s for s in strokes if len(s) >= 2]
        if not strokes:
            return None
        with self.lock:
            page = self.doc[index]
            m = page.derotation_matrix
            pts = [[tuple(fitz.Point(p) * m) for p in s] for s in strokes]
            annot = page.add_ink_annot(pts)
            annot.set_colors(stroke=color)
            annot.set_border(width=width)
            annot.update()
            xref = annot.xref
        self._after_annot(index, xref)
        return xref

    def add_shape(self, index: int, rect, kind: str, color, width: float = 2.0) -> int:
        with self.lock:
            page = self.doc[index]
            r = self._to_unrotated(index, fitz.Rect(rect)).normalize()
            if kind == "ellipse":
                annot = page.add_circle_annot(r)
            else:
                annot = page.add_rect_annot(r)
            annot.set_colors(stroke=color)
            annot.set_border(width=width)
            annot.update()
            xref = annot.xref
        self._after_annot(index, xref)
        return xref

    def _after_annot(self, index: int, xref: int):
        self.undo_stack.append((index, xref))
        self.set_modified(True)
        self.bump_page(index)

    def annotations(self, index: int) -> list[dict]:
        """List annotations of a page with visual-coordinate rects."""
        out = []
        with self.lock:
            page = self.doc[index]
            m = page.rotation_matrix
            for a in page.annots() or []:
                info = a.info
                out.append({
                    "xref": a.xref,
                    "type": a.type[1],
                    "rect": a.rect * m,
                    "content": info.get("content", ""),
                    "author": info.get("title", ""),
                    "date": info.get("modDate", "") or info.get("creationDate", ""),
                })
        return out

    def annotation_at(self, index: int, point) -> dict | None:
        best = None
        for a in self.annotations(index):
            r = fitz.Rect(a["rect"])
            if r.contains(fitz.Point(point)):
                if best is None or r.get_area() < fitz.Rect(best["rect"]).get_area():
                    best = a
        return best

    def delete_annotation(self, index: int, xref: int):
        with self.lock:
            page = self.doc[index]
            annot = page.load_annot(xref)
            if annot is not None:
                page.delete_annot(annot)
        self.undo_stack = [u for u in self.undo_stack if u != (index, xref)]
        self.set_modified(True)
        self.bump_page(index)

    def set_annotation_content(self, index: int, xref: int, text: str):
        with self.lock:
            annot = self.doc[index].load_annot(xref)
            if annot is None:
                return
            annot.set_info(content=text)
            annot.update()
        self.set_modified(True)
        self.bump_page(index)

    def set_annotation_color(self, index: int, xref: int, color):
        with self.lock:
            annot = self.doc[index].load_annot(xref)
            if annot is None:
                return
            if annot.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                annot.update(text_color=color)
            else:
                annot.set_colors(stroke=color)
                annot.update()
        self.set_modified(True)
        self.bump_page(index)

    def undo(self) -> bool:
        while self.undo_stack:
            index, xref = self.undo_stack.pop()
            with self.lock:
                page = self.doc[index] if index < len(self.doc) else None
                annot = page.load_annot(xref) if page is not None else None
                if annot is None:
                    continue
                page.delete_annot(annot)
            self.set_modified(True)
            self.bump_page(index)
            return True
        return False

    # ---------------------------------------------------------------- pages
    def rotate_pages(self, indices, delta: int):
        with self.lock:
            for i in indices:
                page = self.doc[i]
                page.set_rotation((page.rotation + delta) % 360)
        self._structure_edit()

    def delete_pages(self, indices):
        indices = sorted(set(indices))
        if not indices or len(indices) >= self.page_count:
            return
        with self.lock:
            self.doc.delete_pages(indices)
        self.undo_stack.clear()
        self._structure_edit()

    def move_page(self, src: int, dst: int):
        """Move page ``src`` so that it ends up at position ``dst``."""
        if src == dst:
            return
        with self.lock:
            if dst >= self.page_count - 1:
                self.doc.move_page(src, -1)
            else:
                self.doc.move_page(src, dst if dst < src else dst + 1)
        self.undo_stack.clear()
        self._structure_edit()

    def insert_pdf(self, path: str, at: int):
        src = fitz.open(path)
        try:
            if not src.is_pdf:
                data = src.convert_to_pdf()
                src.close()
                src = fitz.open("pdf", data)
            with self.lock:
                self.doc.insert_pdf(src, start_at=at)
        finally:
            src.close()
        self.undo_stack.clear()
        self._structure_edit()

    def insert_blank_page(self, at: int):
        w, h = self.page_sizes[min(at, self.page_count - 1)] if self.page_count else (595, 842)
        with self.lock:
            self.doc.new_page(pno=at, width=w, height=h)
        self.undo_stack.clear()
        self._structure_edit()

    def extract_pages(self, indices, path: str):
        with self.lock:
            out = fitz.open()
            for i in sorted(set(indices)):
                out.insert_pdf(self.doc, from_page=i, to_page=i)
        out.save(path, garbage=3, deflate=True)
        out.close()

    def _structure_edit(self):
        self.content_version += 1
        self._reset_geometry()
        self.set_modified(True)
        self.structureChanged.emit()
        self.outlineChanged.emit()

    # ---------------------------------------------------------------- export
    def render_page_png(self, index: int, path: str, dpi: int = 150):
        with self.lock:
            pix = self.doc[index].get_pixmap(dpi=dpi, annots=True)
        pix.save(path)

    def export_text(self, path: str):
        parts = []
        for i in range(self.page_count):
            parts.append(self.page_text(i))
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n\f".join(parts))

    def save_copy(self, path: str):
        """Write the current content (decrypted, with edits) to ``path``."""
        with self.lock:
            self.doc.save(path, garbage=1, deflate=True)

    def metadata(self) -> dict:
        with self.lock:
            md = dict(self.doc.metadata or {})
            md["_encrypted"] = self.doc.is_encrypted or bool(md.get("encryption"))
            md["_pages"] = len(self.doc)
        return md

    # ----------------------------------------------------------------- save
    def save(self, path: str | None = None):
        """Save to ``path`` (or to the original file) and reopen from it."""
        target = os.path.abspath(path or self.path)
        with self.lock:
            same_file = self.path and os.path.normcase(target) == os.path.normcase(self.path)
            if same_file and self.doc.can_save_incrementally():
                self.doc.save(target, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            else:
                fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(target))
                os.close(fd)
                try:
                    self.doc.save(tmp, garbage=3, deflate=True)
                    if same_file:
                        self.doc.close()
                    shutil.move(tmp, target)
                except Exception:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    if same_file and self.doc.is_closed:
                        self.doc = fitz.open(self.path)
                    raise
                if not self.doc.is_closed:
                    self.doc.close()
                self.doc = fitz.open(target)
            self.path = target
            self._title = None
            self.password = None
            self.content_version += 1
            self._disk_version = self.content_version
            self._reset_geometry()
        self.undo_stack.clear()
        self.set_modified(False)
        self.structureChanged.emit()
