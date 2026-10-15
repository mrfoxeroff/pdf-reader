"""Dialogs and the start (home) page."""
from __future__ import annotations

import datetime as _dt
import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QAbstractItemView, QHeaderView,
)

from . import icons
from .version import APP_NAME, VERSION


def _pdf_date(s: str) -> str:
    """Format a PDF date string like D:20240131120000+03'00'."""
    if not s:
        return "—"
    raw = s[2:] if s.startswith("D:") else s
    try:
        dt = _dt.datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return s


def _size(n: int) -> str:
    for unit in ("байт", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "байт" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


class PropertiesDialog(QDialog):
    def __init__(self, document, current_page, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Свойства документа")
        self.setMinimumWidth(520)
        md = document.metadata()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(7)

        def row(label, value):
            v = QLabel(value or "—")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setWordWrap(True)
            form.addRow(f"<b>{label}:</b>", v)

        path = document.path or "(не сохранён)"
        row("Файл", path)
        if document.path and os.path.exists(document.path):
            row("Размер файла", _size(os.path.getsize(document.path)))
        row("Название", md.get("title"))
        row("Автор", md.get("author"))
        row("Тема", md.get("subject"))
        row("Ключевые слова", md.get("keywords"))
        row("Создан", _pdf_date(md.get("creationDate", "")))
        row("Изменён", _pdf_date(md.get("modDate", "")))
        row("Приложение", md.get("creator"))
        row("PDF-генератор", md.get("producer"))
        row("Версия PDF", md.get("format"))
        row("Страниц", str(md.get("_pages")))
        w, h = document.page_sizes[current_page] if document.page_count else (0, 0)
        row("Размер страницы", f"{w / 72 * 25.4:.0f} × {h / 72 * 25.4:.0f} мм  ({w:.0f} × {h:.0f} pt)")
        row("Защита", md.get("encryption") or ("Есть" if md.get("_encrypted") else "Нет"))
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


SHORTCUTS = [
    ("Ctrl+O", "Открыть файл"), ("Ctrl+S", "Сохранить"), ("Ctrl+Shift+S", "Сохранить как"),
    ("Ctrl+P", "Печать"), ("Ctrl+W", "Закрыть вкладку"), ("Ctrl+Tab", "Следующая вкладка"),
    ("Ctrl+D", "Свойства документа"), ("Ctrl+F", "Найти"), ("Enter / F3", "Следующее совпадение"),
    ("Shift+Enter / Shift+F3", "Предыдущее совпадение"), ("Ctrl+Shift+F", "Расширенный поиск"),
    ("Ctrl+C", "Копировать выделенный текст"), ("Ctrl+A", "Выделить весь текст"),
    ("Ctrl+Z", "Отменить последний комментарий"),
    ("Ctrl + колесо / Ctrl+= / Ctrl+-", "Масштаб"), ("Ctrl+0", "Страница целиком"),
    ("Ctrl+1", "Реальный размер"), ("Ctrl+2", "По ширине"),
    ("Ctrl+Shift+N", "Перейти к странице"), ("Home / End", "Первая / последняя страница"),
    ("PgUp / PgDn, Пробел", "Экран вверх / вниз"), ("← / →", "Предыдущая / следующая страница"),
    ("Alt+← / Alt+→", "Назад / вперёд по истории переходов"),
    ("Ctrl+Shift+= / Ctrl+Shift+-", "Повернуть вид по / против часовой"),
    ("F4", "Показать / скрыть боковую панель"), ("Ctrl+H", "Режим чтения"),
    ("Ctrl+L", "Полноэкранный режим (презентация)"), ("Ctrl+Shift+H", "Автопрокрутка"),
    ("Ctrl+Shift+I", "Ночной режим"), ("V / H", "Инструменты «Выделение» / «Рука»"),
    ("Esc", "Выход из режима / снять выделение / закрыть поиск"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Горячие клавиши")
        self.resize(560, 640)
        t = QTableWidget(len(SHORTCUTS), 2)
        t.setHorizontalHeaderLabels(["Клавиши", "Действие"])
        t.verticalHeader().hide()
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for r, (k, v) in enumerate(SHORTCUTS):
            t.setItem(r, 0, QTableWidgetItem(k))
            t.setItem(r, 1, QTableWidgetItem(v))
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        lay = QVBoxLayout(self)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def about_text() -> str:
    import pymupdf
    from PySide6 import __version__ as qt_ver
    return (
        f"<h3>{APP_NAME} {VERSION}</h3>"
        "<p>Автономный просмотрщик PDF в стиле Adobe Acrobat.</p>"
        f"<p>Движок: MuPDF {pymupdf.mupdf_version} (PyMuPDF {pymupdf.VersionBind})<br>"
        f"Интерфейс: Qt {qt_ver} (PySide6)</p>"
    )


class HomePage(QWidget):
    """Start page with "open" button and the recent files list."""

    openRequested = Signal()
    fileRequested = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setObjectName("homePage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 36, 48, 36)
        title = QLabel(f"Добро пожаловать в {APP_NAME}")
        title.setObjectName("homeTitle")
        outer.addWidget(title)
        sub = QLabel("Откройте PDF-файл или перетащите его в это окно.")
        sub.setObjectName("dimLabel")
        outer.addWidget(sub)
        outer.addSpacing(18)

        btns = QHBoxLayout()
        b = QPushButton(icons.icon("open", "#ffffff"), "  Открыть файл")
        b.setObjectName("primary")
        b.setIconSize(QSize(18, 18))
        b.setMinimumHeight(34)
        b.clicked.connect(self.openRequested)
        btns.addWidget(b)
        btns.addStretch(1)
        outer.addLayout(btns)
        outer.addSpacing(22)

        card = QWidget()
        card.setObjectName("homeCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        lbl = QLabel("<b>Недавние файлы</b>")
        head.addWidget(lbl)
        head.addStretch(1)
        clear = QPushButton("Очистить список")
        clear.clicked.connect(self._clear)
        head.addWidget(clear)
        cl.addLayout(head)
        self.list = QListWidget()
        self.list.setIconSize(QSize(22, 22))
        self.list.itemActivated.connect(self._open_item)
        self.list.itemClicked.connect(self._open_item)
        cl.addWidget(self.list)
        self.empty = QLabel("Здесь появятся недавно открытые документы.")
        self.empty.setObjectName("dimLabel")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.empty)
        outer.addWidget(card, 1)
        self.refresh()

    def refresh(self):
        self.list.clear()
        files = self.settings.recent_files()
        for p in files:
            exists = os.path.exists(p)
            it = QListWidgetItem(icons.icon("file_pdf", "#d7373f" if exists else "#999999"),
                                 f"{os.path.basename(p)}\n{os.path.dirname(p)}")
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setSizeHint(QSize(100, 44))
            if not exists:
                it.setToolTip("Файл не найден")
            self.list.addItem(it)
        self.empty.setVisible(not files)
        self.list.setVisible(bool(files))

    def _open_item(self, item):
        self.fileRequested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _clear(self):
        self.settings.clear_recent()
        self.refresh()
