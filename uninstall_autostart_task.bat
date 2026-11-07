@echo off
setlocal

echo ==============================================================================
echo [Kronos] Removing 24/7 Auto-Start Scheduled Task
echo ==============================================================================

set TASK_NAME=Kronos247TradingBot

schtasks /delete /tn "%TASK_NAME%" /f

if %errorlevel% == 0 (
    echo [Kronos] Task '%TASK_NAME%' has been removed successfully.
) else (
    echo [Kronos] Task '%TASK_NAME%' was not found or could not be removed.
)

pause
