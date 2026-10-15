"""Update notification banner and the update dialog."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QTextBrowser,
    QToolButton, QVBoxLayout, QWidget,
)

from . import icons, theme, updater
from .version import APP_NAME

DAY = 24 * 3600


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} МБ"


class UpdateBanner(QWidget):
    """Bar under the toolbar: "a new version is available"."""

    updateRequested = Signal(object)   # Release
    postponed = Signal(object, int)    # Release, seconds (0 = skip this version)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updateBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.release = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 8, 6)
        lay.setSpacing(8)
        self.icon = QLabel()
        self.icon.setPixmap(icons.icon("download", theme.current().accent).pixmap(20, 20))
        lay.addWidget(self.icon)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.linkActivated.connect(self._show_notes)
        lay.addWidget(self.text, 1)
        self.btn_update = QPushButton("Обновить")
        self.btn_update.setObjectName("primary")
        self.btn_update.clicked.connect(lambda: self.updateRequested.emit(self.release))
        lay.addWidget(self.btn_update)
        later = QPushButton("Отложить")
        m = QMenu(later)
        m.addAction("Напомнить через час", lambda: self._postpone(3600))
        m.addAction("Напомнить завтра", lambda: self._postpone(DAY))
        m.addAction("Напомнить через неделю", lambda: self._postpone(7 * DAY))
        m.addSeparator()
        m.addAction("Пропустить эту версию", lambda: self._postpone(0))
        later.setMenu(m)
        lay.addWidget(later)
        close = QToolButton()
        close.setIcon(icons.icon("close"))
        close.setToolTip("Скрыть (напомнить завтра)")
        close.clicked.connect(lambda: self._postpone(DAY))
        lay.addWidget(close)
        self.hide()

    def show_release(self, release):
        self.release = release
        self.text.setText(
            f"<b>Доступна новая версия {APP_NAME} {release.version}</b> "
            f"(у вас {updater.current_version()}). "
            f"<a href='notes' style='color:{theme.current().accent}'>Что нового?</a>")
        self.show()

    def _postpone(self, seconds):
        self.hide()
        self.postponed.emit(self.release, seconds)

    def _show_notes(self, _link):
        dlg = UpdateDialog(self.window(), release=self.release, notes_only=True)
        dlg.exec()


class UpdateDialog(QDialog):
    """Check -> show what's new -> download with progress -> install.

    ``auto=True`` downloads and installs without asking (Update script).
    ``prepare_exit`` is called before installing; returning False aborts
    (e.g. the user cancelled saving documents).
    """

    def __init__(self, parent=None, release=None, auto=False, notes_only=False, prepare_exit=None):
        super().__init__(parent)
        self.setWindowTitle(f"Обновление {APP_NAME}")
        self.setWindowIcon(icons.app_icon())
        self.setMinimumWidth(520)
        self.release = release
        self.auto = auto
        self.notes_only = notes_only
        self.prepare_exit = prepare_exit
        self.downloader = None
        self.installed = False

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("dimLabel")
        lay.addWidget(self.info)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(180)
        self.notes.hide()
        lay.addWidget(self.notes, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        lay.addWidget(self.bar)
        btns = QHBoxLayout()
        self.btn_page = QPushButton("Страница релиза")
        self.btn_page.clicked.connect(self._open_page)
        self.btn_page.hide()
        btns.addWidget(self.btn_page)
        btns.addStretch(1)
        self.btn_main = QPushButton("Обновить сейчас")
        self.btn_main.setObjectName("primary")
        self.btn_main.setDefault(True)
        self.btn_main.clicked.connect(self._start_download)
        self.btn_main.hide()
        btns.addWidget(self.btn_main)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)

        if release is None:
            self._check()
        else:
            self._show_release(release)

    # ------------------------------------------------------------- states
    def _check(self):
        self.title.setText("Проверка обновлений…")
        self.info.setText(f"Установлена версия {updater.current_version()}.")
        self.bar.setRange(0, 0)
        self.bar.show()
        self.checker = updater.UpdateChecker()
        self.checker.found.connect(self._show_release)
        self.checker.upToDate.connect(self._up_to_date)
        self.checker.failed.connect(self._failed)
        self.checker.check()

    def _up_to_date(self, rel):
        self.bar.hide()
        self.title.setText("У вас последняя версия")
        self.info.setText(f"{APP_NAME} {updater.current_version()} — актуальная версия "
                          f"(последний выпуск на GitHub: {rel.version}).")
        if self.auto:
            QTimer.singleShot(2500, self.accept)

    def _failed(self, msg):
        self.bar.hide()
        self.title.setText("Не удалось проверить обновления")
        self.info.setText(msg)
        self.btn_page.show()

    def _show_release(self, rel):
        self.release = rel
        self.bar.hide()
        self.title.setText(f"Доступна версия {rel.version}")
        asset = updater.asset_for_this_install(rel)
        kind = updater.install_kind()
        size = f" ({_mb(asset.size)})" if asset else ""
        self.info.setText(f"У вас версия {updater.current_version()}. "
                          f"Будет скачано обновление{size}, программа перезапустится сама.")
        self.notes.setMarkdown(rel.notes or "_Описание изменений отсутствует._")
        self.notes.show()
        self.btn_page.show()
        if self.notes_only:
            self.info.setText(f"У вас версия {updater.current_version()}.")
            return
        if kind == "source":
            self.info.setText("Программа запущена из исходников — обновите её командой git pull.")
            return
        if asset is None:
            self.info.setText("В этом выпуске нет файла для вашего варианта установки.")
            return
        self.btn_main.show()
        if self.auto:
            QTimer.singleShot(300, self._start_download)

    def _start_download(self):
        asset = updater.asset_for_this_install(self.release)
        self.btn_main.setEnabled(False)
        self.title.setText(f"Загрузка {self.release.version}…")
        self.bar.setRange(0, max(1, asset.size))
        self.bar.setValue(0)
        self.bar.show()
        self.downloader = updater.Downloader(asset)
        self.downloader.progress.connect(self._progress)
        self.downloader.finished.connect(self._downloaded)
        self.downloader.failed.connect(self._download_failed)
        self.downloader.start()
        self.btn_close.setText("Отмена")

    def _progress(self, done, total):
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        self.info.setText(f"Скачано {_mb(done)} из {_mb(total)}")

    def _download_failed(self, msg):
        self.bar.hide()
        self.title.setText("Ошибка загрузки")
        self.info.setText(msg)
        self.btn_main.setEnabled(True)
        self.btn_main.setText("Повторить")
        self.btn_close.setText("Закрыть")

    def _downloaded(self, path):
        self.title.setText("Установка обновления…")
        self.info.setText("Программа закроется и через несколько секунд откроется уже новой версией.")
        self.bar.setRange(0, 0)
        if self.prepare_exit is not None and not self.prepare_exit():
            self.bar.hide()
            self.title.setText("Обновление отложено")
            self.info.setText("Файл обновления скачан — установите его позже.")
            self.btn_main.setEnabled(True)
            self.btn_main.setText("Установить")
            self.btn_main.clicked.disconnect()
            self.btn_main.clicked.connect(lambda: self._downloaded(path))
            self.btn_close.setText("Закрыть")
            return
        try:
            updater.apply_update(path)
        except Exception as exc:
            self.title.setText("Не удалось запустить установку")
            self.info.setText(str(exc))
            return
        self.installed = True
        QTimer.singleShot(400, self.accept)

    def _open_page(self):
        url = self.release.page_url if self.release else updater.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def reject(self):
        if self.downloader is not None:
            self.downloader.cancel()
        super().reject()


class AutoUpdateScheduler:
    """Periodic background check that shows the banner (respecting snooze)."""

    INTERVAL_MS = 6 * 3600 * 1000

    def __init__(self, window, banner: UpdateBanner, settings):
        self.window = window
        self.banner = banner
        self.settings = settings
        self.checker = updater.UpdateChecker()
        self.checker.found.connect(self._found)
        self.timer = QTimer(window, interval=self.INTERVAL_MS, timeout=self.check_now)
        banner.postponed.connect(self._postponed)

    def start(self):
        if self.enabled():
            QTimer.singleShot(4000, self.check_now)
        self.timer.start()

    def enabled(self) -> bool:
        return self.settings.get("auto_update", True) and updater.install_kind() != "source"

    def check_now(self):
        if self.enabled():
            self.checker.check()

    def _found(self, rel):
        if rel.version == self.settings.get("update_skip", ""):
            return
        if time.time() < float(self.settings.get("update_snooze_until", 0) or 0):
            return
        self.banner.show_release(rel)

    def _postponed(self, rel, seconds):
        if seconds == 0:
            self.settings.set("update_skip", rel.version)
        else:
            self.settings.set("update_snooze_until", time.time() + seconds)
