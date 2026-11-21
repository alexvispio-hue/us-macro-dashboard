@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Macro Dashboard - update and publish
set "PYTHONUTF8=1"
set "PY=python"
%PY% -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 goto run
set "PY=py -3"
%PY% -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer was not found. Install Python and enable Add to PATH.
  if /I not "%~1"=="--no-pause" pause
  exit /b 1
)
:run
echo Updating data, validating and publishing to GitHub...
%PY% src\update_publish.py %*
set "RESULT=%ERRORLEVEL%"
echo.
if /I "%~1"=="--no-pause" exit /b %RESULT%
pause
exit /b %RESULT%
