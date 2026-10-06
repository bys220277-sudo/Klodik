@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Klodik v4.4: build ===

if not exist "klodik.py" (
  echo ERROR: klodik.py not found next to build.bat
  goto fail
)
if not exist "pet_ai.py" (
  echo ERROR: pet_ai.py not found next to build.bat.
  echo The file must be named exactly pet_ai.py ^(not "pet_ai (1).py"^).
  goto fail
)

rem --- find Python: "py" launcher first, then "python" ---
if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ERROR: Python 3.10 or newer not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
  start "" https://www.python.org/downloads/
  goto fail
)
echo Using Python: %PY%

echo Closing running Klodik.exe ^(if any^)...
taskkill /f /im Klodik.exe >nul 2>&1
taskkill /f /im ClaudePet.exe >nul 2>&1

%PY% -m pip install --upgrade pyqt6 pyinstaller pypdf
if errorlevel 1 goto fail

echo Checking that pet_ai.py imports without errors...
%PY% -c "import pet_ai; print('pet_ai OK')"
if errorlevel 1 (
  echo ERROR: pet_ai.py has an error, see the message above.
  goto fail
)

%PY% klodik.py --make-icon
if exist icon.ico (set ICON=--icon icon.ico) else (set ICON=)
%PY% -m PyInstaller --noconfirm --clean --noconsole --onefile --name Klodik --paths . --hidden-import pet_ai --hidden-import pypdf --hidden-import sqlite3 %ICON% klodik.py
if errorlevel 1 goto fail
echo.
echo Done: dist\Klodik.exe
if /i "%~1"=="nopause" exit /b 0
echo Run it: an older copy will be closed automatically.
echo Claude Code hooks: right click the crab - Parametry - "Claude i sistema" - "Skopirovat huki",
echo then paste into %%USERPROFILE%%\.claude\settings.json
pause
exit /b 0
:fail
echo Build failed. Make sure Python 3.10+ is installed and added to PATH.
if /i "%~1"=="nopause" exit /b 1
pause
exit /b 1
