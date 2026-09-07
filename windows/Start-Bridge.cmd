@echo off
setlocal
cd /d "%~dp0"
if exist "dist\KeydousCodex\KeydousCodex.exe" (
  start "" "dist\KeydousCodex\KeydousCodex.exe"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "run_bridge.py"
  exit /b 0
)
if exist "..\.venv\Scripts\pythonw.exe" (
  start "" "..\.venv\Scripts\pythonw.exe" "run_bridge.py"
  exit /b 0
)
echo Python environment not found. Run Setup.ps1 first.
pause
exit /b 1
