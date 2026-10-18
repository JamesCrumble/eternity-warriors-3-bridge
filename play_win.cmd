@echo off
cd /d "%~dp0"
.\server\.venv\Scripts\python.exe play_win.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Launcher exited with code %errorlevel%. Check logs\play.log and logs\ew3gl.log
    pause
)
