@echo off
rem Actualiza BOT_PDF en Docker: lo detiene, trae la ultima version (git pull) y lo vuelve a arrancar.
rem Doble clic; en CMD: actualizar-docker; en PowerShell: .\actualizar-docker.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\actualizar-docker.ps1" %*
if errorlevel 1 pause
