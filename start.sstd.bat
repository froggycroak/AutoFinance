@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python and add it to PATH.
  pause
  exit /b 1
)
set AF_REPO=repo.sstd
start "" cmd /c "timeout /t 1 /nobreak >nul & start "" http://127.0.0.1:8766"
python -u -m backend
echo.
echo Server stopped.
pause
