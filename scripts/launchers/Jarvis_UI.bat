@echo off
setlocal
cd /d "%~dp0..\.."
if exist "bin\Jarvis.exe" (
    start "" "bin\Jarvis.exe"
) else (
    start "" ".venv\Scripts\pythonw.exe" -m app --gui
)
