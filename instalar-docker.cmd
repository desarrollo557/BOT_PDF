@echo off
rem Instala BOT_PDF con Docker y lo abre en el navegador.
rem Doble clic; en CMD: instalar-docker; en PowerShell: .\instalar-docker.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar-escritorio.ps1" %*
if errorlevel 1 pause
