@echo off
title Start TrustVote & Voter Download Portal
cd /d "%~dp0"
echo Starting TrustVote Election System (Port 5000)...
start "TrustVote System (Port 5000)" cmd /k "run_trustvote.bat"

timeout /t 2 /nobreak >nul

echo Starting First-Time Voter e-EPIC Download Portal (Port 5001)...
start "Voter e-EPIC Portal (Port 5001)" cmd /k "run_voter_portal.bat"

echo.
echo Both websites started:
echo 1. TrustVote System: http://127.0.0.1:5000
echo 2. First-Time Voter Download Portal: http://127.0.0.1:5001
echo.
