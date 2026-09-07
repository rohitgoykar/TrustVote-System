@echo off
title TrustVote - Push to GitHub Repository
echo ========================================================
echo   TRUSTVOTE - STATE ELECTION COMMISSION MAHARASHTRA
echo   AUTOMATED GITHUB REPOSITORY DEPLOYMENT
echo ========================================================
echo.

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not found in your system PATH.
    echo Please install Git for Windows from: https://git-scm.com/download/win
    echo After installing Git, re-run this script.
    echo.
    pause
    exit /b 1
)

echo [1/5] Initializing Git repository...
git init

echo.
echo [2/5] Staging project files...
git add .

echo.
echo [3/5] Creating commit...
git commit -m "SEC Maharashtra TrustVote: Immutable Blockchain Ledger, Maharashtra Map Telemetry, and Biometric Voting System"

echo.
echo [4/5] Setting default branch to main...
git branch -M main

echo.
echo ========================================================
echo   ENTER YOUR GITHUB REPOSITORY LINK:
echo   Example: https://github.com/your-username/trustvote.git
echo ========================================================
set /p REPO_URL="Repository URL: "

if "%REPO_URL%"=="" (
    echo [ERROR] No repository URL entered. Aborting.
    pause
    exit /b 1
)

echo.
echo [5/5] Linking remote repository and pushing...
git remote remove origin >nul 2>nul
git remote add origin %REPO_URL%
git push -u origin main

echo.
if %errorlevel% equ 0 (
    echo ========================================================
    echo   [SUCCESS] Successfully pushed to GitHub!
    echo   Your repository is live at: %REPO_URL%
    echo ========================================================
) else (
    echo ========================================================
    echo   [NOTICE] If asked, please enter your GitHub Personal Access Token
    echo   or login via GitHub CLI.
    echo ========================================================
)
echo.
pause
