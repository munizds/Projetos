@echo off
setlocal
chcp 65001 >nul
if "%~3"=="" (
 echo USO: rodar_no_windows.bat "PASTA_BT4" "PASTA_GAMEDATA_BT3" "PASTA_RELATORIOS"
 exit /b 1
)
where py >nul 2>nul
if %errorlevel%==0 (
 py -3 "%~dp0bt4_ferramenta.py" analisar --bt4 "%~1" --bt3 "%~2" --saida "%~3"
) else (
 python "%~dp0bt4_ferramenta.py" analisar --bt4 "%~1" --bt3 "%~2" --saida "%~3"
)
pause
