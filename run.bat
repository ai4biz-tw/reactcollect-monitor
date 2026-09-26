@echo off
cd /d %~dp0
where python >nul 2>nul || (echo 請先安裝 Python 3：https://www.python.org/downloads/ && pause && exit /b 1)
python app.py
pause
