@echo off
setlocal
cd /d "%~dp0backend"

where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install Python 3.11+ and enable "Add Python to PATH".
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 goto :error
)

call "venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Starting AttendX...
start "AttendX Browser" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000/"
python app.py
pause
exit /b 0

:error
echo.
echo AttendX could not start. Check the error above.
pause
exit /b 1
