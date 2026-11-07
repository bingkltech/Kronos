@echo off
setlocal
cd /d "%~dp0"

echo ==============================================================================
echo [Kronos] Installing 24/7 Auto-Start Scheduled Task in Windows
echo ==============================================================================

:: Register Scheduled Task in Windows Task Scheduler
set TASK_NAME=Kronos247TradingBot
set SCRIPT_PATH=%~dp0start_standalone.bat

echo [Kronos] Registering task '%TASK_NAME%' to run on user logon...
schtasks /create /tn "%TASK_NAME%" /tr "\"%SCRIPT_PATH%\"" /sc onlogon /rl highest /f

if %errorlevel% == 0 (
    echo ==============================================================================
    echo [Kronos] SUCCESS! Task '%TASK_NAME%' has been installed.
    echo [Kronos] Kronos will now automatically start on every Windows boot / login.
    echo [Kronos] To remove this autostart, run uninstall_autostart_task.bat
    echo ==============================================================================
) else (
    echo [Kronos] Failed to create scheduled task. Please run this batch file as Administrator.
)

pause
