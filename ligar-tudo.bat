@echo off
rem Liga Docker, bancos, site, gateway do WhatsApp e worker. Pode rodar de novo: so sobe o que falta.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ligar-tudo.ps1" %*
echo.
pause
