@echo off
rem Деканат кезегі: сайтты Wi-Fi желісіне ашу (телефоннан кіру үшін)
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python run.py --lan
pause
