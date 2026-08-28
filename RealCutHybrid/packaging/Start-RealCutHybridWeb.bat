@echo off
cd /d "%~dp0"
chcp 65001 >nul
call config\deploy_env.bat

if not exist "%REALCUT_ROOT%\bin\web_server.exe" (
  echo [ERROR] Missing bin\web_server.exe
  pause
  exit /b 1
)

start "RealCutHybrid Web" /min "%REALCUT_ROOT%\bin\web_server.exe" --port 8766
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:8766/"
