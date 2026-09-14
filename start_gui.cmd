@echo off
setlocal
chcp 65001 > nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if exist "ImageWatcherGUI.exe" goto run_exe
if exist ".venv\Scripts\pythonw.exe" goto run_venv
where pyw > nul 2>&1
if errorlevel 1 goto run_python
pyw -3 src\gui.py --config settings.ini
exit /b %errorlevel%

:run_exe
start "" ImageWatcherGUI.exe --config settings.ini
exit /b 0

:run_venv
start "" ".venv\Scripts\pythonw.exe" src\gui.py --config settings.ini
exit /b 0

:run_python
pythonw src\gui.py --config settings.ini
exit /b %errorlevel%
