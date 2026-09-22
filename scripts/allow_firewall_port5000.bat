@echo off
title BudgetBy - Allow Port 5000 Firewall Rule
color 0E

echo ================================================================
echo     ALLOW BUDGETBY LOCAL NETWORK ACCESS (PORT 5000)
echo ================================================================
echo  This script opens inbound port 5000 on private home networks
echo  so your main laptop can stream logs directly from this server.
echo ================================================================
echo.

netsh advfirewall firewall add rule name="BudgetBy Dashboard (Port 5000)" dir=in action=allow protocol=TCP localport=5000 profile=private,domain

echo.
echo ================================================================
echo Done! Port 5000 is now accessible on your private home network.
echo ================================================================
pause
