@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Macro Dashboard

set PY=python
where python >nul 2>nul || set PY=py
%PY% --version >nul 2>nul || (
  echo.
  echo   Python не найден. Поставь его с python.org и отметь "Add to PATH".
  echo.
  pause
  exit /b 1
)

echo Проверяю зависимости...
%PY% -m pip install -q -r requirements.txt

%PY% src\build.py --open %*
if errorlevel 1 (
  echo.
  echo   Сборка завершилась с ошибкой. Текст выше.
)
echo.
pause
