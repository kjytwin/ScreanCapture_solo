@echo off
setlocal
chcp 65001 > nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if exist "ImageWatcher.exe" goto run_exe
if exist ".venv\Scripts\python.exe" goto run_venv
where py > nul 2>&1
if errorlevel 1 goto run_python
py -3 src\main.py --config settings.ini
goto run_done

:run_exe
ImageWatcher.exe --config settings.ini
goto run_done

:run_venv
".venv\Scripts\python.exe" src\main.py --config settings.ini
goto run_done

:run_python
python src\main.py --config settings.ini

:run_done
set "IMAGEWATCHER_EXIT=%errorlevel%"
echo.
pause
exit /b %IMAGEWATCHER_EXIT%
