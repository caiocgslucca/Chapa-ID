@echo off
title CHAPA ID - Diagnostico Python
echo ============================================
echo  CHAPA ID - DIAGNOSTICO DO PYTHON
echo ============================================
echo.
echo [python --version]
python --version 2>&1
echo.
echo [where python]
where python 2>&1
echo.
echo [where python3]
where python3 2>&1
echo.
echo [caminhos comuns]
if exist "%LOCALAPPDATA%\Programs\Python" dir /b "%LOCALAPPDATA%\Programs\Python"
echo.
pause
