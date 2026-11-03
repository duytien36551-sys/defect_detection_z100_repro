@echo off
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -B "board\run_desktop.py" %*
) else (
    py -3 -B "board\run_desktop.py" %*
)
if errorlevel 1 pause
