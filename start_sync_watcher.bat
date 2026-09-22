@echo off
title BudgetBy Automatic GitHub Sync Watcher
color 0E
cd /d "c:\budget-by"

echo ================================================================
echo           BUDGETBY AUTOMATIC GITHUB SYNC WATCHER
echo ================================================================
echo  * Poll Interval : 30 Seconds
echo  * Remote Branch : origin/main
echo  * Action        : Auto-Pull ^& Graceful Daemon Restart
echo ================================================================
echo.

"C:\Users\jay\AppData\Local\Programs\Python\Python311\python.exe" scripts\auto_sync_runner.py

pause
