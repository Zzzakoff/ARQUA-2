@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -m venv .venv
    if errorlevel 1 goto :failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
.venv\Scripts\python.exe manage.py migrate
if errorlevel 1 goto :failed
echo.
echo Site: http://127.0.0.1:8000/
echo To create an administrator, stop the server and run:
echo .venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver
pause
exit /b 0
:failed
echo Setup failed. Check the errors above.
pause
exit /b 1
