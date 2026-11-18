@echo off
setlocal
cd /d "%~dp0\.."

echo ==============================================================================
echo [Kronos] Installing Autonomous Daily System Hygiene Scheduled Task in Windows
echo ==============================================================================

set TASK_NAME=KronosDailyHygiene
set PYTHON_EXE=python
set SCRIPT_PATH=%~dp0system_hygiene.py

echo [Kronos] Registering scheduled task '%TASK_NAME%' to run daily at 03:00 AM...
schtasks /create /tn "%TASK_NAME%" /tr "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\" --quiet" /sc daily /st 03:00 /rl highest /f

if %errorlevel% == 0 (
    echo ==============================================================================
    echo [Kronos] SUCCESS! Task '%TASK_NAME%' installed.
    echo [Kronos] Windows will autonomously clean dead buffers, rotate logs, and vacuum
    echo [Kronos] databases every day at 03:00 AM.
    echo ==============================================================================
) else (
    echo [Kronos] Note: If task creation failed, ensure this script is run as Administrator.
)

pause
