@echo off
rem Builds the installer dist\PDFReader-Setup-<version>.exe
rem   build.bat           - installer (needs Inno Setup 6)
rem   build.bat portable  - additionally a single-file dist\PDFReader-portable.exe
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
call .venv\Scripts\python tools\make_icon.py || goto :error
call .venv\Scripts\pyinstaller PDFReader.spec --noconfirm || goto :error

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 not found. Install it:  winget install JRSoftware.InnoSetup
    goto :error
)
"%ISCC%" /Q installer.iss || goto :error

if /i "%~1"=="portable" (
    call .venv\Scripts\pyinstaller PDFReader-portable.spec --noconfirm || goto :error
)
echo.
echo Done. Installer: %~dp0dist\
dir /b dist\*.exe
exit /b 0
:error
echo Build failed.
exit /b 1
