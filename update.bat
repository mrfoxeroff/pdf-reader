@echo off
rem Updates a source checkout of PDF Reader: pulls the latest code from GitHub
rem and installs new dependencies. (The installed app updates itself via
rem "Update PDF Reader" in the Start menu or Update.cmd in its folder.)
setlocal
cd /d "%~dp0"
git pull --ff-only || goto :error
if not exist .venv python -m venv .venv || goto :error
call .venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
echo Updated. Run: .venv\Scripts\python main.py   or build the installer: build.bat
exit /b 0
:error
echo Update failed.
exit /b 1
