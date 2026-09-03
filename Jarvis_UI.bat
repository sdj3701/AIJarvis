@echo off
cd /d "%~dp0"
if exist "Jarvis.exe" (
    start "" "Jarvis.exe"
) else (
    start "" ".venv\Scripts\pythonw.exe" -m app --gui
)
exit
