@echo off
title BudgetBy 24/7 Deal Engine ^& Telegram Bot
color 0B
cd /d "c:\budget-by"

echo ================================================================
echo           BUDGETBY 24/7 AUTONOMOUS DEAL ENGINE
echo ================================================================
echo  * Database : Mumbai Supabase (ap-south-1)
echo  * Scrapers : Amazon, Flipkart, Myntra, Ajio, Nykaa
echo  * Channels : Real-Time Telegram MTProto Listener
echo  * Power    : Windows Keep-Awake (Sleep Disabled)
echo  * Web UI   : http://localhost:5000
echo ================================================================
echo.
echo Starting bot daemon... (Keep this window open. Minimizing is fine!)
echo.

"C:\Users\jay\AppData\Local\Programs\Python\Python311\python.exe" run_local_daemon.py

echo.
echo Daemon stopped.
pause
