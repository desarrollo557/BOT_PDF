@echo off
rem Prueba de aceptacion de BOT_PDF en Docker: dice, punto por punto, si la instalacion funciona.
rem Doble clic; en CMD: probar-instalacion; en PowerShell: .\probar-instalacion.cmd
rem Rapida, sin la corrida de punta a punta:  .\probar-instalacion.cmd -Rapida
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\probar-instalacion.ps1" %*
pause
