@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
start "RealCut Hybrid Web" /min python web_server.py --host 127.0.0.1
