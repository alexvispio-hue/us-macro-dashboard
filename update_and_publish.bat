@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Macro Dashboard - обновление и публикация
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите Python и включите Add to PATH.
  pause
  exit /b 1
)
echo Обновление данных, проверка и публикация на GitHub...
%PY% src\update_publish.py %*
set "RESULT=%ERRORLEVEL%"
echo.
if /I "%~1"=="--no-pause" exit /b %RESULT%
pause
exit /b %RESULT%
