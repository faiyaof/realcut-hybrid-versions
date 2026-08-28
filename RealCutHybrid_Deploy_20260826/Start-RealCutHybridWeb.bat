@echo off
cd /d "%~dp0"
chcp 65001 >nul
call config\deploy_env.bat
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
start "RealCutHybrid Web" /min "%REALCUT_ROOT%\runtime\python\python.exe" web_server.py --port 8766
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:8766/"
