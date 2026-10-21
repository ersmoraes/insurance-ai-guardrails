@echo off
chcp 65001 >nul
echo =========================================================================
echo   SEGURADORA HORIZONTE - SIMULADOR DE PRÉ-ANÁLISE AUTO D0
echo =========================================================================
echo.
echo [*] Abrindo o navegador em http://localhost:8000 ...
start http://localhost:8000
echo [*] Iniciando o servidor Python...
echo Pressione Ctrl+C para encerrar o servidor.
echo.
call ".\.venv\Scripts\python.exe" server.py
pause
