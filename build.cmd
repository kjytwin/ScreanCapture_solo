@echo off
setlocal
chcp 65001 > nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto missing_venv

".venv\Scripts\python.exe" -c "import PyInstaller" > nul 2>&1
if errorlevel 1 goto missing_pyinstaller

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

:missing_venv
echo [ERROR] .venv was not found.
echo Run: py -3 -m venv .venv
goto failed

:missing_pyinstaller
echo [ERROR] PyInstaller is not installed.
echo Run: .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
goto failed

:build_failed
echo [ERROR] The executable build failed.

:failed
pause
exit /b 1
