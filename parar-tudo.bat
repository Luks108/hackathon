@echo off
rem Desliga site, gateway do WhatsApp e worker (nao desliga o Docker nem apaga dado). Com --ComBancos desliga tambem os bancos.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\parar-tudo.ps1" %*
echo.
pause
