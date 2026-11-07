@echo off
setlocal
cd /d "%~dp0"

echo ==============================================================================
echo [Kronos] Launching 24/7 Standalone Trading Engine...
echo ==============================================================================

:: Check if port 7070 is already active
netstat -ano | findstr ":7070" | findstr "LISTENING" >nul
if %errorlevel% == 0 (
    echo [Kronos] System is ALREADY RUNNING on http://localhost:7070
    echo [Kronos] Opening browser dashboard...
    start http://localhost:7070
    goto :eof
)

:: Create logs directory if it does not exist
if not exist logs mkdir logs

echo [Kronos] Spawning supervisor watchdog in background...
start "Kronos 24/7 Trading Engine" /min python scripts\standalone_daemon.py

:: Wait up to 10 seconds for port 7070 to come online
echo [Kronos] Awaiting socket initialization...
set /a attempts=0
:WAIT_LOOP
timeout /t 1 /nobreak >nul
set /a attempts+=1
netstat -ano | findstr ":7070" | findstr "LISTENING" >nul
if %errorlevel% == 0 (
    echo [Kronos] SUCCESS! Server active on http://localhost:7070
    echo [Kronos] Live logs: logs\kronos_standalone.log
    start http://localhost:7070
    goto :eof
)
if %attempts% lss 10 goto :WAIT_LOOP

echo [Kronos] WARNING: Server startup is taking longer than expected.
echo [Kronos] Please check logs\kronos_standalone.log for details.
pause
