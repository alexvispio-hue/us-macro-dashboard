@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Macro Dashboard - проверка источников

set PY=python
where python >nul 2>nul || set PY=py

%PY% -m pip install -q -r requirements.txt
%PY% src\build.py --doctor
echo.
echo   Скопируй этот вывод и покажи мне, если что-то не сошлось.
echo.
pause
