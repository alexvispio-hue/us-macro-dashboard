@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Macro Dashboard - update and publish
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python and enable Add to PATH.
  pause
  exit /b 1
)
echo Updating data, validating and publishing to GitHub...
%PY% src\update_publish.py %*
set "RESULT=%ERRORLEVEL%"
echo.
if /I "%~1"=="--no-pause" exit /b %RESULT%
pause
exit /b %RESULT%
