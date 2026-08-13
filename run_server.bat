@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_server.ps1" -Mode Development
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Server launcher failed with exit code %EXIT_CODE%.
  echo [INFO] Review the error above and the latest logs\server-*.log file.
  if /I not "%LC_CANVAS_NO_PAUSE%"=="1" pause
)

exit /b %EXIT_CODE%
