"""Full-text search.

The text of every page is extracted once by the text worker process into an
in-memory index of normalized strings. A query is a regular expression run
over that index, which takes milliseconds even for thousands of pages, so the
complete result list is available almost instantly. Highlight rectangles are
computed lazily (again in the worker) only for pages that are actually shown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .pool import pool
from .worker import normalize

INDEX_BATCH = 16
MAX_HITS = 200_000


@dataclass(frozen=True)
class Hit:
    page: int
    occ: int        # occurrence number within the page
    before: str
    match: str
    after: str


def build_pattern(query: str, case: bool, whole: bool) -> tuple[str, int] | None:
    q = normalize(query).strip()
    if not q:
        return None
    parts = []
    for ch in q:
        if ch == " ":
            parts.append(r"\s+")
        elif ch in "еёЕЁ":
            parts.append("[её]" if ch in "её" else "[ЕЁ]")
        else:
            parts.append(re.escape(ch))
    pattern = "".join(parts)
    if whole:
        pattern = r"(?<!\w)" + pattern + r"(?!\w)"
    flags = 0 if case else re.IGNORECASE
    return pattern, flags


class SearchEngine(QObject):
    indexProgress = Signal(int, int)   # pages indexed, total
    resultsChanged = Signal()
    rectsReady = Signal(int)           # page

    def __init__(self, document):
        super().__init__()
        self.document = document
        self.hits: list[Hit] = []
        self.query = ""
        self._pattern: tuple[str, int] | None = None
        self._rx = None
        self._index: list[str | None] = []
        self._indexed = 0
        self._generation = 0
        self._rects: dict[int, list] = {}
        self._rects_pending: set[int] = set()
        self._started = False
        self.document.structureChanged.connect(self.reset_index)

    # ---------------------------------------------------------------- index
    @property
    def index_complete(self) -> bool:
        return self._started and self._indexed >= len(self._index)

    def start_indexing(self):
        if self._started:
            return
        self._started = True
        self._generation += 1
        n = self.document.page_count
        self._index = [None] * n
        self._indexed = 0
        gen = self._generation
        for start in range(0, n, INDEX_BATCH):
            pages = list(range(start, min(n, start + INDEX_BATCH)))
            pool().submit_text(
                self.document.id,
                lambda pages=pages: ("index", self.document.worker_spec(), pages),
                lambda msg, gen=gen: self._on_index(gen, msg),
            )
        if n == 0:
            self.indexProgress.emit(0, 0)

    def reset_index(self):
        pool().forget_owner(self.document.id)
        self._started = False
        self._rects.clear()
        self._rects_pending.clear()
        self.start_indexing()
        if self._pattern:
            self._run_search()

    def _on_index(self, gen, msg):
        if gen != self._generation or msg[0] != "index":
            return
        new_pages = []
        for page, text in msg[2]:
            if page < len(self._index) and self._index[page] is None:
                self._index[page] = text
                self._indexed += 1
                new_pages.append(page)
        self.indexProgress.emit(self._indexed, len(self._index))
        if self._rx is not None and new_pages:
            before = len(self.hits)
            for p in new_pages:
                self._search_page(p)
            if len(self.hits) != before:
                self.hits.sort(key=lambda h: (h.page, h.occ))
            self.resultsChanged.emit()

    def page_text(self, page: int) -> str | None:
        if 0 <= page < len(self._index):
            return self._index[page]
        return None

    # --------------------------------------------------------------- search
    def set_query(self, query: str, case: bool = False, whole: bool = False):
        self.start_indexing()
        pattern = build_pattern(query, case, whole)
        self.query = query
        if pattern == self._pattern:
            self.resultsChanged.emit()
            return
        self._pattern = pattern
        self._rx = re.compile(*pattern) if pattern else None
        self._rects.clear()
        self._rects_pending.clear()
        self._run_search()

    def clear(self):
        self.set_query("")

    def _run_search(self):
        self.hits = []
        if self._rx is not None:
            for p, text in enumerate(self._index):
                if text is not None:
                    self._search_page(p)
                    if len(self.hits) >= MAX_HITS:
                        break
        self.resultsChanged.emit()

    def _search_page(self, page: int):
        text = self._index[page]
        if not text or len(self.hits) >= MAX_HITS:
            return
        for occ, m in enumerate(self._rx.finditer(text)):
            s, e = m.span()
            if e <= s:
                continue
            before = text[max(0, s - 40):s]
            after = text[e:e + 60]
            self.hits.append(Hit(page, occ, before, text[s:e], after))

    # ---------------------------------------------------------------- rects
    def page_hit_rects(self, page: int):
        """List (per occurrence) of rect lists in visual page coordinates.

        Returns None while the geometry is being computed; ``rectsReady`` is
        emitted once it is available.
        """
        if self._pattern is None:
            return []
        r = self._rects.get(page)
        if r is not None:
            return r
        text = self.page_text(page)
        if text is not None and not self._rx.search(text):
            self._rects[page] = []
            return self._rects[page]
        if page in self._rects_pending:
            return None
        self._rects_pending.add(page)
        pattern = self._pattern
        pool().submit_text(
            self.document.id,
            lambda: ("rects", self.document.worker_spec(), page, pattern[0], pattern[1]),
            lambda msg: self._on_rects(pattern, page, msg),
        )
        return None

    def _on_rects(self, pattern, page, msg):
        if pattern != self._pattern:
            return
        self._rects_pending.discard(page)
        self._rects[page] = msg[3] if msg[0] == "rects" else []
        self.rectsReady.emit(page)

    def hit_index_near(self, page: int) -> int:
        """Index of the first hit on or after ``page`` (wrapping)."""
        if not self.hits:
            return -1
        lo, hi = 0, len(self.hits)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.hits[mid].page < page:
                lo = mid + 1
            else:
                hi = mid
        return lo if lo < len(self.hits) else 0
