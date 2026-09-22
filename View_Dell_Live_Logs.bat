@echo off
title BudgetBy Live Console Stream (Dell Server)
color 0B
cd /d "%~dp0"

echo ================================================================
echo           BUDGETBY LIVE REMOTE CONSOLE (DELL SERVER)
echo ================================================================
echo  * Target Services : Deal Engine ^& Sync Watcher
echo  * Data Flow       : Direct Home Wi-Fi (Zero Supabase Egress)
echo  * On-Demand Mode  : Streaming ONLY while this window is open
echo ================================================================
echo.

python scripts\stream_remote_logs.py

echo.
pause
