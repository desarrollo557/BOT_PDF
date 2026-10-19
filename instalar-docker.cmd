@echo off
rem Instala BOT_PDF con Docker y lo abre en el navegador. Doble clic, o desde cmd o PowerShell:
rem   instalar-docker
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar-escritorio.ps1" %*
if errorlevel 1 pause
