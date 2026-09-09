@echo off
setlocal
cd /d "%~dp0"
if exist "backend\.venv\Scripts\python.exe" (
  "backend\.venv\Scripts\python.exe" VALIDAR_V6.py
) else (
  python VALIDAR_V6.py
)
echo.
pause
