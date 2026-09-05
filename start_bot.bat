@echo off
title BudgetBy 24/7 Deal Engine ^& Telegram Bot
color 0B
cd /d "c:\Users\jaysi\.gemini\antigravity\scratch\budget-by"

echo ================================================================
echo           BUDGETBY 24/7 AUTONOMOUS DEAL ENGINE
echo ================================================================
echo  * Database : Mumbai Supabase (ap-south-1)
echo  * Scrapers : Amazon, Flipkart, Myntra, Ajio, Nykaa
echo  * Channels : Real-Time Telegram MTProto Listener
echo  * Power    : Windows Keep-Awake (Sleep Disabled)
echo ================================================================
echo.
echo Starting bot daemon... (Keep this window open to run 24/7)
echo.

"C:\Program Files\Python311\python.exe" run_local_daemon.py

echo.
echo Daemon stopped.
pause
