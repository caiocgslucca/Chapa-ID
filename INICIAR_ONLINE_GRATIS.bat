@echo off
setlocal EnableExtensions
title CHAPA ID - Acesso Online Gratis
cd /d "%~dp0"

echo ============================================================
echo   CHAPA ID - ACESSO ONLINE GRATIS - CLOUDFLARE TUNNEL
echo ============================================================
echo Nao exige cartao, conta Cloudflare ou liberacao de porta.
echo Cada projeto usa automaticamente uma porta local diferente.
echo.

set "PYTHON_CMD="

if exist "backend\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=backend\.venv\Scripts\python.exe"
    goto :python_ok
)

where python >nul 2>&1 && set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)
if not defined PYTHON_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PYTHON_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)

if not defined PYTHON_CMD (
    echo ERRO: Python nao localizado.
    pause
    exit /b 1
)

:python_ok

if not exist "backend\.venv\Scripts\python.exe" (
    echo Criando ambiente Python do CHAPA ID...
    "%PYTHON_CMD%" -m venv "backend\.venv"
    if errorlevel 1 goto :falha
)

set "PY=backend\.venv\Scripts\python.exe"

echo Verificando dependencias...
"%PY%" -m pip install --disable-pip-version-check --prefer-binary -r "backend\requirements.txt"
if errorlevel 1 goto :falha

"%PY%" online_launcher.py
exit /b %errorlevel%

:falha
echo.
echo ERRO: nao foi possivel preparar o CHAPA ID.
pause
exit /b 1
