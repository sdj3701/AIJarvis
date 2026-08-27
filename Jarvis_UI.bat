@echo off
title JARVIS — STARK INDUSTRIES HUD
chcp 65001 > nul
cd /d "D:\Ai\Jarvis"
echo ===================================================
echo       JARVIS STARK INDUSTRIES NEURAL HUD
echo ===================================================
echo [!] Initializing Holographic Arc Reactor Interface...
echo.
start "" "D:\Ai\Jarvis\.venv\Scripts\python.exe" -m app --gui
