"""Render the application icon to assets/icon.ico (run once before building)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from pdfreader.icons import app_icon_pixmap  # noqa: E402

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out, exist_ok=True)
    app_icon_pixmap(256).save(os.path.join(out, "icon.png"))
    ok = app_icon_pixmap(256).save(os.path.join(out, "icon.ico"))
    print("icon.ico written" if ok else "ICO writer unavailable")
