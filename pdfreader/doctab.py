"""One open document: side rail, side panels, page view and the find bar."""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMenu, QMessageBox, QSplitter, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from . import icons
from .panels import BookmarkPanel, CommentsPanel, SearchPanel, ThumbnailPanel
from .renderer import RenderManager
from .search import SearchEngine
from .viewer import PdfView


class FindBar(QWidget):
    """Compact Acrobat-style find box floating over the top-right of the view."""

    closed = Signal()

    def __init__(self, tab, parent):
        super().__init__(parent)
        self.tab = tab
        self.setObjectName("findBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 5, 5)
        lay.setSpacing(2)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Найти текст")
        self.edit.setMinimumWidth(220)
        self.edit.setClearButtonEnabled(True)
        self.edit.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        lay.addWidget(self.edit)
        self.count = QLabel("")
        self.count.setObjectName("dimLabel")
        self.count.setMinimumWidth(70)
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.count)
        self.btn_prev = self._btn("prev", "Предыдущее (Shift+Enter)", lambda: tab.find_step(-1))
        self.btn_next = self._btn("next", "Следующее (Enter)", lambda: tab.find_step(1))
        opt = self._btn("settings", "Параметры поиска", None)
        m = QMenu(opt)
        self.act_case = m.addAction("С учётом регистра")
        self.act_case.setCheckable(True)
        self.act_whole = m.addAction("Только слова целиком")
        self.act_whole.setCheckable(True)
        m.addSeparator()
        m.addAction(icons.icon("search"), "Расширенный поиск (список результатов)…",
                    lambda: tab.show_panel("search"))
        opt.setMenu(m)
        opt.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.act_case.toggled.connect(lambda _: self._run())
        self.act_whole.toggled.connect(lambda _: self._run())
        self._btn("close", "Закрыть (Esc)", self.hide_bar)
        self._timer = QTimer(self, singleShot=True, interval=200, timeout=self._run)
        self.edit.textChanged.connect(lambda _: self._timer.start())
        self.edit.installEventFilter(self)
        tab.search.resultsChanged.connect(self.update_count)
        tab.search.indexProgress.connect(lambda *_: self.update_count())
        self.hide()

    def _btn(self, name, tip, slot):
        b = QToolButton(self)
        b.setIcon(icons.icon(name))
        b.setToolTip(tip)
        if slot:
            b.clicked.connect(slot)
        self.layout().addWidget(b)
        return b

    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.Type.KeyPress:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._timer.isActive():
                    self._timer.stop()
                    self._run()
                back = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.tab.find_step(-1 if back else 1)
                return True
            if e.key() == Qt.Key.Key_Escape:
                self.hide_bar()
                return True
        return super().eventFilter(obj, e)

    def _run(self):
        self.tab.run_search(self.edit.text(), self.act_case.isChecked(), self.act_whole.isChecked())

    def show_bar(self, text=None):
        if text:
            self.edit.setText(text)
        self.show()
        self.raise_()
        self.reposition()
        self.edit.setFocus()
        self.edit.selectAll()

    def hide_bar(self):
        self.hide()
        self.tab.view.setFocus()
        self.closed.emit()

    def reposition(self):
        p = self.parentWidget()
        self.adjustSize()
        self.move(p.width() - self.width() - 24, 10)

    def update_count(self):
        s = self.tab.search
        if not s.query.strip():
            self.count.setText("")
            return
        n = len(s.hits)
        cur = self.tab.view.current_hit
        if n == 0:
            self.count.setText("0 из 0" if s.index_complete else "поиск…")
        else:
            more = "" if s.index_complete else "+"
            self.count.setText(f"{cur + 1 if cur >= 0 else '–'} из {n}{more}")


class _ViewHost(QWidget):
    """Container that keeps floating overlays positioned over the view."""

    def __init__(self, view):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view)
        self.find_bar: FindBar | None = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.find_bar is not None and self.find_bar.isVisible():
            self.find_bar.reposition()


class DocumentTab(QWidget):
    titleChanged = Signal()
    statusMessage = Signal(str)

    PANELS = [
        ("thumbs", "thumbs", "Миниатюры страниц"),
        ("bookmarks", "bookmark", "Закладки"),
        ("comments", "comments", "Комментарии"),
        ("search", "search", "Поиск"),
    ]

    def __init__(self, document, settings, parent=None):
        super().__init__(parent)
        self.doc = document
        self.settings = settings
        self.renderer = RenderManager(document)
        self.search = SearchEngine(document)
        self.view = PdfView(document, self.renderer, self.search)
        self.view.statusMessage.connect(self.statusMessage)
        self._await_first_hit = False
        self.search.resultsChanged.connect(self._on_results)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # left icon rail
        rail = QWidget()
        rail.setObjectName("sideRail")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(0, 6, 0, 6)
        rl.setSpacing(2)
        self.rail_group = QButtonGroup(self)
        self.rail_group.setExclusive(False)
        self.rail_buttons = {}
        for key, ic, tip in self.PANELS:
            b = QToolButton()
            b.setObjectName("railButton")
            b.setIcon(icons.icon(ic))
            b.setIconSize(b.iconSize() * 1.15)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.clicked.connect(lambda checked, k=key: self.toggle_panel(k))
            rl.addWidget(b)
            self.rail_buttons[key] = b
        rl.addStretch(1)
        root.addWidget(rail)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.panel_stack = QStackedWidget()
        self.panel_stack.setObjectName("sidePanel")
        self.panel_stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.panel_stack.setMinimumWidth(170)
        self.thumbs = ThumbnailPanel(self.view)
        self.thumbs.pageActivated.connect(lambda p: self.view.go_to_page(p))
        self.thumbs.page_actions = self.page_actions
        self.bookmarks = BookmarkPanel(self.view)
        self.bookmarks.destinationActivated.connect(self._go_dest)
        self.comments = CommentsPanel(self.view)
        self.comments.destinationActivated.connect(self._go_dest)
        self.search_panel = SearchPanel(self.view)
        self.search_panel.hitActivated.connect(self.go_to_hit)
        self.search_panel.queryEdited.connect(self._sync_find_bar)
        self.panels = {"thumbs": self.thumbs, "bookmarks": self.bookmarks,
                       "comments": self.comments, "search": self.search_panel}
        for w in self.panels.values():
            self.panel_stack.addWidget(w)
        self.splitter.addWidget(self.panel_stack)
        self.host = _ViewHost(self.view)
        self.splitter.addWidget(self.host)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([210, 1000])
        root.addWidget(self.splitter, 1)
        self.find_bar = FindBar(self, self.host)
        self.host.find_bar = self.find_bar
        self.view.currentPageChanged.connect(lambda _: self.thumbs.list.viewport().update())

        self.panel_stack.hide()
        self.current_panel = None
        self.doc.modifiedChanged.connect(lambda _: self.titleChanged.emit())
        self.view.escapePressed.connect(self._on_escape)
        QShortcut(QKeySequence("F3"), self, lambda: self.find_step(1))
        QShortcut(QKeySequence("Shift+F3"), self, lambda: self.find_step(-1))

        # start building the search index in the background right away
        QTimer.singleShot(400, self.search.start_indexing)

    # ----------------------------------------------------------------- panels
    def toggle_panel(self, key):
        if self.current_panel == key and self.panel_stack.isVisible():
            self.hide_panel()
        else:
            self.show_panel(key)

    def show_panel(self, key):
        self.current_panel = key
        self.panel_stack.setCurrentWidget(self.panels[key])
        self.panel_stack.show()
        for k, b in self.rail_buttons.items():
            b.setChecked(k == key)
        if key == "search":
            fb = self.find_bar
            self.search_panel.set_query(fb.edit.text(), fb.act_case.isChecked(), fb.act_whole.isChecked())
            self.search_panel.focus()

    def hide_panel(self):
        self.panel_stack.hide()
        for b in self.rail_buttons.values():
            b.setChecked(False)

    def panel_visible(self):
        return self.panel_stack.isVisible()

    def _go_dest(self, page, y):
        self.view.go_to_page(page, y_pt=y)
        self.view.setFocus()

    def _on_escape(self):
        if self.find_bar.isVisible():
            self.find_bar.hide_bar()
        elif self.search.query:
            self.search.clear()
            self.view.current_hit = -1
            self.view.viewport().update()

    # ----------------------------------------------------------------- search
    def show_find(self):
        sel = self.view.selected_text().strip()
        self.find_bar.show_bar(sel if sel and "\n" not in sel and len(sel) < 80 else None)

    def run_search(self, text, case, whole):
        self.view.current_hit = -1
        self.search.set_query(text, case, whole)
        if self.search_panel.isVisible():
            self.search_panel.set_query(text, case, whole)
        # jump to the first hit at or after the current page
        self._await_first_hit = not self.search.hits
        if self.search.hits:
            self.go_to_hit(self.search.hit_index_near(self.view.current_page))
        self.find_bar.update_count()

    def _on_results(self):
        if self._await_first_hit and self.search.hits:
            self._await_first_hit = False
            self.go_to_hit(self.search.hit_index_near(self.view.current_page))

    def _sync_find_bar(self, text, case, whole):
        fb = self.find_bar
        for w, v in ((fb.edit, None), (fb.act_case, case), (fb.act_whole, whole)):
            w.blockSignals(True)
        fb.edit.setText(text)
        fb.act_case.setChecked(case)
        fb.act_whole.setChecked(whole)
        for w in (fb.edit, fb.act_case, fb.act_whole):
            w.blockSignals(False)
        self.view.current_hit = -1
        fb.update_count()

    def find_step(self, direction):
        if not self.find_bar.isVisible() and not self.search.query:
            self.show_find()
            return
        hits = self.search.hits
        if not hits:
            return
        cur = self.view.current_hit
        if cur < 0:
            idx = self.search.hit_index_near(self.view.current_page)
            if direction < 0:
                idx = (idx - 1) % len(hits)
        else:
            idx = (cur + direction) % len(hits)
        self.go_to_hit(idx)

    def go_to_hit(self, idx):
        if not (0 <= idx < len(self.search.hits)):
            return
        self.view.show_hit(idx)
        self.find_bar.update_count()
        if self.search_panel.isVisible():
            self.search_panel.list.setCurrentIndex(self.search_panel.model.index(idx))

    # ------------------------------------------------------------------ pages
    def page_actions(self, menu: QMenu, pages: list[int]):
        label = f"страницу {pages[0] + 1}" if len(pages) == 1 else f"{len(pages)} стр."
        menu.addAction(icons.icon("rotate_cw"), f"Повернуть {label} по часовой",
                       lambda: self.doc.rotate_pages(pages, 90))
        menu.addAction(icons.icon("rotate_ccw"), f"Повернуть {label} против часовой",
                       lambda: self.doc.rotate_pages(pages, -90))
        menu.addSeparator()
        menu.addAction(icons.icon("extract"), f"Извлечь {label} в новый PDF…",
                       lambda: self.extract_pages(pages))
        menu.addAction(icons.icon("image"), "Сохранить страницу как изображение…",
                       lambda: self.export_image(pages[0]))
        menu.addSeparator()
        menu.addAction(icons.icon("insert"), "Вставить страницы из файла…",
                       lambda: self.insert_from_file(pages[-1] + 1))
        menu.addAction(icons.icon("plus"), "Вставить пустую страницу после",
                       lambda: self.doc.insert_blank_page(pages[-1] + 1))
        if len(pages) == 1:
            menu.addAction(icons.icon("prev"), "Переместить страницу…", lambda: self.move_page(pages[0]))
        menu.addSeparator()
        act = menu.addAction(icons.icon("trash"), f"Удалить {label}", lambda: self.delete_pages(pages))
        act.setEnabled(len(pages) < self.doc.page_count)

    def delete_pages(self, pages):
        if len(pages) >= self.doc.page_count:
            return
        txt = ", ".join(str(p + 1) for p in pages[:12]) + ("…" if len(pages) > 12 else "")
        if QMessageBox.question(self, "Удалить страницы", f"Удалить страницы: {txt}?") \
                == QMessageBox.StandardButton.Yes:
            self.doc.delete_pages(pages)

    def move_page(self, page):
        n = self.doc.page_count
        target, ok = QInputDialog.getInt(self, "Переместить страницу",
                                         f"Новая позиция страницы {page + 1} (1–{n}):", page + 1, 1, n)
        if ok and target - 1 != page:
            self.doc.move_page(page, target - 1)
            self.view.go_to_page(target - 1, add_history=False)

    def extract_pages(self, pages):
        base = os.path.splitext(self.doc.title)[0]
        suffix = f"стр{pages[0] + 1}" if len(pages) == 1 else f"стр{pages[0] + 1}-{pages[-1] + 1}"
        start = os.path.join(self._dir(), f"{base}_{suffix}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Извлечь страницы", start, "PDF (*.pdf)")
        if path:
            self.doc.extract_pages(pages, path)
            self.statusMessage.emit(f"Сохранено: {path}")

    def export_image(self, page):
        base = os.path.splitext(self.doc.title)[0]
        start = os.path.join(self._dir(), f"{base}_стр{page + 1}.png")
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить страницу как изображение", start,
                                              "PNG (*.png);;JPEG (*.jpg)")
        if not path:
            return
        dpi, ok = QInputDialog.getInt(self, "Разрешение", "Разрешение (DPI):", 150, 36, 600, 25)
        if ok:
            self.doc.render_page_png(page, path, dpi)
            self.statusMessage.emit(f"Сохранено: {path}")

    def insert_from_file(self, at):
        path, _ = QFileDialog.getOpenFileName(self, "Вставить страницы из файла", self._dir(),
                                              "Документы (*.pdf *.xps *.epub *.cbz *.png *.jpg *.jpeg)")
        if path:
            try:
                self.doc.insert_pdf(path, at)
                self.view.go_to_page(at, add_history=False)
            except Exception as exc:
                QMessageBox.warning(self, "Ошибка", f"Не удалось вставить страницы:\n{exc}")

    def _dir(self):
        if self.doc.path:
            return os.path.dirname(self.doc.path)
        return self.settings.last_dir()

    # -------------------------------------------------------------- lifecycle
    def shutdown(self):
        self.renderer.stop()
        self.doc.close()
