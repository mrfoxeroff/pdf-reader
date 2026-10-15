# PyInstaller spec: single-file portable build (dist\PDFReader-portable.exe)
# Usage:  .venv\Scripts\pyinstaller PDFReader-portable.spec --noconfirm
import os

block_cipher = None
EXCLUDES = [
    "tkinter", "unittest", "pydoc", "numpy", "cv2", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtSql", "PySide6.QtDesigner",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtTest", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtHelp", "PySide6.QtXml",
    "PySide6.QtUiTools", "PySide6.QtSpatialAudio", "PySide6.QtStateMachine",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=["win32process", "win32com.client", "pythoncom", "pywintypes"],
    excludes=EXCLUDES,
    noarchive=False,
)

# drop Qt translations and unused plugins to keep the exe small
def keep(entry):
    name = entry[0].replace("\\", "/")
    if "/translations/" in name and "qtbase_ru" not in name:
        return False
    for bad in ("qtvirtualkeyboard", "/qml/", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "opengl32sw"):
        if bad in name:
            return False
    return True

a.datas = [d for d in a.datas if keep(d)]
a.binaries = [b for b in a.binaries if keep(b)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PDFReader-portable",
    icon="assets/icon.ico",
    version="version_info.txt",
    console=False,
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
)
