@echo off
rem Builds dist\PDFReader.exe (a single portable file).
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
call .venv\Scripts\python tools\make_icon.py || goto :error
call .venv\Scripts\pyinstaller PDFReader.spec --noconfirm || goto :error
echo.
echo Done: %~dp0dist\PDFReader.exe
exit /b 0
:error
echo Build failed.
exit /b 1
