"""Main application window."""
from __future__ import annotations

import os

import pymupdf as fitz
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIntValidator, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QFileDialog, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QSizePolicy, QTabWidget,
    QToolBar, QToolButton, QWidget,
)

from . import icons, theme
from .dialogs import HomePage, PropertiesDialog, ShortcutsDialog, about_text
from .doctab import DocumentTab
from .document import PasswordRequired, PdfDocument
from .printing import print_document
from .settings import Settings
from .version import APP_NAME
from .viewer import TOOL_NAMES, TOOLS_WITH_COLOR, _qcolor

OPEN_FILTER = ("Все поддерживаемые (*.pdf *.xps *.oxps *.epub *.cbz *.fb2 *.mobi);;"
               "PDF (*.pdf);;Все файлы (*.*)")
SUPPORTED_EXT = (".pdf", ".xps", ".oxps", ".epub", ".cbz", ".fb2", ".mobi")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")

ZOOM_PRESETS = [("По ширине", "width"), ("Страница целиком", "page"), ("Реальный размер", 1.0),
                ("25%", 0.25), ("50%", 0.5), ("75%", 0.75), ("100%", 1.0), ("125%", 1.25),
                ("150%", 1.5), ("200%", 2.0), ("300%", 3.0), ("400%", 4.0), ("800%", 8.0),
                ("1600%", 16.0)]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setAcceptDrops(True)
        self.resize(1320, 880)
        self._icon_actions: list[tuple[object, str]] = []
        self._read_mode = False
        self._presentation = False
        self._pre_present = None
        self.night = self.settings.get("night", False)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.home = HomePage(self.settings)
        self.home.openRequested.connect(self.open_dialog)
        self.home.fileRequested.connect(self.open_file)
        self.tabs.addTab(self.home, icons.icon("home"), "Главная")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.LeftSide, None)
        self.setCentralWidget(self.tabs)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.statusBar().setSizeGripEnabled(True)
        self.index_label = QLabel("")
        self.index_label.setObjectName("dimLabel")
        self.statusBar().addPermanentWidget(self.index_label)

        geo = self.settings.get("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self._update_actions()

    # ================================================================ helpers
    def tab(self) -> DocumentTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def doc_tabs(self) -> list[DocumentTab]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())
                if isinstance(self.tabs.widget(i), DocumentTab)]

    def _act(self, text, slot, shortcut=None, icon=None, checkable=False, tip=None, needs_doc=True):
        a = QAction(text, self)
        if icon:
            a.setIcon(icons.icon(icon))
            self._icon_actions.append((a, icon))
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        if tip or shortcut:
            sc = shortcut[0] if isinstance(shortcut, (list, tuple)) else shortcut
            a.setToolTip(f"{tip or text.replace('…', '')}" + (f"  ({QKeySequence(sc).toString()})" if sc else ""))
        if slot is not None:
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(lambda checked=False: slot())
        a.setProperty("needs_doc", needs_doc)
        self.addAction(a)
        return a

    def _with_tab(self, fn):
        def run():
            t = self.tab()
            if t is not None:
                fn(t)
        return run

    # ================================================================ actions
    def _build_actions(self):
        A = self._act
        W = self._with_tab
        self.a_open = A("Открыть…", self.open_dialog, QKeySequence.StandardKey.Open, "open", needs_doc=False)
        self.a_merge = A("Объединить файлы в PDF…", self.merge_files, None, "merge", needs_doc=False)
        self.a_save = A("Сохранить", self.save, QKeySequence.StandardKey.Save, "save")
        self.a_save_as = A("Сохранить как…", self.save_as, "Ctrl+Shift+S")
        self.a_export_img = A("Страницу как изображение…", W(lambda t: t.export_image(t.view.current_page)),
                              None, "image")
        self.a_export_txt = A("Весь текст в TXT…", self.export_text)
        self.a_print = A("Печать…", W(lambda t: print_document(self, t.doc, t.view.current_page)),
                         QKeySequence.StandardKey.Print, "print")
        self.a_props = A("Свойства документа…", W(lambda t: PropertiesDialog(t.doc, t.view.current_page, self).exec()),
                         "Ctrl+D", "info")
        self.a_close = A("Закрыть вкладку", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W", "close")
        self.a_show_folder = A("Показать в папке", self.show_in_folder)
        self.a_quit = A("Выход", self.close, "Ctrl+Q", needs_doc=False)
        self.a_next_tab = A("Следующая вкладка", lambda: self._cycle_tab(1), "Ctrl+Tab", needs_doc=False)
        self.a_prev_tab = A("Предыдущая вкладка", lambda: self._cycle_tab(-1), "Ctrl+Shift+Tab", needs_doc=False)

        self.a_undo = A("Отменить комментарий", W(lambda t: t.doc.undo()), QKeySequence.StandardKey.Undo, "undo")
        self.a_copy = A("Копировать", W(lambda t: t.view.copy_selection()), QKeySequence.StandardKey.Copy, "copy")
        self.a_select_all = A("Выделить весь текст", W(lambda t: t.view.select_all()), QKeySequence.StandardKey.SelectAll)
        self.a_find = A("Найти…", W(lambda t: t.show_find()), QKeySequence.StandardKey.Find, "search")
        self.a_find_adv = A("Расширенный поиск…", W(lambda t: t.show_panel("search")), "Ctrl+Shift+F", "search")

        self.a_prev = A("Предыдущая страница", W(lambda t: t.view.prev_page()), None, "prev")
        self.a_next = A("Следующая страница", W(lambda t: t.view.next_page()), None, "next")
        self.a_first = A("Первая страница", W(lambda t: t.view.first_page()))
        self.a_last = A("Последняя страница", W(lambda t: t.view.last_page()))
        self.a_goto = A("Перейти к странице…", self.goto_dialog, "Ctrl+Shift+N")
        self.a_back = A("Назад", W(lambda t: t.view.go_back()), "Alt+Left", "back")
        self.a_forward = A("Вперёд", W(lambda t: t.view.go_forward()), "Alt+Right", "forward")

        self.a_zoom_in = A("Увеличить", W(lambda t: t.view.zoom_in()), ["Ctrl+=", "Ctrl++"], "zoom_in")
        self.a_zoom_out = A("Уменьшить", W(lambda t: t.view.zoom_out()), "Ctrl+-", "zoom_out")
        self.a_fit_page = A("Страница целиком", W(lambda t: t.view.set_fit("page")), "Ctrl+0", "fit_page")
        self.a_actual = A("Реальный размер", W(lambda t: t.view.set_zoom(1.0)), "Ctrl+1")
        self.a_fit_width = A("По ширине", W(lambda t: t.view.set_fit("width")), "Ctrl+2", "fit_width")

        self.a_rot_cw = A("Повернуть вид по часовой", W(lambda t: t.doc.rotate_pages(range(t.doc.page_count), 90)),
                          ["Ctrl+Shift+=", "Ctrl+Shift++"], "rotate_cw")
        self.a_rot_ccw = A("Повернуть вид против часовой", W(lambda t: t.doc.rotate_pages(range(t.doc.page_count), -90)),
                           "Ctrl+Shift+-", "rotate_ccw")

        self.layout_group = QActionGroup(self)
        self.a_layouts = {}
        for key, text, ic in (("single", "Одна страница", "page_single"),
                              ("continuous", "Прокрутка (непрерывно)", "page_cont"),
                              ("two", "Две страницы", "page_two"),
                              ("two_continuous", "Две страницы с прокруткой", "page_two_cont")):
            a = A(text, None, None, ic, checkable=True)
            a.triggered.connect(lambda checked=False, k=key: self.set_layout_mode(k))
            self.layout_group.addAction(a)
            self.a_layouts[key] = a
        self.a_layouts["continuous"].setChecked(True)

        self.a_sidebar = A("Боковая панель", self.toggle_sidebar, "F4", "sidebar")
        self.a_night = A("Ночной режим", self.set_night, "Ctrl+Shift+I", "moon", checkable=True, needs_doc=False)
        self.a_night.setChecked(self.night)
        self.a_read = A("Режим чтения", self.toggle_read_mode, "Ctrl+H", "read_mode", needs_doc=True)
        self.a_present = A("Полноэкранный режим", self.toggle_presentation, "Ctrl+L", "fullscreen")
        self.a_autoscroll = A("Автопрокрутка", W(lambda t: t.view.toggle_autoscroll()), "Ctrl+Shift+H", "autoscroll")
        self.theme_group = QActionGroup(self)
        self.a_theme_light = A("Светлая", lambda: self.set_theme("light"), None, checkable=False, needs_doc=False)
        self.a_theme_dark = A("Тёмная", lambda: self.set_theme("dark"), None, checkable=False, needs_doc=False)
        for a in (self.a_theme_light, self.a_theme_dark):
            a.setCheckable(True)
            self.theme_group.addAction(a)
        (self.a_theme_dark if theme.current().name == "dark" else self.a_theme_light).setChecked(True)

        self.tool_group = QActionGroup(self)
        self.a_tools = {}
        tool_defs = [("select", "select", "V"), ("hand", "hand", "H"), ("highlight", "highlight", None),
                     ("underline", "underline", None), ("strikeout", "strikeout", None),
                     ("note", "note", None), ("text", "textbox", None), ("ink", "ink", None),
                     ("rect", "rect", None), ("ellipse", "ellipse", None), ("eraser", "eraser", None)]
        for key, ic, sc in tool_defs:
            a = A(TOOL_NAMES[key], None, sc, ic, checkable=True)
            a.triggered.connect(lambda checked=False, k=key: self.set_tool(k))
            self.tool_group.addAction(a)
            self.a_tools[key] = a
        self.a_tools["select"].setChecked(True)
        self.a_color = A("Цвет инструмента…", self.pick_tool_color, None, "palette")

        self.a_pg_rot_cw = A("Повернуть текущую страницу по часовой",
                             W(lambda t: t.doc.rotate_pages([t.view.current_page], 90)), None, "rotate_cw")
        self.a_pg_rot_ccw = A("Повернуть текущую страницу против часовой",
                              W(lambda t: t.doc.rotate_pages([t.view.current_page], -90)), None, "rotate_ccw")
        self.a_pg_delete = A("Удалить текущую страницу…", W(lambda t: t.delete_pages([t.view.current_page])),
                             None, "trash")
        self.a_pg_extract = A("Извлечь страницы…", self.extract_dialog, None, "extract")
        self.a_pg_insert = A("Вставить страницы из файла…",
                             W(lambda t: t.insert_from_file(t.view.current_page + 1)), None, "insert")
        self.a_pg_blank = A("Вставить пустую страницу", W(lambda t: t.doc.insert_blank_page(t.view.current_page + 1)),
                            None, "plus")
        self.a_pg_move = A("Переместить текущую страницу…", W(lambda t: t.move_page(t.view.current_page)))

        self.a_shortcuts = A("Горячие клавиши", lambda: ShortcutsDialog(self).exec(), "F1", needs_doc=False)
        self.a_about = A("О программе", self.about, None, "info", needs_doc=False)
        self.a_escape = A("Выход из режима", self.escape_modes, None, needs_doc=False)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Файл")
        m.addAction(self.a_open)
        self.recent_menu = m.addMenu(icons.icon("file_pdf"), "Недавние файлы")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addAction(self.a_merge)
        m.addSeparator()
        m.addAction(self.a_save)
        m.addAction(self.a_save_as)
        exp = m.addMenu("Экспорт")
        exp.addAction(self.a_export_img)
        exp.addAction(self.a_export_txt)
        m.addSeparator()
        m.addAction(self.a_print)
        m.addAction(self.a_props)
        m.addAction(self.a_show_folder)
        m.addSeparator()
        m.addAction(self.a_close)
        m.addAction(self.a_quit)

        m = mb.addMenu("&Правка")
        m.addAction(self.a_undo)
        m.addSeparator()
        m.addAction(self.a_copy)
        m.addAction(self.a_select_all)
        m.addSeparator()
        m.addAction(self.a_find)
        m.addAction(self.a_find_adv)

        m = mb.addMenu("&Вид")
        nav = m.addMenu("Навигация по страницам")
        for a in (self.a_first, self.a_prev, self.a_next, self.a_last, None, self.a_goto, None,
                  self.a_back, self.a_forward):
            nav.addSeparator() if a is None else nav.addAction(a)
        z = m.addMenu("Масштаб")
        for a in (self.a_zoom_in, self.a_zoom_out, None, self.a_fit_page, self.a_actual, self.a_fit_width):
            z.addSeparator() if a is None else z.addAction(a)
        r = m.addMenu("Повернуть вид")
        r.addAction(self.a_rot_cw)
        r.addAction(self.a_rot_ccw)
        lm = m.addMenu("Режим отображения страниц")
        for a in self.a_layouts.values():
            lm.addAction(a)
        m.addSeparator()
        m.addAction(self.a_sidebar)
        m.addAction(self.a_read)
        m.addAction(self.a_present)
        m.addAction(self.a_autoscroll)
        m.addSeparator()
        m.addAction(self.a_night)
        tm = m.addMenu(icons.icon("palette"), "Тема оформления")
        tm.addAction(self.a_theme_light)
        tm.addAction(self.a_theme_dark)

        m = mb.addMenu("&Комментарии")
        for k in ("select", "hand", None, "highlight", "underline", "strikeout", None,
                  "note", "text", "ink", "rect", "ellipse", None, "eraser"):
            m.addSeparator() if k is None else m.addAction(self.a_tools[k])
        m.addSeparator()
        m.addAction(self.a_color)
        m.addAction(self.a_undo)

        m = mb.addMenu("&Страницы")
        for a in (self.a_pg_rot_cw, self.a_pg_rot_ccw, None, self.a_pg_insert, self.a_pg_blank,
                  self.a_pg_move, self.a_pg_extract, None, self.a_pg_delete, None, self.a_merge):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu("&Справка")
        m.addAction(self.a_shortcuts)
        m.addAction(self.a_about)

    def _build_toolbar(self):
        tb = QToolBar("Основная панель")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.toolbar = tb
        for a in (self.a_open, self.a_save, self.a_print):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_find)
        tb.addSeparator()
        for k in ("select", "hand"):
            tb.addAction(self.a_tools[k])
        tb.addSeparator()
        for k in ("highlight", "underline", "strikeout", "note", "text", "ink"):
            tb.addAction(self.a_tools[k])
        shapes = QToolButton()
        shapes.setIcon(icons.icon("rect"))
        self._icon_actions.append((shapes, "rect"))
        shapes.setToolTip("Фигуры и ластик")
        sm = QMenu(shapes)
        for k in ("rect", "ellipse", "eraser"):
            sm.addAction(self.a_tools[k])
        shapes.setMenu(sm)
        shapes.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(shapes)
        self.color_btn = QToolButton()
        self.color_btn.setToolTip("Цвет текущего инструмента")
        self.color_btn.clicked.connect(self.pick_tool_color)
        tb.addWidget(self.color_btn)
        self._update_color_button()

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        tb.addAction(self.a_prev)
        tb.addAction(self.a_next)
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(48)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.setValidator(QIntValidator(1, 999999))
        self.page_edit.returnPressed.connect(self._page_entered)
        tb.addWidget(self.page_edit)
        self.page_total = QLabel(" / 0 ")
        self.page_total.setObjectName("dimLabel")
        tb.addWidget(self.page_total)
        tb.addSeparator()
        tb.addAction(self.a_zoom_out)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.setFixedWidth(130)
        for text, val in ZOOM_PRESETS:
            self.zoom_combo.addItem(text, val)
        self.zoom_combo.activated.connect(self._zoom_chosen)
        self.zoom_combo.lineEdit().returnPressed.connect(self._zoom_typed)
        tb.addWidget(self.zoom_combo)
        tb.addAction(self.a_zoom_in)
        tb.addAction(self.a_fit_width)
        tb.addAction(self.a_fit_page)
        tb.addSeparator()
        layout_btn = QToolButton()
        layout_btn.setIcon(icons.icon("page_cont"))
        self._icon_actions.append((layout_btn, "page_cont"))
        layout_btn.setToolTip("Режим отображения страниц")
        lm = QMenu(layout_btn)
        for a in self.a_layouts.values():
            lm.addAction(a)
        lm.addSeparator()
        lm.addAction(self.a_rot_cw)
        lm.addAction(self.a_rot_ccw)
        layout_btn.setMenu(lm)
        layout_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(layout_btn)
        tb.addAction(self.a_night)
        tb.addAction(self.a_read)
        tb.addAction(self.a_present)

    # ============================================================ open/save
    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Открыть", self.settings.last_dir(), OPEN_FILTER)
        for p in paths:
            self.open_file(p)

    def open_file(self, path: str):
        path = os.path.abspath(path)
        for t in self.doc_tabs():
            if t.doc.path and os.path.normcase(t.doc.path) == os.path.normcase(path):
                self.tabs.setCurrentWidget(t)
                return t
        if not os.path.exists(path):
            QMessageBox.warning(self, APP_NAME, f"Файл не найден:\n{path}")
            self.settings.remove_recent(path)
            self.home.refresh()
            return None
        if path.lower().endswith(IMAGE_EXT):
            return self._open_images([path])
        password = None
        for attempt in range(4):
            try:
                doc = PdfDocument.open(path, password)
                break
            except PasswordRequired:
                prompt = "Документ защищён паролем. Введите пароль:" if attempt == 0 else "Неверный пароль. Повторите:"
                password, ok = QInputDialog.getText(self, "Пароль", prompt, QLineEdit.EchoMode.Password)
                if not ok:
                    return None
            except Exception as exc:
                QMessageBox.critical(self, APP_NAME, f"Не удалось открыть файл:\n{path}\n\n{exc}")
                return None
        else:
            return None
        self.settings.add_recent(path)
        self.settings.set_last_dir(path)
        self.home.refresh()
        return self._add_tab(doc, restore=path)

    def _add_tab(self, doc: PdfDocument, restore: str | None = None):
        t = DocumentTab(doc, self.settings)
        t.view.set_invert(self.night)
        t.view.currentPageChanged.connect(lambda _p, t=t: self._sync_page(t))
        t.view.zoomChanged.connect(lambda _z, t=t: self._sync_zoom(t))
        t.view.toolChanged.connect(lambda tool, t=t: self._sync_tool(t))
        t.view.historyChanged.connect(self._update_actions)
        t.view.escapePressed.connect(self.escape_modes)
        t.view.layoutModeChanged.connect(lambda _m, t=t: self._sync_layout(t))
        t.statusMessage.connect(lambda msg: self.statusBar().showMessage(msg, 4000))
        t.titleChanged.connect(lambda t=t: self._update_tab_title(t))
        doc.structureChanged.connect(lambda t=t: self._sync_page(t))
        t.search.indexProgress.connect(lambda done, total, t=t: self._index_progress(t, done, total))
        layout_mode = self.settings.get("layout_mode", "continuous")
        if layout_mode in self.a_layouts:
            t.view.set_layout_mode(layout_mode)
        if self.settings.get("sidebar", True) and not self._read_mode:
            t.show_panel("thumbs")
        idx = self.tabs.addTab(t, icons.icon("file_pdf", "#d7373f"), doc.title)
        self.tabs.setTabToolTip(idx, doc.path or doc.title)
        self.tabs.setCurrentIndex(idx)
        st = self.settings.position(restore) if restore else None

        def apply_state():
            if st:
                zm = st.get("zoom")
                if zm in ("width", "page"):
                    t.view.set_fit(zm)
                elif isinstance(zm, (int, float)):
                    t.view.set_zoom(float(zm))
                t.view.restore_scroll_state(st)
            else:
                t.view.set_fit("width")
                t.view.go_to_page(0, add_history=False)
            self._sync_page(t)
            self._sync_zoom(t)
        QTimer.singleShot(0, apply_state)
        t.view.setFocus()
        self._update_actions()
        return t

    def _open_images(self, paths):
        out = fitz.open()
        for p in paths:
            with fitz.open(p) as img:
                out.insert_pdf(fitz.open("pdf", img.convert_to_pdf()))
        name = os.path.splitext(os.path.basename(paths[0]))[0] + ".pdf"
        doc = PdfDocument.from_bytes(out.tobytes(), name)
        out.close()
        doc.set_modified(True)
        return self._add_tab(doc)

    def merge_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Объединить файлы в PDF", self.settings.last_dir(),
            "Документы и изображения (*.pdf *.xps *.epub *.cbz *.png *.jpg *.jpeg *.bmp *.tif *.tiff);;Все файлы (*.*)")
        if not paths:
            return
        out = fitz.open()
        try:
            for p in paths:
                src = fitz.open(p)
                if not src.is_pdf:
                    data = src.convert_to_pdf()
                    src.close()
                    src = fitz.open("pdf", data)
                elif src.needs_pass:
                    QMessageBox.warning(self, APP_NAME, f"Пропущен защищённый файл:\n{p}")
                    continue
                out.insert_pdf(src)
                src.close()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Ошибка при объединении:\n{exc}")
            return
        if not len(out):
            return
        doc = PdfDocument.from_bytes(out.tobytes(garbage=3, deflate=True), "Объединённый.pdf")
        out.close()
        doc.set_modified(True)
        self._add_tab(doc)

    def save(self, tab: DocumentTab | None = None) -> bool:
        t = tab or self.tab()
        if t is None:
            return False
        if not t.doc.path:
            return self.save_as(t)
        return self._do_save(t, None)

    def save_as(self, tab: DocumentTab | None = None) -> bool:
        t = tab or self.tab()
        if t is None:
            return False
        start = t.doc.path or os.path.join(self.settings.last_dir(), t.doc.title)
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить как", start, "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        ok = self._do_save(t, path)
        if ok:
            self.settings.add_recent(path)
            self.home.refresh()
        return ok

    def _do_save(self, t: DocumentTab, path):
        state = t.view.scroll_state()
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            t.doc.save(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, f"Не удалось сохранить файл:\n{exc}\n\n"
                                                 "Возможно, файл открыт в другой программе или доступен только для чтения.")
            return False
        QApplication.restoreOverrideCursor()
        t.view.restore_scroll_state(state)
        self._update_tab_title(t)
        self.statusBar().showMessage(f"Сохранено: {t.doc.path}", 4000)
        return True

    def export_text(self):
        t = self.tab()
        if t is None:
            return
        base = os.path.splitext(t.doc.title)[0] + ".txt"
        start = os.path.join(os.path.dirname(t.doc.path) if t.doc.path else self.settings.last_dir(), base)
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт текста", start, "Текст (*.txt)")
        if path:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                t.doc.export_text(path)
            finally:
                QApplication.restoreOverrideCursor()
            self.statusBar().showMessage(f"Текст сохранён: {path}", 4000)

    def show_in_folder(self):
        t = self.tab()
        if t and t.doc.path:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(t.doc.path)])

    def extract_dialog(self):
        t = self.tab()
        if t is None:
            return
        n = t.doc.page_count
        text, ok = QInputDialog.getText(self, "Извлечь страницы",
                                        f"Страницы (например: 1-3, 5, 8-10), всего {n}:",
                                        text=str(t.view.current_page + 1))
        if not ok:
            return
        pages = parse_ranges(text, n)
        if not pages:
            QMessageBox.warning(self, APP_NAME, "Неверный диапазон страниц.")
            return
        t.extract_pages(pages)

    # ================================================================== tabs
    def close_tab(self, index) -> bool:
        w = self.tabs.widget(index)
        if not isinstance(w, DocumentTab):
            return True
        if w.doc.modified:
            self.tabs.setCurrentIndex(index)
            r = QMessageBox.question(
                self, APP_NAME, f"Сохранить изменения в «{w.doc.title}» перед закрытием?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return False
            if r == QMessageBox.StandardButton.Save and not self.save(w):
                return False
        self._remember(w)
        self.tabs.removeTab(index)
        w.shutdown()
        w.deleteLater()
        self._update_actions()
        return True

    def _remember(self, t: DocumentTab):
        if not t.doc.path:
            return
        st = t.view.scroll_state()
        st["zoom"] = t.view.fit_mode or round(t.view.zoom, 4)
        self.settings.save_position(t.doc.path, st)

    def _cycle_tab(self, d):
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % n)

    def _on_tab_changed(self, _i):
        t = self.tab()
        if t is not None:
            if self._read_mode:
                t.hide_panel()
            self._sync_page(t)
            self._sync_zoom(t)
            self._sync_tool(t)
            self._sync_layout(t)
            t.view.set_invert(self.night)
        self._update_actions()

    def _update_tab_title(self, t: DocumentTab):
        i = self.tabs.indexOf(t)
        if i >= 0:
            self.tabs.setTabText(i, ("● " if t.doc.modified else "") + t.doc.title)
            self.tabs.setTabToolTip(i, t.doc.path or t.doc.title)
        if t is self.tab():
            self._update_window_title()

    def _update_window_title(self):
        t = self.tab()
        if t is None:
            self.setWindowTitle(APP_NAME)
        else:
            self.setWindowTitle(f"{'*' if t.doc.modified else ''}{t.doc.title} — {APP_NAME}")

    def _update_actions(self):
        t = self.tab()
        has = t is not None
        for a in self.actions():
            if a.property("needs_doc"):
                a.setEnabled(has)
        self.page_edit.setEnabled(has)
        self.zoom_combo.setEnabled(has)
        self.color_btn.setEnabled(has)
        if has:
            self.a_back.setEnabled(t.view.can_go_back())
            self.a_forward.setEnabled(t.view.can_go_forward())
            self.a_show_folder.setEnabled(bool(t.doc.path))
        else:
            self.page_edit.setText("")
            self.page_total.setText(" / 0 ")
            self.zoom_combo.setEditText("")
        self._update_window_title()

    # ========================================================== sync widgets
    def _sync_page(self, t):
        if t is not self.tab():
            return
        if not self.page_edit.hasFocus():
            self.page_edit.setText(str(t.view.current_page + 1))
        self.page_total.setText(f" / {t.doc.page_count} ")
        self.a_prev.setEnabled(t.view.current_page > 0)
        self.a_next.setEnabled(t.view.current_page < t.doc.page_count - 1)

    def _sync_zoom(self, t):
        if t is not self.tab():
            return
        if not self.zoom_combo.lineEdit().hasFocus():
            self.zoom_combo.setEditText(f"{t.view.zoom * 100:.0f}%")

    def _sync_tool(self, t):
        if t is not self.tab():
            return
        a = self.a_tools.get(t.view.tool)
        if a:
            a.setChecked(True)
        self._update_color_button()

    def _sync_layout(self, t):
        a = self.a_layouts.get(t.view.layout_mode)
        if a:
            a.setChecked(True)

    def _index_progress(self, t, done, total):
        if t is not self.tab():
            return
        if total and done < total:
            self.index_label.setText(f"Индексация текста для поиска: {done * 100 // total}%  ")
        else:
            self.index_label.setText("")

    def _page_entered(self):
        t = self.tab()
        if t and self.page_edit.text():
            t.view.go_to_page(int(self.page_edit.text()) - 1)
            t.view.setFocus()

    def _zoom_chosen(self, index):
        t = self.tab()
        if t is None:
            return
        val = self.zoom_combo.itemData(index)
        if val in ("width", "page"):
            t.view.set_fit(val)
        elif val is not None:
            t.view.set_zoom(float(val))
        t.view.setFocus()

    def _zoom_typed(self):
        t = self.tab()
        if t is None:
            return
        text = self.zoom_combo.currentText().replace("%", "").replace(",", ".").strip()
        try:
            t.view.set_zoom(float(text) / 100)
        except ValueError:
            pass
        t.view.setFocus()
        self._sync_zoom(t)

    def goto_dialog(self):
        t = self.tab()
        if t is None:
            return
        n = t.doc.page_count
        p, ok = QInputDialog.getInt(self, "Перейти к странице", f"Номер страницы (1–{n}):",
                                    t.view.current_page + 1, 1, n)
        if ok:
            t.view.go_to_page(p - 1)

    # ================================================================ tools
    def set_tool(self, tool):
        for t in self.doc_tabs():
            t.view.set_tool(tool)
        self._update_color_button()

    def _current_color_tool(self):
        t = self.tab()
        tool = t.view.tool if t else "highlight"
        return tool if tool in TOOLS_WITH_COLOR else "highlight"

    def _update_color_button(self):
        if not hasattr(self, "color_btn"):
            return
        t = self.tab()
        tool = self._current_color_tool()
        rgb = t.view.tool_colors[tool] if t else (1, 0.85, 0)
        self.color_btn.setIcon(icons.color_swatch(_qcolor(rgb)))
        self.color_btn.setToolTip(f"Цвет: {TOOL_NAMES[tool]}")

    def pick_tool_color(self):
        t = self.tab()
        if t is None:
            return
        tool = self._current_color_tool()
        c = QColorDialog.getColor(_qcolor(t.view.tool_colors[tool]), self, f"Цвет — {TOOL_NAMES[tool]}")
        if c.isValid():
            rgb = (c.redF(), c.greenF(), c.blueF())
            for tab in self.doc_tabs():
                tab.view.set_tool_color(tool, rgb)
            self._update_color_button()

    # ================================================================= view
    def set_layout_mode(self, mode):
        t = self.tab()
        if t:
            t.view.set_layout_mode(mode)
        self.settings.set("layout_mode", mode)

    def toggle_sidebar(self):
        t = self.tab()
        if t is None:
            return
        if t.panel_visible():
            t.hide_panel()
            self.settings.set("sidebar", False)
        else:
            t.show_panel(t.current_panel or "thumbs")
            self.settings.set("sidebar", True)

    def set_night(self, on):
        self.night = bool(on)
        self.settings.set("night", self.night)
        for t in self.doc_tabs():
            t.view.set_invert(self.night)
            t.thumbs.list.viewport().update()

    def set_theme(self, name):
        theme.apply(QApplication.instance(), name)
        self.settings.set("theme", name)
        for obj, ic in self._icon_actions:
            obj.setIcon(icons.icon(ic))
        for t in self.doc_tabs():
            for key, ic, _tip in DocumentTab.PANELS:
                t.rail_buttons[key].setIcon(icons.icon(ic))
            t.view.viewport().update()
            t.comments.reload()
        self._update_color_button()

    def toggle_read_mode(self):
        self._set_read_mode(not self._read_mode)

    def _set_read_mode(self, on, quiet=False):
        self._read_mode = on
        self.toolbar.setVisible(not on)
        self.menuBar().setVisible(not on)
        self.statusBar().setVisible(not on)
        self.tabs.tabBar().setVisible(not on)
        for t in self.doc_tabs():
            rail = t.layout().itemAt(0).widget()
            rail.setVisible(not on)
            if on:
                t.hide_panel()
            elif self.settings.get("sidebar", True):
                t.show_panel(t.current_panel or "thumbs")
        if on and not quiet:
            self._toast("Режим чтения — Esc или Ctrl+H для выхода")

    def toggle_presentation(self):
        t = self.tab()
        if t is None:
            return
        if self._presentation:
            self._exit_presentation()
            return
        self._presentation = True
        self._pre_present = (self.isMaximized(), t.view.layout_mode, t.view.fit_mode, t.view.zoom, self._read_mode)
        self._set_read_mode(True, quiet=True)
        self.showFullScreen()
        t.view.layout_mode = "single"
        t.view._single_page = t.view.current_page
        t.view.fit_mode = "page"
        t.view.set_presentation(True)
        self._toast("Полноэкранный режим — ←/→ листать, Esc для выхода")

    def _exit_presentation(self):
        t = self.tab()
        self._presentation = False
        was_max, layout, fit, zoom, read = self._pre_present
        if t is not None:
            t.view.presentation = False
            t.view.layout_mode = layout
            t.view.fit_mode = fit
            t.view.zoom = zoom
            page = t.view.current_page
            t.view._relayout(keep_anchor=False)
            t.view.go_to_page(page, add_history=False)
        self._set_read_mode(read, quiet=True)
        if was_max:
            self.showMaximized()
        else:
            self.showNormal()

    def escape_modes(self):
        if self._presentation:
            self._exit_presentation()
        elif self._read_mode:
            self._set_read_mode(False)

    def _toast(self, text):
        lbl = QLabel(text, self)
        lbl.setStyleSheet("background: rgba(30,30,30,215); color: white; padding: 10px 18px;"
                          "border-radius: 8px; font-size: 10pt;")
        lbl.adjustSize()
        lbl.move((self.width() - lbl.width()) // 2, 40)
        lbl.show()
        lbl.raise_()
        QTimer.singleShot(2200, lbl.deleteLater)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and (self._presentation or self._read_mode):
            self.escape_modes()
            return
        super().keyPressEvent(e)

    def about(self):
        QMessageBox.about(self, f"О программе {APP_NAME}", about_text())

    def _fill_recent(self):
        m = self.recent_menu
        m.clear()
        files = self.settings.recent_files()
        if not files:
            a = m.addAction("(пусто)")
            a.setEnabled(False)
            return
        for p in files:
            m.addAction(os.path.basename(p), lambda p=p: self.open_file(p)).setToolTip(p)
        m.addSeparator()
        m.addAction("Очистить список", lambda: (self.settings.clear_recent(), self.home.refresh()))

    # ======================================================== drag and drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(SUPPORTED_EXT + IMAGE_EXT):
                    e.acceptProposedAction()
                    return

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                p = u.toLocalFile()
                if p.lower().endswith(SUPPORTED_EXT + IMAGE_EXT):
                    self.open_file(p)

    # ================================================================ close
    def closeEvent(self, e):
        for t in self.doc_tabs():
            if t.doc.modified:
                idx = self.tabs.indexOf(t)
                if not self.close_tab(idx):
                    e.ignore()
                    return
        for t in self.doc_tabs():
            self._remember(t)
            t.shutdown()
        if not self._presentation:
            self.settings.set("maximized", self.isMaximized())
            self.settings.set("geometry", self.saveGeometry())
        e.accept()


def parse_ranges(text: str, n: int) -> list[int]:
    pages: set[int] = set()
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a = int(a) if a.strip() else 1
                b = int(b) if b.strip() else n
            except ValueError:
                return []
            if a > b:
                a, b = b, a
            pages.update(range(max(1, a) - 1, min(n, b)))
        else:
            try:
                k = int(part)
            except ValueError:
                return []
            if 1 <= k <= n:
                pages.add(k - 1)
    return sorted(pages)
