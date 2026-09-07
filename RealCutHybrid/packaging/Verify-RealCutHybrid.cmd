@echo off
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Verify-RealCutHybrid.ps1" -InstallerDirectory "%~dp0"
set "VERIFY_EXIT=%ERRORLEVEL%"
echo.
if not "%VERIFY_EXIT%"=="0" echo Verification failed. Do not run the installer.
pause
exit /b %VERIFY_EXIT%
