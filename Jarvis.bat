@echo off
title Jarvis AI Assistant
chcp 65001 > nul
cd /d "D:\Ai\Jarvis"
echo ===================================================
echo             JARVIS AI ASSISTANT
echo ===================================================
echo [!] Starting Jarvis CLI...
echo.
"D:\Ai\Jarvis\.venv\Scripts\python.exe" -m app
if errorlevel 1 (
    echo.
    echo [!] Jarvis exited with an error.
    pause
)
