@echo off
rem Gera a base de conhecimento a partir dos documentos da pasta "conhecimento".
rem Basta dar dois cliques. Requer Python instalado.
cd /d "%~dp0"
python -X utf8 gerar_conhecimento.py
echo.
pause
