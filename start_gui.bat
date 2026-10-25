@echo off
REM כל הזכויות שמורות לנתאי שנדורפי (c) 2026
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  echo לא נמצא Python במחשב. התקן אותו מ-python.org וסמן Add Python to PATH.
  pause
  exit /b
)
start "" pythonw photo_tools_gui.py
