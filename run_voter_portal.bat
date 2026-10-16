@echo off
title First-Time Voter e-EPIC Download Portal (Port 5001)
cd /d "%~dp0"
echo ======================================================================
echo   State Election Commission / National Voter Services Portal
echo   FIRST-TIME VOTER e-EPIC CARD DOWNLOAD PORTAL (STANDALONE WEBSITE)
echo ======================================================================
echo.
echo Starting Voter Portal on http://127.0.0.1:5001 ...
echo.
set PORT=5001
python voter_portal_app.py
pause
