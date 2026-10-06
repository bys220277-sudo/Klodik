@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================
echo   Klodik v4.4 - installation
echo ==============================================
echo.
echo Step 1/3: building Klodik.exe (takes a few minutes the first time)...
call build.bat nopause
if errorlevel 1 (
  echo.
  echo Installation failed, see the messages above.
  pause
  exit /b 1
)

echo.
echo Step 2/3: copying to %LOCALAPPDATA%\Programs\Klodik ...
set "DEST=%LOCALAPPDATA%\Programs\Klodik"
if not exist "%DEST%" mkdir "%DEST%"
taskkill /f /im Klodik.exe >nul 2>&1
taskkill /f /im ClaudePet.exe >nul 2>&1
copy /y "dist\Klodik.exe" "%DEST%\Klodik.exe" >nul
if errorlevel 1 (
  echo ERROR: could not copy Klodik.exe
  pause
  exit /b 1
)

echo Step 3/3: desktop shortcut "Klodik" ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Klodik.lnk'); $s.TargetPath='%DEST%\Klodik.exe'; $s.WorkingDirectory='%DEST%'; $s.Save()"

echo.
echo Done! Starting the crab...
start "" "%DEST%\Klodik.exe"
echo.
echo The crab lives at the bottom of the screen. Right click it for the menu.
echo For the AI chat: install LM Studio, see README.md
pause
