@echo off
title Jarvis AI Voice Assistant
chcp 65001 > nul
cd /d "D:\Ai\Jarvis"
echo ===================================================
echo         JARVIS AI VOICE ASSISTANT
echo ===================================================
echo [!] Starting Jarvis in Voice Mode...
echo [!] Say 'Jarvis' (자비스) to wake up!
echo.
"D:\Ai\Jarvis\.venv\Scripts\python.exe" -m app --voice
if errorlevel 1 (
    echo.
    echo [!] Jarvis Voice exited with an error.
    pause
)
