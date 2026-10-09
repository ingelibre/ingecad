@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-IngeCAD.ps1"
if errorlevel 1 (
  echo Update failed. Read the error above before trying again.
  pause
  exit /b 1
)
pause
