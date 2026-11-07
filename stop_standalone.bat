@echo off
setlocal
cd /d "%~dp0"

echo ==============================================================================
echo [Kronos] Stopping 24/7 Standalone Trading Engine...
echo ==============================================================================

:: Check PID file first
if exist data\kronos.pid (
    for /f "tokens=1,2 delims=:" %%a in (data\kronos.pid) do (
        echo [Kronos] Stopping Child PID %%b...
        taskkill /PID %%b /F >nul 2>&1
        echo [Kronos] Stopping Supervisor PID %%a...
        taskkill /PID %%a /F >nul 2>&1
    )
    del data\kronos.pid >nul 2>&1
)

:: Terminate any remaining process listening on port 7070
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":7070" ^| findstr "LISTENING"') do (
    echo [Kronos] Releasing socket: Terminating lingering PID %%p...
    taskkill /PID %%p /F >nul 2>&1
)

timeout /t 1 /nobreak >nul
netstat -ano | findstr ":7070" | findstr "LISTENING" >nul
if %errorlevel% neq 0 (
    echo [Kronos] Engine successfully stopped. Standby complete.
) else (
    echo [Kronos] WARNING: Port 7070 may still be active. Please check Task Manager.
)
timeout /t 2 /nobreak >nul
