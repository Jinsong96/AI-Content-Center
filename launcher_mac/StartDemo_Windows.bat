@echo off
REM ============================================================
REM  AI Content Platform Demo - Windows one-click launcher
REM  Double-click this file. It checks/installs Python, starts
REM  the backend bridge, then opens the frontend page.
REM ============================================================
cd /d "%~dp0"

echo ======================================================
echo   AI Content Platform Demo - starting for you...
echo ======================================================

where python >nul 2>nul
if %errorlevel%==0 goto :RUN

echo.
echo Python not found - installing via winget (first time only, 2-5 min)...
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements >nul 2>nul

where python >nul 2>nul
if %errorlevel%==0 goto :RUN

echo.
echo Python install failed. Please install manually from https://www.python.org/downloads/
echo (check "Add python.exe to PATH"), then double-click this file again.
pause
exit /b

:RUN
echo Python ready: 
python --version

echo.
echo Starting backend service http://127.0.0.1:8787 ...
start "AI-Demo-Backend" cmd /k "cd /d %~dp0backend && python agent_reach_bridge.py"
timeout /t 3 >nul

echo Starting frontend and opening browser http://localhost:8000 ...
start "" "http://localhost:8000"
cd /d "%~dp0"
python -m http.server 8000 --bind 127.0.0.1 -d frontend
pause
