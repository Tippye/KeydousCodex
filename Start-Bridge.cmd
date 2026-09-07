@echo off
if exist "%~dp0windows\dist\KeydousCodex\KeydousCodex.exe" (
  start "" "%~dp0windows\dist\KeydousCodex\KeydousCodex.exe" --data-dir "%~dp0windows\data"
  exit /b 0
)
call "%~dp0windows\Start-Bridge.cmd"
