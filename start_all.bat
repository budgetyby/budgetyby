@echo off
title BudgetBy Master Launcher
color 0A
cd /d "%~dp0"

echo ================================================================
echo             BUDGETBY 24/7 COMPLETE SERVER LAUNCHER
echo ================================================================
echo  * Window 1: Autonomous Deal Engine (Live Console Stream)
echo  * Window 2: GitHub Auto-Sync Watcher (30s Polling)
echo ================================================================
echo.
echo Launching both services in independent windows...

start "BudgetBy Deal Engine" cmd /k "%~dp0start_bot.bat"
ping 127.0.0.1 -n 3 >nul
start "BudgetBy GitHub Auto-Sync" cmd /k "%~dp0start_sync_watcher.bat"

echo.
echo Both services launched successfully!
echo You can minimize these windows. Do not close them.
ping 127.0.0.1 -n 4 >nul
exit
