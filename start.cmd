@echo off
chcp 65001 > nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

where py > nul 2>&1
if errorlevel 1 (
    python src\main.py --config settings.ini
) else (
    py -3 src\main.py --config settings.ini
)
set "IMAGEWATCHER_EXIT=%errorlevel%"

echo.
pause
exit /b %IMAGEWATCHER_EXIT%

