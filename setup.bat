@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Setup complete. Next, double-click setup_baseline.bat once.
pause
exit /b 0
:failed
echo.
echo Setup failed. Check that Python 3 is installed and this computer is online.
pause
exit /b 1
