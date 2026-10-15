@echo off
rem Division de documentos AFINIA: levanta el backend y el front, cada uno en su ventana de cmd.
rem Uso, desde esta carpeta:  division-afinia
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\levantar.ps1" -Ventanas %*
