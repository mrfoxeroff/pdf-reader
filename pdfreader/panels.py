"""Side panels: page thumbnails, bookmarks, comments and search results."""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QRect, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMenu, QStyle, QStyledItemDelegate,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import icons, theme

THUMB_LOGICAL_W = 120


# ===================================================================== thumbs
class ThumbModel(QAbstractListModel):
    def __init__(self, document, renderer, invert_getter):
        super().__init__()
        self.doc = document
        self.renderer = renderer
        self.invert = invert_getter
        self.renderer.ready.connect(self._on_ready)
        self.doc.structureChanged.connect(self._reset)
        self.doc.pageChanged.connect(self._page_changed)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.doc.page_count

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        i = index.row()
        if role == Qt.ItemDataRole.DisplayRole:
            return str(i + 1)
        if role == Qt.ItemDataRole.UserRole:
            key = self.renderer.thumb_key(i, self.invert())
            pm = self.renderer.get(key)
            if pm is None:
                self.renderer.request_thumb(key)
            return pm
        if role == Qt.ItemDataRole.SizeHintRole:
            w, h = self.doc.page_sizes[i]
            th = int(THUMB_LOGICAL_W * h / max(w, 1))
            return QSize(THUMB_LOGICAL_W + 30, min(th, 260) + 34)
        return None

    def _on_ready(self, key):
        if key[0] == "p" and key[2] < self.doc.page_count:
            idx = self.index(key[2])
            self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.UserRole])

    def _page_changed(self, page):
        idx = self.index(page)
        self.dataChanged.emit(idx, idx)

    def _reset(self):
        self.beginResetModel()
        self.endResetModel()


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, current_getter, parent=None):
        super().__init__(parent)
        self.current = current_getter

    def paint(self, p: QPainter, option, index):
        t = theme.current()
        r = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        model = index.model()
        i = index.row()
        w, h = model.doc.page_sizes[i]
        tw = THUMB_LOGICAL_W
        th = int(tw * h / max(w, 1))
        if th > 260:
            th = 260
            tw = int(th * w / max(h, 1))
        x = r.x() + (r.width() - tw) // 2
        y = r.y() + 6
        target = QRect(x, y, tw, th)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if option.state & QStyle.StateFlag.State_MouseOver and not selected:
            p.fillRect(r.adjusted(4, 1, -4, -1), QColor(t.hover))
        if selected:
            p.fillRect(r.adjusted(4, 1, -4, -1), QColor(t.selection))
        pm = index.data(Qt.ItemDataRole.UserRole)
        p.fillRect(target.adjusted(1, 1, 2, 2), QColor(0, 0, 0, 40))
        if pm is not None:
            p.drawPixmap(target, pm)
        else:
            p.fillRect(target, QColor("#ffffff"))
        is_current = i == self.current()
        pen = QPen(QColor(t.accent) if is_current else QColor(t.bar_border), 2 if is_current else 1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(target)
        p.setPen(QColor(t.text if is_current else t.text_dim))
        p.drawText(QRect(r.x(), y + th + 4, r.width(), 20), Qt.AlignmentFlag.AlignHCenter, str(i + 1))
        p.restore()

    def sizeHint(self, option, index):
        return index.data(Qt.ItemDataRole.SizeHintRole)


class ThumbnailPanel(QWidget):
    pageActivated = Signal(int)

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.doc = view.doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(_title("Миниатюры страниц"))
        self.list = QListView()
        self.list.setUniformItemSizes(False)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(24)
        self.list.setMouseTracking(True)
        self.model = ThumbModel(self.doc, view.renderer, lambda: view.invert)
        self.list.setModel(self.model)
        self.list.setItemDelegate(ThumbDelegate(lambda: view.current_page, self.list))
        self.list.clicked.connect(lambda idx: self.pageActivated.emit(idx.row()))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)
        view.currentPageChanged.connect(self._on_page)
        self.page_actions = None  # set by the document tab

    def _on_page(self, page):
        if 0 <= page < self.model.rowCount():
            idx = self.model.index(page)
            if not self.list.selectionModel().isSelected(idx) or len(self.selected_pages()) <= 1:
                self.list.setCurrentIndex(idx)
            self.list.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
            self.list.viewport().update()

    def selected_pages(self) -> list[int]:
        return sorted(i.row() for i in self.list.selectionModel().selectedIndexes())

    def _menu(self, pos):
        if self.page_actions is None:
            return
        idx = self.list.indexAt(pos)
        if idx.isValid() and idx.row() not in self.selected_pages():
            self.list.setCurrentIndex(idx)
        pages = self.selected_pages() or [self.view.current_page]
        m = QMenu(self)
        self.page_actions(m, pages)
        m.exec(self.list.viewport().mapToGlobal(pos))


# ================================================================== bookmarks
class BookmarkPanel(QWidget):
    destinationActivated = Signal(int, object)  # page, y (visual pt) or None

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.doc = view.doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 6, 0)
        head.addWidget(_title("Закладки"), 1)
        for name, tip, slot in (
            ("plus", "Добавить закладку на текущую страницу", self._add),
            ("expand", "Развернуть/свернуть всё", self._toggle_expand),
        ):
            b = QToolButton()
            b.setIcon(icons.icon(name if name != "expand" else "next"))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            head.addWidget(b)
        lay.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._activate)
        self.tree.itemActivated.connect(self._activate)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree)
        self.empty = QLabel("В документе нет закладок.\nНажмите «+», чтобы добавить.")
        self.empty.setObjectName("dimLabel")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        self._expanded = False
        self._toc = []
        self.doc.outlineChanged.connect(self.reload)
        self.reload()

    def reload(self):
        self.tree.clear()
        self._toc = self.doc.toc()
        stack: list[tuple[int, QTreeWidgetItem | None]] = [(0, None)]
        for k, entry in enumerate(self._toc):
            level, title, page = entry[0], entry[1], entry[2]
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, k)
            item.setToolTip(0, f"{title} — стр. {page}")
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            stack.append((level, item))
        self.empty.setVisible(not self._toc)
        self.tree.setVisible(bool(self._toc))

    def _activate(self, item, _col=0):
        k = item.data(0, Qt.ItemDataRole.UserRole)
        if k is None or k >= len(self._toc):
            return
        entry = self._toc[k]
        page = entry[2] - 1
        y = None
        if len(entry) > 3 and isinstance(entry[3], dict):
            to = entry[3].get("to")
            if to is not None and 0 <= page < self.doc.page_count:
                try:
                    import pymupdf as fitz
                    with self.doc.lock:
                        y = (fitz.Point(to) * self.doc.doc[page].rotation_matrix).y
                except Exception:
                    y = None
        if 0 <= page < self.doc.page_count:
            self.destinationActivated.emit(page, y)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.tree.expandAll()
        else:
            self.tree.collapseAll()

    def _simple_toc(self):
        return [[e[0], e[1], e[2]] for e in self._toc]

    def _add(self):
        name, ok = QInputDialog.getText(self, "Новая закладка", "Название:",
                                        text=f"Страница {self.view.current_page + 1}")
        if not ok or not name.strip():
            return
        toc = self._simple_toc()
        page = self.view.current_page + 1
        pos = len(toc)
        for k, e in enumerate(toc):
            if e[2] > page:
                pos = k
                break
        level = 1
        if pos > 0:
            level = toc[pos - 1][0]
        toc.insert(pos, [level, name.strip(), page])
        self.doc.set_toc(toc)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        m = QMenu(self)
        m.addAction(icons.icon("plus"), "Добавить закладку", self._add)
        if item is not None:
            k = item.data(0, Qt.ItemDataRole.UserRole)
            m.addAction(icons.icon("note"), "Переименовать", lambda: self._rename(k))
            m.addAction(icons.icon("trash"), "Удалить", lambda: self._delete(k))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename(self, k):
        toc = self._simple_toc()
        name, ok = QInputDialog.getText(self, "Переименовать закладку", "Название:", text=toc[k][1])
        if ok and name.strip():
            toc[k][1] = name.strip()
            self.doc.set_toc(toc)

    def _delete(self, k):
        toc = self._simple_toc()
        level = toc[k][0]
        end = k + 1
        while end < len(toc) and toc[end][0] > level:
            end += 1
        del toc[k:end]
        # fix level jumps after removal
        prev = 0
        for e in toc:
            e[0] = min(e[0], prev + 1)
            prev = e[0]
        self.doc.set_toc(toc)


# =================================================================== comments
ANNOT_NAMES = {
    "Highlight": "Выделение", "Underline": "Подчёркивание", "StrikeOut": "Зачёркивание",
    "Squiggly": "Волнистая линия", "Text": "Записка", "FreeText": "Текстовое поле",
    "Ink": "Рисунок", "Square": "Прямоугольник", "Circle": "Эллипс", "Line": "Линия",
    "Polygon": "Многоугольник", "PolyLine": "Ломаная", "Stamp": "Штамп",
    "FileAttachment": "Вложение", "Caret": "Вставка", "Redact": "Скрытие",
}


class CommentsPanel(QWidget):
    destinationActivated = Signal(int, object)

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.doc = view.doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(_title("Комментарии"))
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.itemClicked.connect(self._activate)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)
        self.info = QLabel("")
        self.info.setObjectName("dimLabel")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self._dirty = True
        self._timer = QTimer(self, singleShot=True, interval=300, timeout=self.reload)
        self.doc.pageChanged.connect(self._mark_dirty)
        self.doc.structureChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_):
        self._dirty = True
        if self.isVisible():
            self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:
            self.reload()

    def reload(self):
        self._dirty = False
        self.list.clear()
        count = 0
        for page in range(self.doc.page_count):
            for a in self.doc.annotations(page):
                if a["type"] in ("Link", "Widget", "Popup"):
                    continue
                name = ANNOT_NAMES.get(a["type"], a["type"])
                text = a["content"].strip()
                if not text and a["type"] in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
                    text = self._covered_text(page, a["rect"])
                line = f"{name} · стр. {page + 1}"
                if a["author"]:
                    line += f" · {a['author']}"
                item = QListWidgetItem(line + ("\n" + text[:200] if text else ""))
                item.setData(Qt.ItemDataRole.UserRole, (page, a["xref"], a["rect"].y0))
                item.setIcon(icons.icon(_annot_icon(a["type"])))
                self.list.addItem(item)
                count += 1
        self.info.setText("" if count else "Комментариев нет.\nИспользуйте инструменты на панели «Комментарии».")
        self.info.setVisible(count == 0)

    def _covered_text(self, page, rect):
        words = self.doc.words(page)
        out = [w[4] for w in words
               if w[0] < rect.x1 and w[2] > rect.x0 and (w[1] + w[3]) / 2 > rect.y0 and (w[1] + w[3]) / 2 < rect.y1]
        return " ".join(out)

    def _activate(self, item):
        page, _xref, y = item.data(Qt.ItemDataRole.UserRole)
        self.destinationActivated.emit(page, max(0.0, y - 20))

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        page, xref, _ = item.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction(icons.icon("trash"), "Удалить", lambda: self.doc.delete_annotation(page, xref))
        m.exec(self.list.viewport().mapToGlobal(pos))


def _annot_icon(t):
    return {"Highlight": "highlight", "Underline": "underline", "StrikeOut": "strikeout",
            "Text": "note", "FreeText": "textbox", "Ink": "ink", "Square": "rect",
            "Circle": "ellipse"}.get(t, "comments")


# ===================================================================== search
class SearchPanel(QWidget):
    """Advanced search: query field, options and the list of all results."""

    hitActivated = Signal(int)
    queryEdited = Signal(str, bool, bool)

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.search = view.search
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(_title("Поиск"))
        box = QVBoxLayout()
        box.setContentsMargins(10, 0, 10, 4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Найти в документе…")
        self.edit.setClearButtonEnabled(True)
        self.edit.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        box.addWidget(self.edit)
        self.case = QCheckBox("С учётом регистра")
        self.whole = QCheckBox("Только слова целиком")
        box.addWidget(self.case)
        box.addWidget(self.whole)
        self.status = QLabel("")
        self.status.setObjectName("dimLabel")
        box.addWidget(self.status)
        lay.addLayout(box)
        self.list = QListView()
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setUniformItemSizes(True)
        self.model = _HitModel(self.search)
        self.list.setModel(self.model)
        self.list.setItemDelegate(_HitDelegate(self.list))
        self.list.clicked.connect(lambda idx: self.hitActivated.emit(idx.row()))
        self.list.activated.connect(lambda idx: self.hitActivated.emit(idx.row()))
        lay.addWidget(self.list, 1)
        self._timer = QTimer(self, singleShot=True, interval=180, timeout=self._run)
        self.edit.textChanged.connect(lambda _: self._timer.start())
        self.edit.returnPressed.connect(self._run_and_go)
        self.case.toggled.connect(lambda _: self._run())
        self.whole.toggled.connect(lambda _: self._run())
        self.search.resultsChanged.connect(self._update_status)
        self.search.indexProgress.connect(lambda *_: self._update_status())

    def set_query(self, text, case=None, whole=None):
        self.edit.blockSignals(True)
        self.edit.setText(text)
        self.edit.blockSignals(False)
        if case is not None:
            self.case.blockSignals(True)
            self.case.setChecked(case)
            self.case.blockSignals(False)
        if whole is not None:
            self.whole.blockSignals(True)
            self.whole.setChecked(whole)
            self.whole.blockSignals(False)
        self._update_status()

    def focus(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def _run(self):
        self.search.set_query(self.edit.text(), self.case.isChecked(), self.whole.isChecked())
        self.queryEdited.emit(self.edit.text(), self.case.isChecked(), self.whole.isChecked())

    def _run_and_go(self):
        self._timer.stop()
        self._run()
        if self.search.hits:
            self.hitActivated.emit(self.search.hit_index_near(self.view.current_page))

    def _update_status(self):
        s = self.search
        if not s.query.strip():
            self.status.setText("")
            return
        n = len(s.hits)
        pages = len({h.page for h in s.hits})
        text = f"Найдено: {n} на {pages} стр." if n else "Ничего не найдено"
        if not s.index_complete:
            text += f" (индексация {s._indexed}/{len(s._index)}…)"
        self.status.setText(text)


class _HitModel(QAbstractListModel):
    def __init__(self, search):
        super().__init__()
        self.search = search
        self._n = 0
        search.resultsChanged.connect(self._refresh)

    def _refresh(self):
        self.beginResetModel()
        self._n = len(self.search.hits)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._n

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.UserRole and index.row() < len(self.search.hits):
            return self.search.hits[index.row()]
        return None


class _HitDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, option, index):
        hit = index.data(Qt.ItemDataRole.UserRole)
        if hit is None:
            return
        t = theme.current()
        r = option.rect
        p.save()
        if option.state & QStyle.StateFlag.State_Selected:
            p.fillRect(r, QColor(t.selection))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.fillRect(r, QColor(t.hover))
        f = p.font()
        p.setPen(QColor(t.text_dim))
        p.drawText(r.adjusted(10, 4, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   f"Страница {hit.page + 1}")
        fm = p.fontMetrics()
        y = r.y() + 4 + fm.height() + 2
        x = r.x() + 10
        avail = r.width() - 18
        before = hit.before.lstrip()
        match = hit.match
        after = hit.after
        mw = fm.horizontalAdvance(match)
        bw = min(fm.horizontalAdvance(before), max(0, (avail - mw) // 3))
        before_el = fm.elidedText(before, Qt.TextElideMode.ElideLeft, bw) if bw > 10 else ""
        p.setPen(QColor(t.text))
        p.drawText(x, y + fm.ascent(), before_el)
        x += fm.horizontalAdvance(before_el)
        bold = type(f)(f)
        bold.setBold(True)
        p.setFont(bold)
        bfm = p.fontMetrics()
        mw = bfm.horizontalAdvance(match)
        p.fillRect(x - 1, y, mw + 2, fm.height(), QColor(255, 215, 0, 150))
        p.drawText(x, y + fm.ascent(), match)
        x += mw
        p.setFont(f)
        rest = fm.elidedText(after, Qt.TextElideMode.ElideRight, max(0, r.right() - 8 - x))
        p.drawText(x, y + fm.ascent(), rest)
        p.setPen(QColor(t.bar_border))
        p.drawLine(r.left() + 8, r.bottom(), r.right() - 8, r.bottom())
        p.restore()

    def sizeHint(self, option, index):
        fm = option.fontMetrics
        return QSize(200, fm.height() * 2 + 12)


def _title(text) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("panelTitle")
    return lb
