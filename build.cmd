@echo off
setlocal
chcp 65001 > nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if not exist "requirements-dev.txt" goto missing_requirements
if not exist ".venv\Scripts\python.exe" call :create_venv
if errorlevel 1 goto setup_failed

".venv\Scripts\python.exe" -c "import PyInstaller" > nul 2>&1
if errorlevel 1 call :install_dependencies
if errorlevel 1 goto setup_failed

echo Building ImageWatcher.exe...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --name ImageWatcher --distpath "." --workpath "build\pyinstaller-cli" --specpath "build" --hidden-import winotify "src\main.py"
if errorlevel 1 goto build_failed
if not exist "ImageWatcher.exe" goto build_failed

echo Building ImageWatcherGUI.exe...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name ImageWatcherGUI --distpath "." --workpath "build\pyinstaller-gui" --specpath "build" --hidden-import winotify "src\gui.py"
if errorlevel 1 goto build_failed
if not exist "ImageWatcherGUI.exe" goto build_failed

echo.
echo [SUCCESS] ImageWatcher.exe and ImageWatcherGUI.exe were created.
pause
exit /b 0

:create_venv
echo [SETUP] Creating .venv in the project folder...
where py > nul 2>&1
if not errorlevel 1 (
    py -3 -m venv ".venv"
    if errorlevel 1 exit /b 1
    exit /b 0
)
where python > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3 was not found.
    exit /b 1
)
python -m venv ".venv"
if errorlevel 1 exit /b 1
exit /b 0

:install_dependencies
echo [SETUP] Installing build dependencies...
".venv\Scripts\python.exe" -m pip install -r "%~dp0requirements-dev.txt"
if errorlevel 1 exit /b 1
exit /b 0

:missing_requirements
echo [ERROR] requirements-dev.txt was not found next to build.cmd.
echo Extract the complete source ZIP before running build.cmd.
goto failed

:setup_failed
echo [ERROR] Python environment setup failed.
echo Check the network connection and Python installation, then run build.cmd again.
goto failed

:build_failed
echo [ERROR] The executable build failed.

:failed
pause
exit /b 1
