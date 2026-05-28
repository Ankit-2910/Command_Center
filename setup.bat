@echo off
title OBSIDIAN Command Center - Setup
echo ============================================
echo   Installing the command center (one time)
echo ============================================
echo.
python -m pip install --upgrade pip
python -m pip install flask feedparser requests
echo.
echo ============================================
echo   Setup complete! Now double-click start_dashboard.bat
echo ============================================
echo.
pause
