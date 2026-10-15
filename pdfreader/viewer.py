"""The page view: layout, smooth scrolling, tiled painting and mouse tools."""
from __future__ import annotations

import math
import time

import pymupdf as fitz
from PySide6.QtCore import (
    QPointF, QRectF, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QDesktopServices, QGuiApplication, QKeySequence, QPainter,
    QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea, QApplication, QColorDialog, QInputDialog, QMenu,
    QMessageBox, QToolTip,
)

from . import icons, theme
from .frameclock import clock, refresh_rate
from .renderer import tile_grid

PT_TO_PX = 96.0 / 72.0
MIN_ZOOM, MAX_ZOOM = 0.08, 64.0
ZOOM_STEPS = [0.1, 0.125, 0.25, 0.33, 0.5, 0.67, 0.75, 0.85, 1.0, 1.25, 1.5, 2.0,
              2.5, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0, 48.0, 64.0]

MARKUP_TOOLS = ("highlight", "underline", "strikeout")
DEFAULT_COLORS = {
    "highlight": (1.0, 0.85, 0.0),
    "underline": (0.08, 0.45, 0.9),
    "strikeout": (0.86, 0.1, 0.1),
    "note": (1.0, 0.82, 0.2),
    "text": (0.0, 0.0, 0.0),
    "ink": (0.86, 0.1, 0.1),
    "rect": (0.86, 0.1, 0.1),
    "ellipse": (0.86, 0.1, 0.1),
}
TOOLS_WITH_COLOR = tuple(DEFAULT_COLORS)
TOOL_NAMES = {
    "select": "Выделение", "hand": "Рука", "highlight": "Выделение цветом",
    "underline": "Подчёркивание", "strikeout": "Зачёркивание", "note": "Записка",
    "text": "Текстовое поле", "ink": "Рисование", "rect": "Прямоугольник",
    "ellipse": "Эллипс", "eraser": "Ластик (удалить комментарий)",
}

LAYOUTS = ("continuous", "single", "two_continuous", "two")


def _qcolor(rgb, alpha=255) -> QColor:
    return QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), alpha)


class PdfView(QAbstractScrollArea):
    currentPageChanged = Signal(int)
    zoomChanged = Signal(float)
    toolChanged = Signal(str)
    selectionChanged = Signal(bool)
    layoutModeChanged = Signal(str)
    historyChanged = Signal()
    escapePressed = Signal()
    statusMessage = Signal(str)

    def __init__(self, document, renderer, search, parent=None):
        super().__init__(parent)
        self.doc = document
        self.renderer = renderer
        self.search = search
        self.zoom = 1.0
        self.fit_mode: str | None = "width"
        self.layout_mode = "continuous"
        self.invert = False
        self.presentation = False
        self.tool = "select"
        self.tool_colors = dict(DEFAULT_COLORS)
        self.current_page = 0
        self.current_hit: int = -1
        self._dpr = 1.0
        self._pos: list = []
        self._content_w = self._content_h = 0  # device px
        self._single_page = 0
        self._rows: list[list[int]] = []
        self._row_bounds: list[tuple[int, int]] = []
        self._sel = None          # (anchor_page, anchor_idx, focus_page, focus_idx)
        self._sel_rect_cache: dict = {}
        self._drag = None         # active mouse interaction
        self._space_pan = False
        self._history: list = []
        self._future: list = []
        self._annot_cache: dict[int, tuple] = {}
        self._pending_reveal = None
        self._wheel_accum = 0.0
        self._indicator_timer = QTimer(self, singleShot=True, interval=900,
                                       timeout=self.viewport().update)
        # Smooth scrolling is driven by a vsync-locked frame clock; the
        # position is kept as a float so motion is exact to the device pixel.
        self._fine_y: float | None = None
        self._scroll_target: float | None = None
        self._autoscroll_on = False
        self._autoscroll_speed = 90.0  # logical px per second
        self._clock_active = False
        self._last_frame: float | None = None
        # middle-button autoscroll ("anchor" scrolling as in browsers/Acrobat)
        self._mmb: dict | None = None
        clock().tick.connect(self._on_frame)

        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(self._on_scrolled)
        self.verticalScrollBar().setSingleStep(40)
        self.horizontalScrollBar().setSingleStep(40)

        self.renderer.ready.connect(self._on_tile_ready)
        self.search.rectsReady.connect(self._on_hit_rects)
        self.search.resultsChanged.connect(self.viewport().update)
        self.doc.structureChanged.connect(self._on_structure_changed)
        self.doc.pageChanged.connect(self._on_page_changed)
        self._relayout()

    # ================================================================ layout
    @property
    def scale_dev(self) -> float:
        """Device pixels per PDF point."""
        return self.zoom * PT_TO_PX * self._dpr

    def _margins(self):
        if self.presentation:
            return 0, 0, 0
        return 14, 12, 14  # side, gap, top/bottom (logical px)

    def _build_rows(self) -> list[list[int]]:
        n = self.doc.page_count
        if self.layout_mode in ("two_continuous", "two"):
            return [list(range(i, min(i + 2, n))) for i in range(0, n, 2)]
        return [[i] for i in range(n)]

    def _relayout(self, keep_anchor=True):
        anchor = self._anchor() if keep_anchor and self._pos else None
        self._dpr = self.devicePixelRatioF() or 1.0
        old_zoom = self.zoom
        if self.fit_mode:
            self.zoom = self._fit_zoom(self.fit_mode)
        n = self.doc.page_count
        s = self.scale_dev
        side, gap, edge = (round(v * self._dpr) for v in self._margins())
        self._rows = self._build_rows()
        rows = self._rows
        if self.layout_mode in ("single", "two"):
            row_idx = self._row_of(self._single_page)
            rows_to_place = [rows[row_idx]] if rows else []
        else:
            rows_to_place = rows
        self._pos = [None] * n
        vw = max(1, round(self.viewport().width() * self._dpr))
        sizes = [self._painted_size(i, s) for i in range(n)]
        widest = 0
        for row in rows_to_place:
            widest = max(widest, sum(sizes[i][0] for i in row) + gap * (len(row) - 1))
        content_w = max(vw, widest + 2 * side)
        y = edge
        self._row_bounds = []
        for row in rows_to_place:
            row_w = sum(sizes[i][0] for i in row) + gap * (len(row) - 1)
            row_h = max(sizes[i][1] for i in row)
            x = (content_w - row_w) // 2
            for i in row:
                w, h = sizes[i]
                self._pos[i] = (x, y + (row_h - h) // 2, w, h)
                x += w + gap
            self._row_bounds.append((y, y + row_h))
            y += row_h + gap
        content_h = y - gap + edge if rows_to_place else 0
        self._content_w, self._content_h = content_w, content_h
        self._sel_rect_cache.clear()
        self._update_scrollbars()
        if anchor:
            self._restore_anchor(anchor)
        self.viewport().update()
        self._update_current_page()
        if abs(old_zoom - self.zoom) > 1e-9:
            self.zoomChanged.emit(self.zoom)

    def _row_of(self, page: int) -> int:
        if self.layout_mode in ("two_continuous", "two"):
            return page // 2
        return page

    def _update_scrollbars(self):
        d = self._dpr
        vs, hs = self.verticalScrollBar(), self.horizontalScrollBar()
        vw, vh = self.viewport().width(), self.viewport().height()
        hs.setRange(0, max(0, int(self._content_w / d) - vw - 1))
        hs.setPageStep(vw)
        vs.setRange(0, max(0, math.ceil(self._content_h / d) - vh))
        vs.setPageStep(vh)
        vs.setSingleStep(max(20, vh // 20))

    def _fit_zoom(self, mode: str) -> float:
        if not self.doc.page_count:
            return 1.0
        side, gap, edge = self._margins()
        vw = max(50, self.viewport().width() - 2 * side)
        vh = max(50, self.viewport().height() - 2 * edge)
        page = min(self.current_page, self.doc.page_count - 1)
        if self.layout_mode in ("two_continuous", "two"):
            # use the typical page size so a single odd page does not shrink the spread
            sample = sorted(self.doc.page_sizes[: 200])
            typical_w = sample[len(sample) // 2][0]
            row = self._build_rows()[self._row_of(page)]
            w = 2 * typical_w + gap / PT_TO_PX
            h = max(self.doc.page_sizes[i][1] for i in row)
        else:
            w = self.doc.page_sizes[page][0]
            h = self.doc.page_sizes[page][1]
        zw = vw / (w * PT_TO_PX)
        if mode == "width":
            return max(MIN_ZOOM, min(MAX_ZOOM, zw))
        zh = vh / (h * PT_TO_PX)
        return max(MIN_ZOOM, min(MAX_ZOOM, min(zw, zh)))

    # ---------------------------------------------------- coordinate helpers
    def _current_y(self) -> float:
        v = self.verticalScrollBar().value()
        if self._fine_y is not None and abs(self._fine_y - v) <= 0.5:
            return self._fine_y
        return float(v)

    def _set_scroll_y(self, y: float):
        vs = self.verticalScrollBar()
        y = max(float(vs.minimum()), min(float(vs.maximum()), y))
        self._fine_y = y
        iv = round(y)
        if vs.value() != iv:
            vs.setValue(iv)
        else:
            self.viewport().update()

    def _offset_dev(self):
        d = self._dpr
        sx = round(self.horizontalScrollBar().value() * d)
        sy = round(self._current_y() * d)
        vh = round(self.viewport().height() * d)
        oy = (vh - self._content_h) // 2 if self._content_h < vh else 0
        return sx, sy - oy

    def page_rect_widget(self, i: int) -> QRectF | None:
        p = self._pos[i] if 0 <= i < len(self._pos) else None
        if p is None:
            return None
        sx, sy = self._offset_dev()
        d = self._dpr
        return QRectF((p[0] - sx) / d, (p[1] - sy) / d, p[2] / d, p[3] / d)

    def page_to_widget(self, i: int, x: float, y: float) -> QPointF:
        p = self._pos[i]
        sx, sy = self._offset_dev()
        s = self.scale_dev
        d = self._dpr
        return QPointF((p[0] - sx + x * s) / d, (p[1] - sy + y * s) / d)

    def page_rect_to_widget(self, i: int, r) -> QRectF:
        a = self.page_to_widget(i, r[0], r[1])
        b = self.page_to_widget(i, r[2], r[3])
        return QRectF(a, b).normalized()

    def widget_to_page(self, pos: QPointF, nearest=False):
        """Return (page, x_pt, y_pt) or None."""
        sx, sy = self._offset_dev()
        d = self._dpr
        X = pos.x() * d + sx
        Y = pos.y() * d + sy
        s = self.scale_dev
        best = None
        best_dist = None
        for i in self._visible_pages(extra=1 if nearest else 0):
            x, y, w, h = self._pos[i]
            if x <= X <= x + w and y <= Y <= y + h:
                return i, (X - x) / s, (Y - y) / s
            if nearest:
                dx = max(x - X, 0, X - (x + w))
                dy = max(y - Y, 0, Y - (y + h))
                dist = dx + dy * 4
                if best_dist is None or dist < best_dist:
                    best_dist, best = dist, i
        if best is not None:
            x, y, w, h = self._pos[best]
            return best, min(max((X - x) / s, 0), w / s), min(max((Y - y) / s, 0), h / s)
        return None

    def _visible_pages(self, extra=0) -> list[int]:
        """Pages intersecting the viewport (plus ``extra`` rows around it)."""
        if not self._pos:
            return []
        if self.layout_mode in ("single", "two"):
            return [i for i, p in enumerate(self._pos) if p is not None]
        sx, sy = self._offset_dev()
        top = sy
        bottom = sy + self.viewport().height() * self._dpr
        bounds = self._row_bounds
        lo, hi = 0, len(bounds)
        while lo < hi:  # first row whose bottom reaches the viewport
            mid = (lo + hi) // 2
            if bounds[mid][1] < top:
                lo = mid + 1
            else:
                hi = mid
        first = lo
        last = first
        while last < len(bounds) and bounds[last][0] <= bottom:
            last += 1
        first = max(0, first - extra)
        last = min(len(bounds), last + extra)
        out = []
        for r in range(first, last):
            out.extend(self._rows[r])
        return out

    # ---------------------------------------------------------- anchors
    def _anchor(self):
        """Remember what is at the top of the view: (page, fraction, x_frac)."""
        if not self._pos or not self.doc.page_count:
            return None
        sx, sy = self._offset_dev()
        d = self._dpr
        cy = sy + 0  # top edge
        for i in self._visible_pages():
            x, y, w, h = self._pos[i]
            if y + h >= cy:
                hs = self.horizontalScrollBar()
                xf = (hs.value() + self.viewport().width() / 2) / max(1, self._content_w / d)
                return i, (cy - y) / h, xf
        return None

    def _restore_anchor(self, anchor):
        i, frac, xf = anchor
        if i >= len(self._pos):
            return
        if self._pos[i] is None:
            return
        d = self._dpr
        x, y, w, h = self._pos[i]
        self.verticalScrollBar().setValue(round((y + frac * h) / d))
        hs = self.horizontalScrollBar()
        hs.setValue(round(xf * self._content_w / d - self.viewport().width() / 2))

    # ================================================================ public
    def set_zoom(self, zoom: float, anchor_pos: QPointF | None = None, fit_mode=None):
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if anchor_pos is None:
            anchor_pos = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        hit = self.widget_to_page(anchor_pos, nearest=True)
        self.fit_mode = fit_mode
        old = self.zoom
        self.zoom = zoom
        self._relayout(keep_anchor=hit is None)
        if hit is not None:
            i, px, py = hit
            if self._pos[i] is not None:
                p = self.page_to_widget(i, px, py)
                hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
                hs.setValue(round(hs.value() + p.x() - anchor_pos.x()))
                vs.setValue(round(vs.value() + p.y() - anchor_pos.y()))
        if abs(old - self.zoom) > 1e-6 or fit_mode:
            self.zoomChanged.emit(self.zoom)
        self.viewport().update()

    def set_fit(self, mode: str):
        if mode in ("width", "page"):
            self.fit_mode = mode
            page = self.current_page
            self._relayout(keep_anchor=True)
            if mode == "page":
                self.go_to_page(page, add_history=False)
            self.zoomChanged.emit(self.zoom)
        else:
            self.set_zoom(1.0)

    def zoom_in(self):
        z = self.zoom * 1.0001
        nxt = next((s for s in ZOOM_STEPS if s > z), MAX_ZOOM)
        self.set_zoom(nxt)

    def zoom_out(self):
        z = self.zoom * 0.9999
        prv = next((s for s in reversed(ZOOM_STEPS) if s < z), MIN_ZOOM)
        self.set_zoom(prv)

    def set_layout_mode(self, mode: str):
        if mode not in LAYOUTS or mode == self.layout_mode:
            return
        page = self.current_page
        self.layout_mode = mode
        self._single_page = page
        self._relayout(keep_anchor=False)
        self.go_to_page(page, add_history=False)
        self.layoutModeChanged.emit(mode)

    def set_invert(self, on: bool):
        self.invert = on
        self.viewport().update()

    def set_presentation(self, on: bool):
        self.presentation = on
        self._relayout(keep_anchor=False)
        self.go_to_page(self.current_page, add_history=False)

    def set_tool(self, tool: str):
        self.tool = tool
        self._drag = None
        self._update_cursor()
        self.toolChanged.emit(tool)
        self.viewport().update()

    def set_tool_color(self, tool: str, rgb):
        self.tool_colors[tool] = rgb

    # ----------------------------------------------------------- navigation
    def go_to_page(self, page: int, y_pt: float | None = None, add_history=True,
                   x_pt: float | None = None):
        n = self.doc.page_count
        if not n:
            return
        page = max(0, min(n - 1, page))
        if add_history:
            self._push_history()
        self._stop_smooth_scroll()
        if self.layout_mode in ("single", "two"):
            if self._row_of(page) != self._row_of(self._single_page) or self._pos[page] is None:
                self._single_page = page
                self._relayout(keep_anchor=False)
        if self.fit_mode == "page" and self.layout_mode in ("continuous", "two_continuous"):
            pass
        x, y, w, h = self._pos[page]
        d = self._dpr
        _, gap, _ = self._margins()
        if y_pt is None:
            target = y / d - (gap / 2 if not self.presentation else 0)
            if self.fit_mode == "page" or self.presentation:
                vh = self.viewport().height()
                target = y / d - max(0, (vh - h / d) / 2)
        else:
            target = (y + y_pt * self.scale_dev) / d - 30
        self.verticalScrollBar().setValue(round(target))
        hs = self.horizontalScrollBar()
        if x_pt is not None:
            hs.setValue(round((x + x_pt * self.scale_dev) / d - 30))
        elif hs.maximum() > 0:
            vw = self.viewport().width()
            row = [i for i in self._rows[self._row_of(page)] if self._pos[i] is not None]
            rx0 = min(self._pos[i][0] for i in row)
            rx1 = max(self._pos[i][0] + self._pos[i][2] for i in row)
            if (rx1 - rx0) / d <= vw:  # center the row horizontally
                hs.setValue(round((rx0 + rx1) / 2 / d - vw / 2))
            elif not (x / d <= hs.value() <= (x + w) / d - vw):
                hs.setValue(round(x / d))
        self.current_page = page
        self.currentPageChanged.emit(page)
        self._update_current_page()
        self.viewport().update()

    def next_page(self):
        step = 2 if self.layout_mode in ("two", "two_continuous") else 1
        self.go_to_page(self.current_page + step, add_history=False)

    def prev_page(self):
        step = 2 if self.layout_mode in ("two", "two_continuous") else 1
        self.go_to_page(self.current_page - step, add_history=False)

    def first_page(self):
        self.go_to_page(0)

    def last_page(self):
        self.go_to_page(self.doc.page_count - 1)

    def _push_history(self):
        entry = (self.current_page, self._anchor())
        if not self._history or self._history[-1][0] != entry[0]:
            self._history.append(entry)
            del self._history[:-100]
        self._future.clear()
        self.historyChanged.emit()

    def can_go_back(self):
        return bool(self._history)

    def can_go_forward(self):
        return bool(self._future)

    def go_back(self):
        if not self._history:
            return
        self._future.append((self.current_page, self._anchor()))
        page, anchor = self._history.pop()
        self._restore_history(page, anchor)

    def go_forward(self):
        if not self._future:
            return
        self._history.append((self.current_page, self._anchor()))
        page, anchor = self._future.pop()
        self._restore_history(page, anchor)

    def _restore_history(self, page, anchor):
        self.go_to_page(page, add_history=False)
        if anchor and self.layout_mode in ("continuous", "two_continuous"):
            self._restore_anchor(anchor)
        self.historyChanged.emit()

    def scroll_state(self) -> dict:
        a = self._anchor()
        return {"page": self.current_page, "frac": a[1] if a else 0.0}

    def restore_scroll_state(self, st: dict):
        page = int(st.get("page", 0))
        if not (0 <= page < self.doc.page_count):
            return
        self.go_to_page(page, add_history=False)
        frac = float(st.get("frac", 0.0))
        if self.layout_mode in ("continuous", "two_continuous") and self._pos[page]:
            self._restore_anchor((page, frac, 0.5))

    def _update_current_page(self):
        if not self._pos:
            return
        sx, sy = self._offset_dev()
        d = self._dpr
        top, bottom = sy, sy + self.viewport().height() * d
        best, best_vis = self.current_page, -1
        for i in self._visible_pages():
            x, y, w, h = self._pos[i]
            vis = min(bottom, y + h) - max(top, y)
            if vis > best_vis + 1:
                best, best_vis = i, vis
        if self.layout_mode in ("single", "two"):
            row = self._rows[self._row_of(self._single_page)] if self._rows else [0]
            if best not in row:
                best = row[0]
        if best != self.current_page:
            self.current_page = best
            self.currentPageChanged.emit(best)

    # ============================================================== painting
    def paintEvent(self, event):
        if abs((self.devicePixelRatioF() or 1.0) - self._dpr) > 1e-3:
            self._relayout()
        t = theme.current()
        p = QPainter(self.viewport())
        bg = QColor("#000000") if self.presentation else QColor(t.canvas)
        p.fillRect(self.viewport().rect(), bg)
        if not self._pos:
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        d = self._dpr
        sx, sy = self._offset_dev()
        vw_dev = self.viewport().width() * d
        vh_dev = self.viewport().height() * d
        s = self.scale_dev
        visible = self._visible_pages()
        wanted: set = set()

        # prefetch the neighbourhood first so visible tiles are rendered first
        if visible:
            for i in (max(visible) + 1, min(visible) - 1, max(visible) + 2):
                if 0 <= i < len(self._pos) and self._pos[i] is not None:
                    self._request_page(i, s, wanted, sx, sy, vw_dev, vh_dev * 2, prefetch=True)

        for i in visible:
            x, y, w, h = self._pos[i]
            target = QRectF((x - sx) / d, (y - sy) / d, w / d, h / d)
            if not self.presentation:
                self._paint_shadow(p, target)
            pw, ph = self._painted_size(i, s)
            tw, th, cols, rows = tile_grid(pw, ph)
            # visible tile range
            c0 = max(0, int((sx - x) // tw))
            c1 = min(cols - 1, int((sx + vw_dev - x) // tw))
            r0 = max(0, int((sy - y) // th))
            r1 = min(rows - 1, int((sy + vh_dev - y) // th))
            tiles = []
            missing = False
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    key = self.renderer.tile_key(i, s, c, r, self.invert, cols * rows == 1)
                    pm = self.renderer.get(key)
                    wanted.add(key)
                    if pm is None:
                        missing = True
                        clip = None if cols * rows == 1 else (
                            c * tw / s, r * th / s, min(pw, (c + 1) * tw) / s, min(ph, (r + 1) * th) / s)
                        self.renderer.request_tile(key, s, clip)
                    tiles.append((c, r, pm))
            if missing:
                fb = self.renderer.best_fallback(i, self.invert)
                if fb is not None:
                    fb.setDevicePixelRatio(1.0)
                    p.drawPixmap(target, fb, QRectF(fb.rect()))
                else:
                    p.fillRect(target, QColor("#000000") if self.invert else QColor("#ffffff"))
                    self.renderer.request_thumb(self.renderer.thumb_key(i, self.invert))
            # draw sharp tiles pixel for pixel (no scaling -> no blur)
            p.save()
            p.setClipRect(target)
            for c, r, pm in tiles:
                if pm is None:
                    continue
                pm.setDevicePixelRatio(d)
                p.drawPixmap(QPointF((x + c * tw - sx) / d, (y + r * th - sy) / d), pm)
            p.restore()
            self._paint_overlays(p, i)

        self.renderer.retain_tiles(wanted)
        self._paint_drag(p)
        if self._indicator_timer.isActive() and not self.presentation:
            self._paint_page_indicator(p)
        if self._mmb is not None:
            self._paint_mmb_anchor(p)
        p.end()

    def _painted_size(self, i, s):
        """Exact pixel size MuPDF produces for page ``i`` at scale ``s``.

        Using MuPDF's own rounding keeps the layout and the rendered images
        the same size, so pages are drawn 1:1 and never resampled (blurred).
        """
        w, h = self.doc.page_sizes[i]
        return max(1, math.ceil(w * s - 1e-3)), max(1, math.ceil(h * s - 1e-3))

    def _request_page(self, i, s, wanted, sx, sy, vw_dev, vh_dev, prefetch=False):
        x, y, w, h = self._pos[i]
        pw, ph = self._painted_size(i, s)
        tw, th, cols, rows = tile_grid(pw, ph)
        if cols * rows > 4:
            # large zoom: only prefetch a low-res placeholder
            self.renderer.request_thumb(self.renderer.thumb_key(i, self.invert))
            return
        for r in range(rows):
            for c in range(cols):
                key = self.renderer.tile_key(i, s, c, r, self.invert, cols * rows == 1)
                wanted.add(key)
                if self.renderer.get(key) is None:
                    clip = None if cols * rows == 1 else (
                        c * tw / s, r * th / s, min(pw, (c + 1) * tw) / s, min(ph, (r + 1) * th) / s)
                    self.renderer.request_tile(key, s, clip)

    def _paint_shadow(self, p: QPainter, r: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        dark = theme.current().name == "dark"
        for k, a in ((1, 34), (2, 18), (3, 10), (4, 5)):
            c = QColor(0, 0, 0, a * (2 if dark else 1))
            p.setBrush(c)
            p.drawRect(r.adjusted(-k + 1, -k + 2, k - 1, k))

    def _paint_overlays(self, p: QPainter, i: int):
        # search hits
        if self.search.hits and self.search._pattern:
            hits = self.search.page_hit_rects(i)
            if hits:
                cur = self.search.hits[self.current_hit] if 0 <= self.current_hit < len(self.search.hits) else None
                p.setPen(Qt.PenStyle.NoPen)
                for occ, rects in enumerate(hits):
                    is_cur = cur is not None and cur.page == i and cur.occ == occ
                    if is_cur:
                        p.setBrush(QColor(255, 120, 0, 140))
                    else:
                        p.setBrush(QColor(255, 215, 0, 110))
                    for r in rects:
                        rr = self.page_rect_to_widget(i, r).adjusted(-1, -1, 1, 1)
                        p.drawRect(rr)
                        if is_cur:
                            p.setPen(QPen(QColor(230, 90, 0), 1.5))
                            p.drawRect(rr)
                            p.setPen(Qt.PenStyle.NoPen)
        # text selection
        if self._sel is not None:
            rects = self._selection_rects(i)
            if rects:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(20, 115, 230, 80))
                for r in rects:
                    p.drawRect(self.page_rect_to_widget(i, r))

    def _paint_drag(self, p: QPainter):
        dr = self._drag
        if not dr:
            return
        kind = dr.get("kind")
        if kind == "ink" and len(dr["points"]) > 1:
            i = dr["page"]
            path = QPainterPath(self.page_to_widget(i, *dr["points"][0]))
            for pt in dr["points"][1:]:
                path.lineTo(self.page_to_widget(i, *pt))
            pen = QPen(_qcolor(self.tool_colors["ink"]), max(1.0, 2 * self.zoom * PT_TO_PX))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        elif kind in ("rect", "ellipse", "textbox") and dr.get("end"):
            i = dr["page"]
            r = QRectF(self.page_to_widget(i, *dr["start"]), self.page_to_widget(i, *dr["end"])).normalized()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = _qcolor(self.tool_colors.get(kind, (0.1, 0.45, 0.9)))
            p.setPen(QPen(col, 2 if kind != "textbox" else 1, Qt.PenStyle.SolidLine if kind != "textbox" else Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if kind == "ellipse":
                p.drawEllipse(r)
            else:
                p.drawRect(r)

    def _paint_mmb_anchor(self, p: QPainter):
        """Round marker with arrows at the middle-click anchor point."""
        c = self._mmb["anchor"]
        horiz = self.horizontalScrollBar().maximum() > 0
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(60, 60, 60, 200), 1.2))
        p.setBrush(QColor(255, 255, 255, 225))
        p.drawEllipse(c, 15.0, 15.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(50, 50, 50, 230))
        arrows = [((0, -1), (1, 0)), ((0, 1), (1, 0))]
        if horiz:
            arrows += [((-1, 0), (0, 1)), ((1, 0), (0, 1))]
        for (dx, dy), (px, py) in arrows:
            tip = QPointF(c.x() + dx * 11, c.y() + dy * 11)
            base = QPointF(c.x() + dx * 5.5, c.y() + dy * 5.5)
            path = QPainterPath(tip)
            path.lineTo(base.x() + px * 4.5, base.y() + py * 4.5)
            path.lineTo(base.x() - px * 4.5, base.y() - py * 4.5)
            path.closeSubpath()
            p.drawPath(path)
        p.drawEllipse(c, 2.0, 2.0)
        p.restore()

    def _paint_page_indicator(self, p: QPainter):
        text = f"{self.current_page + 1} из {self.doc.page_count}"
        f = p.font()
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 24
        h = fm.height() + 12
        r = QRectF(self.viewport().width() - w - 18, self.viewport().height() - h - 18, w, h)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(40, 40, 40, 200))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    # ------------------------------------------------------------- updates
    def _on_tile_ready(self, key):
        i = key[2]
        r = self.page_rect_widget(i) if 0 <= i < len(self._pos) else None
        if r is not None and r.intersects(QRectF(self.viewport().rect())):
            self.viewport().update(r.toAlignedRect().adjusted(-2, -2, 2, 2))

    def _on_hit_rects(self, page):
        if self._pending_reveal is not None and self._pending_reveal[0] == page:
            idx = self._pending_reveal[1]
            self._pending_reveal = None
            self._reveal_hit(idx)
        r = self.page_rect_widget(page) if page < len(self._pos) else None
        if r is not None:
            self.viewport().update(r.toAlignedRect())

    def _on_structure_changed(self):
        self._sel = None
        self._annot_cache.clear()
        self.current_hit = -1
        self._single_page = min(self._single_page, max(0, self.doc.page_count - 1))
        self.current_page = min(self.current_page, max(0, self.doc.page_count - 1))
        self._relayout()

    def _on_page_changed(self, page):
        self._annot_cache.pop(page, None)
        self._sel_rect_cache.clear()
        self.viewport().update()

    def _on_scrolled(self):
        self._update_current_page()
        if not self.presentation:
            self._indicator_timer.start()
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout(keep_anchor=True)
        if self.fit_mode:
            self.zoomChanged.emit(self.zoom)

    # ================================================================ search
    def show_hit(self, idx: int):
        hits = self.search.hits
        if not (0 <= idx < len(hits)):
            self.current_hit = -1
            self.viewport().update()
            return
        self.current_hit = idx
        self._reveal_hit(idx)

    def _reveal_hit(self, idx):
        hit = self.search.hits[idx] if idx < len(self.search.hits) else None
        if hit is None:
            return
        rects = self.search.page_hit_rects(hit.page)
        if rects is None:
            self._pending_reveal = (hit.page, idx)
            if not self._page_in_view(hit.page):
                self.go_to_page(hit.page, add_history=False)
            return
        if hit.occ < len(rects) and rects[hit.occ]:
            r = rects[hit.occ][0]
            self.ensure_visible(hit.page, r)
        else:
            self.go_to_page(hit.page, add_history=False)
        self.viewport().update()

    def _page_in_view(self, page) -> bool:
        r = self.page_rect_widget(page)
        return r is not None and QRectF(self.viewport().rect()).intersects(r)

    def ensure_visible(self, page: int, rect):
        if self.layout_mode in ("single", "two") and self._pos[page] is None:
            self.go_to_page(page, add_history=False)
        wr = self.page_rect_to_widget(page, rect)
        vr = QRectF(self.viewport().rect())
        margin_y = vr.height() * 0.3
        margin_x = 40
        vs, hs = self.verticalScrollBar(), self.horizontalScrollBar()
        if wr.top() < 10 or wr.bottom() > vr.height() - 10:
            vs.setValue(round(vs.value() + wr.top() - margin_y))
        if wr.left() < 10 or wr.right() > vr.width() - 10:
            hs.setValue(round(hs.value() + wr.left() - margin_x))
        self._update_current_page()

    # ============================================================ selection
    def _word_at(self, page, x, y):
        words = self.doc.words(page)
        best, best_d = -1, float("inf")
        for k, w in enumerate(words):
            dx = max(w[0] - x, 0, x - w[2])
            dy = max(w[1] - y, 0, y - w[3])
            dd = dx + dy * 3
            if dd < best_d:
                best, best_d = k, dd
                if dd == 0:
                    break
        return best, best_d

    def _sel_bounds(self):
        if self._sel is None:
            return None
        ap, ai, fp, fi = self._sel
        if (ap, ai) <= (fp, fi):
            return ap, ai, fp, fi
        return fp, fi, ap, ai

    def _page_sel_range(self, page):
        b = self._sel_bounds()
        if b is None:
            return None
        p0, i0, p1, i1 = b
        if page < p0 or page > p1:
            return None
        words = self.doc.words(page)
        if not words:
            return None
        start = i0 if page == p0 else 0
        end = i1 if page == p1 else len(words) - 1
        if start < 0 or end < start:
            return None
        return start, min(end, len(words) - 1)

    def _selection_rects(self, page):
        key = (page, self._sel)
        if key in self._sel_rect_cache:
            return self._sel_rect_cache[key]
        rng = self._page_sel_range(page)
        rects = []
        if rng:
            words = self.doc.words(page)
            cur_line = None
            for w in words[rng[0]: rng[1] + 1]:
                line = (w[5], w[6])
                if line == cur_line and rects:
                    r = rects[-1]
                    rects[-1] = (min(r[0], w[0]), min(r[1], w[1]), max(r[2], w[2]), max(r[3], w[3]))
                else:
                    rects.append((w[0], w[1], w[2], w[3]))
                    cur_line = line
        if len(self._sel_rect_cache) > 200:
            self._sel_rect_cache.clear()
        self._sel_rect_cache[key] = rects
        return rects

    def has_selection(self) -> bool:
        b = self._sel_bounds()
        if b is None:
            return False
        return any(self._page_sel_range(p) for p in range(b[0], b[2] + 1))

    def selected_text(self) -> str:
        b = self._sel_bounds()
        if b is None:
            return ""
        lines = []
        for page in range(b[0], b[2] + 1):
            rng = self._page_sel_range(page)
            if not rng:
                continue
            cur_line = None
            parts: list[str] = []
            for w in self.doc.words(page)[rng[0]: rng[1] + 1]:
                line = (w[5], w[6])
                if line != cur_line and parts:
                    lines.append(" ".join(parts))
                    parts = []
                cur_line = line
                parts.append(w[4])
            if parts:
                lines.append(" ".join(parts))
        return "\n".join(lines)

    def copy_selection(self):
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.statusMessage.emit("Текст скопирован в буфер обмена")

    def select_all(self):
        n = self.doc.page_count
        if not n:
            return
        last = len(self.doc.words(n - 1)) - 1
        self._sel = (0, 0, n - 1, max(0, last))
        self._sel_rect_cache.clear()
        self.selectionChanged.emit(True)
        self.viewport().update()

    def clear_selection(self):
        if self._sel is not None:
            self._sel = None
            self._sel_rect_cache.clear()
            self.selectionChanged.emit(False)
            self.viewport().update()

    def markup_selection(self, kind: str):
        b = self._sel_bounds()
        if b is None:
            return
        color = self.tool_colors.get(kind, DEFAULT_COLORS["highlight"])
        added = False
        for page in range(b[0], b[2] + 1):
            rects = self._selection_rects(page)
            if rects:
                self.doc.add_text_markup(page, rects, kind, color)
                added = True
        self.clear_selection()
        if added:
            self.statusMessage.emit("Комментарий добавлен")

    # ============================================================== mouse
    def _update_cursor(self, pos: QPointF | None = None):
        if self._space_pan or self.tool == "hand":
            cur = Qt.CursorShape.ClosedHandCursor if self._drag and self._drag.get("kind") == "pan" \
                else Qt.CursorShape.OpenHandCursor
            self.viewport().setCursor(cur)
            return
        if self.tool in ("note", "text", "ink", "rect", "ellipse"):
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            return
        if self.tool == "eraser":
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            return
        if self._drag and self._drag.get("kind") == "pan":
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if pos is not None:
            hit = self.widget_to_page(pos)
            if hit:
                if self._link_at(*hit):
                    self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    return
                if self.tool in MARKUP_TOOLS:
                    self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                    return
                _, dist = self._word_at(*hit)
                if dist < 4:
                    self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                    return
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def _link_at(self, page, x, y):
        for ln in self.doc.links(page):
            r = ln["vrect"]
            if r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1:
                return ln
        return None

    def _annots(self, page):
        rev = self.doc.page_rev[page]
        c = self._annot_cache.get(page)
        if c is None or c[0] != rev:
            c = (rev, self.doc.annotations(page))
            self._annot_cache[page] = c
        return c[1]

    def _annot_at(self, page, x, y):
        best = None
        for a in self._annots(page):
            r = a["rect"]
            if r.x0 - 2 <= x <= r.x1 + 2 and r.y0 - 2 <= y <= r.y1 + 2:
                if best is None or r.get_area() < best["rect"].get_area():
                    best = a
        return best

    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        self._stop_smooth_scroll()
        if self._autoscroll_on:
            self.stop_autoscroll()
        if self._mmb is not None:
            # any click ends the latched middle-button scrolling
            self._end_mmb()
            return
        if e.button() == Qt.MouseButton.MiddleButton:
            self._start_mmb(pos)
            return
        if e.button() == Qt.MouseButton.LeftButton and (self.tool == "hand" or self._space_pan):
            self._drag = {"kind": "pan", "last": pos, "start": pos, "moved": False,
                          "hit": self.widget_to_page(pos)}
            self._update_cursor()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        if self.presentation:
            self.next_page()
            return
        hit = self.widget_to_page(pos)
        tool = self.tool
        if tool == "select" or tool in MARKUP_TOOLS:
            if hit is None and tool == "select":
                self.clear_selection()
                self._drag = {"kind": "pan", "last": pos, "start": pos, "moved": False, "hit": None}
                return
            if hit is None:
                return
            page, x, y = hit
            if tool == "select" and self._link_at(page, x, y):
                self._drag = {"kind": "link", "start": pos, "hit": hit}
                return
            idx, dist = self._word_at(page, x, y)
            if tool == "select" and (idx < 0 or dist > 14):
                self.clear_selection()
                self._drag = {"kind": "pan", "last": pos, "start": pos, "moved": False, "hit": hit}
                self._update_cursor()
                return
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._sel is not None:
                self._sel = (self._sel[0], self._sel[1], page, idx)
            else:
                self._sel = (page, idx, page, idx)
                self._sel_empty = True
            self._sel_rect_cache.clear()
            self._drag = {"kind": "select", "start": pos, "moved": False}
            self.viewport().update()
            return
        if hit is None:
            return
        page, x, y = hit
        if tool == "eraser":
            a = self._annot_at(page, x, y)
            if a is not None:
                self.doc.delete_annotation(page, a["xref"])
                self.statusMessage.emit("Комментарий удалён")
            return
        if tool == "note":
            text, ok = QInputDialog.getMultiLineText(self, "Записка", "Текст записки:")
            if ok and text.strip():
                self.doc.add_note(page, (x, y), text, self.tool_colors["note"])
            return
        if tool in ("ink",):
            self._drag = {"kind": "ink", "page": page, "points": [(x, y)]}
            return
        if tool in ("rect", "ellipse", "text"):
            self._drag = {"kind": tool if tool != "text" else "textbox", "page": page,
                          "start": (x, y), "end": None}
            return

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._mmb is not None:
            d = pos - self._mmb["anchor"]
            self._mmb["moved"] = max(self._mmb["moved"], abs(d.x()) + abs(d.y()))
            return
        dr = self._drag
        if dr is None:
            self._update_cursor(pos)
            self._hover_tooltip(pos)
            return
        kind = dr["kind"]
        if kind == "pan":
            delta = pos - dr["last"]
            dr["last"] = pos
            if (pos - dr["start"]).manhattanLength() > 3:
                dr["moved"] = True
            self.horizontalScrollBar().setValue(round(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(round(self.verticalScrollBar().value() - delta.y()))
            return
        if kind == "link":
            if (pos - dr["start"]).manhattanLength() > 6:
                page, x, y = dr["hit"]
                idx, _ = self._word_at(page, x, y)
                self._sel = (page, idx, page, idx)
                self._drag = {"kind": "select", "start": dr["start"], "moved": True}
            return
        if kind == "select":
            if (pos - dr["start"]).manhattanLength() > 3:
                dr["moved"] = True
            hit = self.widget_to_page(pos, nearest=True)
            if hit and self._sel is not None:
                page, x, y = hit
                idx, _ = self._word_at(page, x, y)
                if idx >= 0:
                    self._sel = (self._sel[0], self._sel[1], page, idx)
                    self._sel_rect_cache.clear()
                    self.viewport().update()
            self._edge_autoscroll(pos)
            return
        if kind == "ink":
            i = dr["page"]
            r = self.page_rect_widget(i)
            if r is None:
                return
            pt = self._clamped_page_point(i, pos)
            dr["points"].append(pt)
            self.viewport().update()
            return
        if kind in ("rect", "ellipse", "textbox"):
            dr["end"] = self._clamped_page_point(dr["page"], pos)
            self.viewport().update()

    def _clamped_page_point(self, i, pos):
        p = self._pos[i]
        sx, sy = self._offset_dev()
        d = self._dpr
        s = self.scale_dev
        X = (pos.x() * d + sx - p[0]) / s
        Y = (pos.y() * d + sy - p[1]) / s
        w, h = self.doc.page_sizes[i]
        return min(max(X, 0), w), min(max(Y, 0), h)

    def _edge_autoscroll(self, pos):
        h = self.viewport().height()
        vs = self.verticalScrollBar()
        if pos.y() < 10:
            vs.setValue(vs.value() - 20)
        elif pos.y() > h - 10:
            vs.setValue(vs.value() + 20)

    def mouseReleaseEvent(self, e):
        if self._mmb is not None and e.button() == Qt.MouseButton.MiddleButton and self._mmb["held"]:
            self._mmb["held"] = False
            # a long press or a press-and-move is temporary scrolling;
            # a short click keeps the mode on until the next click
            if time.perf_counter() - self._mmb["t0"] > 0.35 or self._mmb["moved"] > 12:
                self._end_mmb()
            return
        dr = self._drag
        self._drag = None
        if dr is None:
            return super().mouseReleaseEvent(e)
        kind = dr["kind"]
        pos = e.position()
        if kind == "pan":
            self._update_cursor(pos)
            if not dr["moved"] and dr.get("hit") and self.tool in ("hand",):
                ln = self._link_at(*dr["hit"])
                if ln:
                    self._follow_link(ln)
            return
        if kind == "link":
            ln = self._link_at(*dr["hit"])
            if ln:
                self._follow_link(ln)
            return
        if kind == "select":
            if not dr["moved"]:
                self.clear_selection()
                return
            has = self.has_selection()
            self.selectionChanged.emit(has)
            if has and self.tool in MARKUP_TOOLS:
                self.markup_selection(self.tool)
            return
        if kind == "ink":
            pts = dr["points"]
            if len(pts) > 1:
                width = 2.0
                self.doc.add_ink(dr["page"], [pts], self.tool_colors["ink"], width)
            self.viewport().update()
            return
        if kind in ("rect", "ellipse"):
            if dr.get("end"):
                r = fitz.Rect(dr["start"], dr["end"]).normalize()
                if r.width > 3 and r.height > 3:
                    self.doc.add_shape(dr["page"], r, kind, self.tool_colors[kind])
            self.viewport().update()
            return
        if kind == "textbox":
            self.viewport().update()
            text, ok = QInputDialog.getMultiLineText(self, "Текстовое поле", "Текст:")
            if not ok or not text.strip():
                return
            fs = 12
            if dr.get("end") and fitz.Rect(dr["start"], dr["end"]).normalize().width > 20:
                r = fitz.Rect(dr["start"], dr["end"]).normalize()
            else:
                lines = text.splitlines() or [text]
                w = max(len(ln) for ln in lines) * fs * 0.55 + 12
                h = len(lines) * fs * 1.35 + 10
                x, y = dr["start"]
                r = fitz.Rect(x, y, x + w, y + h)
            pw, ph = self.doc.page_sizes[dr["page"]]
            r = r & fitz.Rect(0, 0, pw, ph)
            self.doc.add_freetext(dr["page"], r, text, fs, self.tool_colors["text"])

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.presentation:
            return
        hit = self.widget_to_page(e.position())
        if not hit:
            return
        page, x, y = hit
        a = self._annot_at(page, x, y)
        if a is not None and a["type"] in ("Text", "FreeText") and self.tool in ("select", "hand"):
            self._edit_annotation(page, a)
            return
        if self.tool in ("select",) + MARKUP_TOOLS:
            idx, dist = self._word_at(page, x, y)
            if idx >= 0 and dist < 4:
                self._sel = (page, idx, page, idx)
                self._sel_rect_cache.clear()
                self.selectionChanged.emit(True)
                self.viewport().update()

    def _hover_tooltip(self, pos):
        hit = self.widget_to_page(pos)
        if not hit:
            QToolTip.hideText()
            return
        ln = self._link_at(*hit)
        if ln and ln.get("uri"):
            QToolTip.showText(QCursor.pos(), ln["uri"], self.viewport())
            return
        if ln:
            tgt = self.doc.resolve_link_target(ln)
            if tgt:
                QToolTip.showText(QCursor.pos(), f"Перейти на страницу {tgt[0] + 1}", self.viewport())
                return
        a = self._annot_at(*hit)
        if a and a["content"]:
            head = a["author"] + "\n" if a["author"] else ""
            QToolTip.showText(QCursor.pos(), head + a["content"][:600], self.viewport())
            return
        QToolTip.hideText()

    def _follow_link(self, ln):
        uri = ln.get("uri")
        if uri:
            if uri.startswith(("http://", "https://", "mailto:")):
                QDesktopServices.openUrl(QUrl(uri))
            else:
                self.statusMessage.emit(f"Ссылка: {uri}")
            return
        tgt = self.doc.resolve_link_target(ln)
        if tgt:
            page, y = tgt
            self.go_to_page(page, y_pt=y, add_history=True)

    # ------------------------------------------------------------ context
    def contextMenuEvent(self, e):
        pos = QPointF(e.pos())
        hit = self.widget_to_page(pos)
        m = QMenu(self)
        if hit:
            a = self._annot_at(*hit)
            if a is not None:
                page = hit[0]
                if a["type"] in ("Text", "FreeText"):
                    m.addAction(icons.icon("note"), "Изменить текст…",
                                lambda: self._edit_annotation(page, a))
                if a["type"] != "Widget":
                    m.addAction(icons.icon("palette"), "Цвет…", lambda: self._recolor_annotation(page, a))
                    m.addAction(icons.icon("trash"), "Удалить комментарий",
                                lambda: self.doc.delete_annotation(page, a["xref"]))
                m.addSeparator()
        if self.has_selection():
            m.addAction(icons.icon("copy"), "Копировать", self.copy_selection)
            m.addAction(icons.icon("highlight"), "Выделить цветом", lambda: self.markup_selection("highlight"))
            m.addAction(icons.icon("underline"), "Подчеркнуть", lambda: self.markup_selection("underline"))
            m.addAction(icons.icon("strikeout"), "Зачеркнуть", lambda: self.markup_selection("strikeout"))
            m.addSeparator()
        m.addAction(icons.icon("select"), "Инструмент выделения", lambda: self.set_tool("select"))
        m.addAction(icons.icon("hand"), "Рука", lambda: self.set_tool("hand"))
        m.addSeparator()
        m.addAction(icons.icon("prev"), "Предыдущая страница", self.prev_page)
        m.addAction(icons.icon("next"), "Следующая страница", self.next_page)
        if self.can_go_back():
            m.addAction(icons.icon("back"), "Назад", self.go_back)
        m.addSeparator()
        m.addAction(icons.icon("zoom_in"), "Увеличить", self.zoom_in)
        m.addAction(icons.icon("zoom_out"), "Уменьшить", self.zoom_out)
        m.addAction(icons.icon("fit_width"), "По ширине", lambda: self.set_fit("width"))
        m.addAction(icons.icon("fit_page"), "Страница целиком", lambda: self.set_fit("page"))
        if hit:
            m.addSeparator()
            m.addAction(icons.icon("rotate_cw"), "Повернуть страницу по часовой",
                        lambda: self.doc.rotate_pages([hit[0]], 90))
        m.exec(e.globalPos())

    def _edit_annotation(self, page, a):
        text, ok = QInputDialog.getMultiLineText(self, "Комментарий", "Текст:", a["content"])
        if ok:
            self.doc.set_annotation_content(page, a["xref"], text)

    def _recolor_annotation(self, page, a):
        c = QColorDialog.getColor(QColor("#ffd400"), self, "Цвет комментария")
        if c.isValid():
            self.doc.set_annotation_color(page, a["xref"], (c.redF(), c.greenF(), c.blueF()))

    # ============================================================ scrolling
    def wheelEvent(self, e):
        if self._mmb is not None:
            self._end_mmb()
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y() or e.pixelDelta().y()
            if dy:
                factor = 1.1 ** (dy / 120)
                self.set_zoom(self.zoom * factor, e.position())
            e.accept()
            return
        pd = e.pixelDelta()
        ad = e.angleDelta()
        horizontal = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if not pd.isNull() and not horizontal:
            # precise touchpad scrolling is already smooth
            self._stop_smooth_scroll()
            hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
            hs.setValue(hs.value() - pd.x())
            if not self._single_page_flip(-pd.y()):
                self._set_scroll_y(self._current_y() - pd.y())
            e.accept()
            return
        dy = ad.y()
        dx = ad.x()
        if horizontal and dy and not dx:
            dx, dy = dy, 0
        if dx:
            hs = self.horizontalScrollBar()
            hs.setValue(hs.value() - round(dx / 120 * 80))
        if dy:
            lines = QApplication.wheelScrollLines() or 3
            step = -dy / 120 * lines * 40
            if self._single_page_flip(step):
                e.accept()
                return
            self.smooth_scroll_by(step)
        e.accept()

    def _single_page_flip(self, delta) -> bool:
        if self.layout_mode not in ("single", "two") and not self.presentation:
            return False
        vs = self.verticalScrollBar()
        if self.presentation and self.layout_mode not in ("single", "two"):
            return False
        at_bottom = vs.value() >= vs.maximum()
        at_top = vs.value() <= vs.minimum()
        if (delta > 0 and at_bottom) or (delta < 0 and at_top):
            self._wheel_accum += delta
            if abs(self._wheel_accum) >= 100:
                forward = self._wheel_accum > 0
                self._wheel_accum = 0
                if forward and self.current_page < self.doc.page_count - 1:
                    self.next_page()
                elif not forward and self.current_page > 0:
                    self.prev_page()
                    vs.setValue(vs.maximum())
            return True
        self._wheel_accum = 0
        return False

    def smooth_scroll_by(self, delta: float):
        vs = self.verticalScrollBar()
        base = self._scroll_target if self._scroll_target is not None else self._current_y()
        self._scroll_target = max(float(vs.minimum()), min(float(vs.maximum()), base + delta))
        self._run_clock(True)

    def _stop_smooth_scroll(self):
        self._scroll_target = None
        if not self._clock_needed():
            self._run_clock(False)

    def _clock_needed(self) -> bool:
        return self._scroll_target is not None or self._autoscroll_on or self._mmb is not None

    # ------------------------------------------------- middle-button scrolling
    MMB_DEADZONE = 6.0

    def _start_mmb(self, pos: QPointF):
        self._mmb = {"anchor": QPointF(pos), "t0": time.perf_counter(), "held": True,
                     "moved": 0.0, "acc_x": 0.0}
        horiz = self.horizontalScrollBar().maximum() > 0
        self.viewport().setCursor(Qt.CursorShape.SizeAllCursor if horiz else Qt.CursorShape.SizeVerCursor)
        self._run_clock(True)
        self.viewport().update()

    def _end_mmb(self):
        if self._mmb is None:
            return
        self._mmb = None
        if not self._clock_needed():
            self._run_clock(False)
        self._update_cursor(QPointF(self.viewport().mapFromGlobal(QCursor.pos())))
        self.viewport().update()

    def _mmb_speed(self, d: float) -> float:
        """Scroll speed (logical px/s) for a cursor offset from the anchor."""
        dist = abs(d) - self.MMB_DEADZONE
        if dist <= 0:
            return 0.0
        return math.copysign(3.2 * dist ** 1.35, d)

    def focusOutEvent(self, e):
        self._end_mmb()
        super().focusOutEvent(e)

    def _run_clock(self, on: bool):
        if on and not self._clock_active:
            self._clock_active = True
            self._last_frame = None
            clock().acquire()
        elif not on and self._clock_active:
            self._clock_active = False
            clock().release()

    def _on_frame(self, t: float):
        """One display frame: advance smooth scrolling / autoscroll."""
        if not self._clock_active:
            return
        dt = (t - self._last_frame) if self._last_frame is not None else 1.0 / refresh_rate()
        dt = max(0.0, min(dt, 0.05))
        self._last_frame = t
        y = self._current_y()
        vs = self.verticalScrollBar()
        if self._mmb is not None:
            pos = QPointF(self.viewport().mapFromGlobal(QCursor.pos()))
            d = pos - self._mmb["anchor"]
            vy = self._mmb_speed(d.y())
            if vy and not self._single_page_flip(vy * dt):
                self._set_scroll_y(y + vy * dt)
            hs = self.horizontalScrollBar()
            if hs.maximum() > 0:
                self._mmb["acc_x"] += self._mmb_speed(d.x()) * dt
                step = int(self._mmb["acc_x"])
                if step:
                    self._mmb["acc_x"] -= step
                    hs.setValue(hs.value() + step)
        elif self._scroll_target is not None:
            target = self._scroll_target
            ny = y + (target - y) * (1.0 - math.exp(-dt / 0.045))
            if abs(target - ny) * self._dpr < 0.5:
                ny = target
                self._scroll_target = None
            self._set_scroll_y(ny)
        elif self._autoscroll_on:
            self._set_scroll_y(y + self._autoscroll_speed * dt)
            if vs.value() >= vs.maximum():
                self.stop_autoscroll()
        else:
            self._run_clock(False)
            return
        self.viewport().repaint()  # present this frame right away
        if not self._clock_needed():
            self._run_clock(False)

    # ------------------------------------------------------------ autoscroll
    def toggle_autoscroll(self):
        if self._autoscroll_on:
            self.stop_autoscroll()
        else:
            self._autoscroll_on = True
            self._scroll_target = None
            self._run_clock(True)
            self.statusMessage.emit("Автопрокрутка: ↑/↓ — скорость, Esc — стоп")

    def stop_autoscroll(self):
        self._autoscroll_on = False
        if not self._clock_needed():
            self._run_clock(False)
        self.statusMessage.emit("")

    # ============================================================== keyboard
    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        vs, hs = self.verticalScrollBar(), self.horizontalScrollBar()
        if self._autoscroll_on:
            if key == Qt.Key.Key_Up:
                self._autoscroll_speed = max(10.0, self._autoscroll_speed / 1.4)
                return
            if key == Qt.Key.Key_Down:
                self._autoscroll_speed = min(3000.0, self._autoscroll_speed * 1.4)
                return
            if key == Qt.Key.Key_Escape:
                self.stop_autoscroll()
                return
        if key == Qt.Key.Key_Escape and self._mmb is not None:
            self._end_mmb()
            return
        if key == Qt.Key.Key_Escape:
            if self._drag:
                self._drag = None
                self.viewport().update()
            elif self._sel is not None:
                self.clear_selection()
            elif self.tool != "select":
                self.set_tool("select")
            else:
                self.escapePressed.emit()
            return
        flip = self.layout_mode in ("single", "two") or self.presentation
        if key in (Qt.Key.Key_PageDown, Qt.Key.Key_Space) and not (mods & Qt.KeyboardModifier.ShiftModifier):
            if flip and (vs.value() >= vs.maximum() or self.presentation):
                self.next_page()
            else:
                self.smooth_scroll_by(self.viewport().height() - 40)
            return
        if key == Qt.Key.Key_PageUp or (key == Qt.Key.Key_Space and mods & Qt.KeyboardModifier.ShiftModifier):
            if flip and (vs.value() <= vs.minimum() or self.presentation):
                self.prev_page()
                if not self.presentation:
                    vs.setValue(vs.maximum())
            else:
                self.smooth_scroll_by(-(self.viewport().height() - 40))
            return
        if key == Qt.Key.Key_Down:
            if self.presentation:
                self.next_page()
            elif flip and vs.value() >= vs.maximum():
                self.next_page()
            else:
                self.smooth_scroll_by(60)
            return
        if key == Qt.Key.Key_Up:
            if self.presentation:
                self.prev_page()
            elif flip and vs.value() <= vs.minimum():
                self.prev_page()
                vs.setValue(vs.maximum())
            else:
                self.smooth_scroll_by(-60)
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Left):
            forward = key == Qt.Key.Key_Right
            if hs.maximum() > 0 and not self.presentation and not (mods & Qt.KeyboardModifier.AltModifier):
                hs.setValue(hs.value() + (60 if forward else -60))
            else:
                self.next_page() if forward else self.prev_page()
            return
        if key == Qt.Key.Key_Home:
            self.first_page()
            return
        if key == Qt.Key.Key_End:
            self.last_page()
            return
        if e.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        super().keyReleaseEvent(e)

    def page_count(self):
        return self.doc.page_count

    def page_label(self, i):
        return str(i + 1)

    def confirm(self, title, text) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes
