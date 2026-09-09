@echo off
setlocal
cd /d "%~dp0"
if exist "backend\.venv\Scripts\python.exe" (
  "backend\.venv\Scripts\python.exe" VALIDAR_V8.py
) else (
  python VALIDAR_V8.py
)
pause
