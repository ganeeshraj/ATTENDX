@echo off
echo Stopping AttendX...
taskkill /F /FI "WINDOWTITLE eq AttendX*" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000') do taskkill /F /PID %%a >nul 2>&1
echo AttendX stopped.
pause
