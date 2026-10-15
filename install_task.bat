@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if not exist .venv\Scripts\pythonw.exe (
  echo The quiet Python launcher is missing. Run setup.bat again, then retry.
  pause
  exit /b 1
)
set "PYTHON=%~dp0.venv\Scripts\pythonw.exe"
set "SCRIPT=%~dp0watcher.py"
set "ACTION=\"%PYTHON%\" \"%SCRIPT%\" --run-once"
 schtasks /Create /TN "Antilogicalism Feed Watcher" /SC MINUTE /MO 15 /TR "%ACTION%" /F /IT
if errorlevel 1 (
  echo.
  echo Windows could not create the scheduled task. You can set it up manually; see README.md.
  pause
  exit /b 1
)
echo.
echo Scheduled to check quietly every 15 minutes; feed fetching remains limited to once an hour.
echo Your existing config.json, .env, and queue state are unchanged.
pause
