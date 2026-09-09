@echo off
setlocal
cd /d "%~dp0"
if exist "backend\.venv\Scripts\python.exe" (
  "backend\.venv\Scripts\python.exe" VALIDAR_V9.py
) else (
  python VALIDAR_V9.py
)
pause
