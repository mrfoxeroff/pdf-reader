@echo off
rem Updates PDF Reader to the latest version published on GitHub.
rem Downloads the new installer, installs it silently and restarts the program.
start "" "%~dp0PDFReader.exe" --update --yes
