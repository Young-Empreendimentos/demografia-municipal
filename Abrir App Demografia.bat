@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Demografia Municipal - App
echo ============================================================
echo   DEMOGRAFIA MUNICIPAL
echo ------------------------------------------------------------
echo   Iniciando o app... uma aba do navegador vai abrir sozinha.
echo   Se nao abrir, acesse:  http://localhost:8501
echo.
echo   NAO FECHE esta janela enquanto usar o app.
echo   Para encerrar, feche esta janela.
echo ============================================================
echo.

python -m streamlit run app.py

echo.
echo O app foi encerrado.
pause
