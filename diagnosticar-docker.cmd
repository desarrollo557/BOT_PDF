@echo off
rem Reune en diagnostico-docker.txt lo necesario para saber por que BOT_PDF en Docker falla.
rem Doble clic; en CMD: diagnosticar-docker; en PowerShell: .\diagnosticar-docker.cmd
rem Para probar tambien con un PDF real:  .\diagnosticar-docker.cmd -Archivo "C:\ruta\archivo.pdf"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\diagnosticar-docker.ps1" %*
pause
