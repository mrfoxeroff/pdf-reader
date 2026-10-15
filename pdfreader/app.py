"""Application start-up: single instance, theme, main window."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import icons, theme
from .version import APP_NAME

SERVER_NAME = f"PDFReader-{os.environ.get('USERNAME', 'user')}"
APP_MUTEX = "PDFReaderAppMutex"  # also referenced by installer.iss (AppMutex)
_mutex = None


def _create_app_mutex():
    """Lets the installer/uninstaller detect that the app is running."""
    global _mutex
    if sys.platform == "win32":
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)


def _send_to_running_instance(paths: list[str]) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    payload = "\n".join(paths) if paths else "\n"
    sock.write(QByteArray(payload.encode("utf-8")))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    files = [os.path.abspath(a) for a in argv[1:] if not a.startswith("-") and os.path.exists(a)]

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PDFReader")
    app.setFont(QFont("Segoe UI", 9))

    if not any(a.startswith("--screenshot=") for a in argv) and _send_to_running_instance(files):
        return 0

    _create_app_mutex()
    from .pool import pool, shutdown_pool
    pool()  # start worker processes early, while the window is being built

    from .mainwindow import MainWindow
    from .settings import Settings

    theme.apply(app, Settings().get("theme", "light"))
    app.setWindowIcon(icons.app_icon())
    win = MainWindow()

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def read():
            data = bytes(sock.readAll()).decode("utf-8", "replace")
            for p in data.splitlines():
                if p.strip():
                    win.open_file(p.strip())
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()

        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(on_connection)

    if Settings().get("maximized", True):
        win.showMaximized()
    else:
        win.show()
    for f in files:
        QTimer.singleShot(0, lambda f=f: win.open_file(f))
    shot = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--screenshot=")), None)
    if shot:  # smoke test: grab the window after start-up and quit
        def grab():
            win.grab().save(shot)
            for t in win.doc_tabs():
                t.doc.set_modified(False)
            win.close()
        QTimer.singleShot(4000, grab)
    code = app.exec()
    server.close()
    shutdown_pool()
    return code
