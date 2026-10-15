"""Per-document tile cache on top of the worker-process pool.

Pages are rendered in tiles of at most ``TILE`` device pixels (small pages in
one piece). Thumbnails double as low-resolution placeholders, so a page is
never shown blank while its sharp tiles are being rendered.
"""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap

from .pool import pool

TILE = 1024             # tile edge in device pixels
SINGLE_TILE_MAX = 2400  # pages up to this size (both edges) render in one piece
THUMB_WIDTH = 240       # device-pixel width of thumbnails / placeholders
CACHE_BYTES = 640 * 1024 * 1024


def tile_grid(page_w_px: int, page_h_px: int):
    """Return (tile_w, tile_h, cols, rows) for a page of the given device size."""
    if page_w_px <= SINGLE_TILE_MAX and page_h_px <= SINGLE_TILE_MAX:
        return page_w_px, page_h_px, 1, 1
    cols = (page_w_px + TILE - 1) // TILE
    rows = (page_h_px + TILE - 1) // TILE
    return TILE, TILE, cols, rows


class RenderManager(QObject):
    """Keys:
      tiles:  ("t", doc_id, page, rev, scale_key, col, row, invert, single)
      thumbs: ("p", doc_id, page, rev, invert)
    """

    ready = Signal(object)  # key

    def __init__(self, document):
        super().__init__()
        self.document = document
        self.doc_id = document.id
        self._cache: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._cache_bytes = 0
        self._alive = True

    # ----------------------------------------------------------------- keys
    def tile_key(self, page, scale, col, row, invert, single):
        return ("t", self.doc_id, page, self.document.page_rev[page],
                int(round(scale * 10000)), col, row, invert, single)

    def thumb_key(self, page, invert):
        return ("p", self.doc_id, page, self.document.page_rev[page], invert)

    # ---------------------------------------------------------------- public
    def stop(self):
        self._alive = False
        pool().forget_owner(self.doc_id)
        pool().close_document(self.doc_id)
        self.clear()

    def get(self, key):
        pm = self._cache.get(key)
        if pm is not None:
            self._cache.move_to_end(key)
        return pm

    def request_tile(self, key, scale: float, clip: tuple | None):
        if key in self._cache:
            return
        doc = self.document
        page = key[2]

        def build():
            if not self._alive or page >= doc.page_count or doc.page_rev[page] != key[3]:
                return None
            return ("render", doc.worker_spec(), page, scale, clip, key[7])

        pool().submit_render(key, build, lambda msg: self._on_result(key, msg))

    def request_thumb(self, key):
        if key in self._cache:
            return
        doc = self.document
        page = key[2]

        def build():
            if not self._alive or page >= doc.page_count or doc.page_rev[page] != key[3]:
                return None
            w = doc.page_sizes[page][0] or 1
            return ("render", doc.worker_spec(), page, THUMB_WIDTH / w, None, key[4])

        pool().submit_render(key, build, lambda msg: self._on_result(key, msg), thumb=True)

    def retain_tiles(self, wanted: set):
        pool().retain(self.doc_id, wanted)

    def clear(self):
        self._cache.clear()
        self._cache_bytes = 0

    def best_fallback(self, page: int, invert: bool):
        """Best cached full-page image of the page at its current revision."""
        rev = self.document.page_rev[page]
        best = None
        best_w = 0
        for k, pm in reversed(self._cache.items()):
            if k[2] != page or k[3] != rev:
                continue
            if k[0] == "t":
                if k[8] and k[7] == invert and pm.width() > best_w:
                    best, best_w = pm, pm.width()
            elif k[4] == invert and best is None:
                best = pm
        return best

    # -------------------------------------------------------------- internal
    def _on_result(self, key, msg):
        if not self._alive or msg[0] != "img":
            return
        _, _, w, h, stride, data = msg
        img = QImage(data, w, h, stride, QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img)
        self._cache[key] = pm
        self._cache_bytes += w * h * 4
        while self._cache_bytes > CACHE_BYTES and len(self._cache) > 8:
            k, old = self._cache.popitem(last=False)
            self._cache_bytes -= old.width() * old.height() * 4
        self.ready.emit(key)
