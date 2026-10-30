@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 mod_installer.py
) else (
    python mod_installer.py
)
if ERRORLEVEL 1 (
    echo.
    echo Nao foi possivel iniciar o instalador. Instale Python 3 com tkinter.
    pause
)