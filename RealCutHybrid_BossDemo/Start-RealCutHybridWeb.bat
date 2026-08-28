@echo off
cd /d "%~dp0"
chcp 65001 >nul
call config\demo_env.bat
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
start "RealCut Auto Web" /min python web_server.py --port 8766
