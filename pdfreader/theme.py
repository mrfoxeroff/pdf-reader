"""Acrobat-like light and dark themes."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import icons


@dataclass
class Theme:
    name: str
    window: str
    bar: str          # toolbars, side rail, panels
    bar_border: str
    canvas: str       # area behind pages
    text: str
    text_dim: str
    hover: str
    pressed: str
    accent: str
    accent_text: str
    input_bg: str
    input_border: str
    tab_inactive: str
    page_shadow: str
    selection: str


LIGHT = Theme(
    name="light", window="#f5f5f5", bar="#ffffff", bar_border="#e1e1e1",
    canvas="#e9e9e9", text="#2c2c2c", text_dim="#6e6e6e", hover="#ececec",
    pressed="#dedede", accent="#1473e6", accent_text="#ffffff",
    input_bg="#ffffff", input_border="#c8c8c8", tab_inactive="#f0f0f0",
    page_shadow="#000000", selection="#cfe3fb",
)

DARK = Theme(
    name="dark", window="#1d1d1d", bar="#252525", bar_border="#3a3a3a",
    canvas="#323232", text="#e8e8e8", text_dim="#a3a3a3", hover="#3a3a3a",
    pressed="#474747", accent="#3d8af7", accent_text="#ffffff",
    input_bg="#1d1d1d", input_border="#4a4a4a", tab_inactive="#1d1d1d",
    page_shadow="#000000", selection="#2b4a73",
)

_current = LIGHT


def current() -> Theme:
    return _current


def _close_icon_path(t: Theme) -> str:
    import os

    from .paths import temp_dir
    path = os.path.join(temp_dir(), f"tab_close_{t.name}.png")
    if not os.path.exists(path):
        icons._render("close", QColor(t.text_dim), 32).save(path)
    return path.replace("\\", "/")


def stylesheet(t: Theme) -> str:
    close_icon = _close_icon_path(t)
    return f"""
    QWidget {{ color: {t.text}; font-family: "Segoe UI", "Segoe UI Variable", Arial; font-size: 9pt; }}
    QMainWindow, QDialog {{ background: {t.window}; }}
    QMenuBar {{ background: {t.bar}; border-bottom: 1px solid {t.bar_border}; padding: 1px 4px; }}
    QMenuBar::item {{ padding: 4px 9px; border-radius: 4px; background: transparent; }}
    QMenuBar::item:selected {{ background: {t.hover}; }}
    QMenu {{ background: {t.bar}; border: 1px solid {t.bar_border}; padding: 4px; border-radius: 6px; }}
    QMenu::item {{ padding: 5px 28px 5px 26px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.hover}; }}
    QMenu::item:disabled {{ color: {t.text_dim}; }}
    QMenu::separator {{ height: 1px; background: {t.bar_border}; margin: 4px 6px; }}
    QMenu::icon {{ padding-left: 6px; }}

    QToolBar {{ background: {t.bar}; border: none; border-bottom: 1px solid {t.bar_border}; spacing: 2px; padding: 3px 6px; }}
    QToolBar::separator {{ background: {t.bar_border}; width: 1px; margin: 6px 6px; }}
    QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 4px; }}
    QToolButton:hover {{ background: {t.hover}; }}
    QToolButton:pressed {{ background: {t.pressed}; }}
    QToolButton:checked {{ background: {t.selection}; border-color: transparent; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QToolButton#railButton {{ border-radius: 6px; padding: 7px; margin: 2px 4px; }}
    QToolButton#railButton:checked {{ background: {t.selection}; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar {{ background: {t.window}; }}
    QTabBar::tab {{ background: {t.tab_inactive}; color: {t.text_dim}; padding: 7px 10px 7px 12px;
                    border: 1px solid {t.bar_border}; border-bottom: none; margin-right: 2px;
                    border-top-left-radius: 6px; border-top-right-radius: 6px; min-width: 90px; max-width: 240px; }}
    QTabBar::tab:selected {{ background: {t.bar}; color: {t.text}; }}
    QTabBar::tab:hover:!selected {{ background: {t.hover}; }}
    QTabBar::close-button {{ image: url("{close_icon}"); subcontrol-position: right; width: 14px; height: 14px;
                             border-radius: 3px; padding: 1px; }}
    QTabBar::close-button:hover {{ background: {t.pressed}; }}

    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{ background: {t.input_bg}; border: 1px solid {t.input_border};
                    border-radius: 4px; padding: 3px 6px; selection-background-color: {t.accent}; selection-color: white; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {t.accent}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: {t.bar}; border: 1px solid {t.bar_border}; selection-background-color: {t.hover}; selection-color: {t.text}; }}

    QPushButton {{ background: {t.bar}; border: 1px solid {t.input_border}; border-radius: 14px; padding: 5px 16px; }}
    QPushButton:hover {{ background: {t.hover}; }}
    QPushButton:default, QPushButton#primary {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
    QPushButton:default:hover, QPushButton#primary:hover {{ background: #0d66d0; }}

    QListView, QTreeView, QTreeWidget, QListWidget {{ background: {t.bar}; border: none; outline: 0; }}
    QListView::item, QTreeView::item {{ padding: 3px; border-radius: 4px; }}
    QListView::item:selected, QTreeView::item:selected {{ background: {t.selection}; color: {t.text}; }}
    QListView::item:hover, QTreeView::item:hover {{ background: {t.hover}; }}
    QHeaderView::section {{ background: {t.bar}; border: none; border-bottom: 1px solid {t.bar_border}; padding: 4px; }}

    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: rgba(128,128,128,0.45); border-radius: 4px; min-height: 30px; margin: 2px 3px; }}
    QScrollBar::handle:vertical:hover {{ background: rgba(128,128,128,0.75); }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: rgba(128,128,128,0.45); border-radius: 4px; min-width: 30px; margin: 3px 2px; }}
    QScrollBar::handle:horizontal:hover {{ background: rgba(128,128,128,0.75); }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    QStatusBar {{ background: {t.bar}; border-top: 1px solid {t.bar_border}; color: {t.text_dim}; }}
    QSplitter::handle {{ background: {t.bar_border}; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; }}
    QToolTip {{ background: {t.bar}; color: {t.text}; border: 1px solid {t.bar_border}; padding: 4px; }}

    #sideRail {{ background: {t.bar}; border-right: 1px solid {t.bar_border}; }}
    #sidePanel {{ background: {t.bar}; border-right: 1px solid {t.bar_border}; }}
    #panelTitle {{ font-size: 10pt; font-weight: 600; padding: 8px 10px; }}
    #findBar {{ background: {t.bar}; border: 1px solid {t.bar_border}; border-radius: 8px; }}
    #homePage {{ background: {t.window}; }}
    #homeTitle {{ font-size: 20pt; font-weight: 300; }}
    #homeCard {{ background: {t.bar}; border: 1px solid {t.bar_border}; border-radius: 10px; }}
    #dimLabel {{ color: {t.text_dim}; }}
    #pageBox {{ max-width: 46px; }}
    """


def apply(app: QApplication, name: str):
    global _current
    _current = DARK if name == "dark" else LIGHT
    t = _current
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(t.window))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Base, QColor(t.input_bg))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.bar))
    pal.setColor(QPalette.ColorRole.Text, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Button, QColor(t.bar))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.bar))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.text_dim))
    app.setPalette(pal)
    icons.set_icon_color(t.text, t.accent)
    app.setStyleSheet(stylesheet(t))
