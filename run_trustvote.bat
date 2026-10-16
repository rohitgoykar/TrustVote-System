@echo off
title TrustVote Electoral Management System (Port 5000)
cd /d "%~dp0"
echo ======================================================================
echo   Maharashtra State Election Commission - TrustVote System
echo ======================================================================
echo.
echo Starting TrustVote on http://127.0.0.1:5000 ...
echo.
set PORT=5000
python app.py
pause
