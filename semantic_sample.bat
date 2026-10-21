@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo The virtual environment is missing. Run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe semantic_sample.py %*
pause
