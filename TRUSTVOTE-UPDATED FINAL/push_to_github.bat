@echo off
title TrustVote - Push to GitHub Repository
echo ========================================================
echo   TRUSTVOTE - STATE ELECTION COMMISSION MAHARASHTRA
echo   AUTOMATED GITHUB REPOSITORY DEPLOYMENT
echo ========================================================
echo.

set "GIT_CMD=git"
where git >nul 2>nul
if %errorlevel% neq 0 (
    if exist "C:\Program Files\Git\cmd\git.exe" (
        set "GIT_CMD=C:\Program Files\Git\cmd\git.exe"
    ) else if exist "C:\Program Files\Git\bin\git.exe" (
        set "GIT_CMD=C:\Program Files\Git\bin\git.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" (
        set "GIT_CMD=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
    ) else (
        echo [ERROR] Git is not found on your system.
        echo Please install Git for Windows from: https://git-scm.com/download/win
        echo.
        pause
        exit /b 1
    )
)

echo [1/5] Initializing Git repository...
"%GIT_CMD%" init


echo.
echo [2/5] Staging project files...
"%GIT_CMD%" add .

echo.
echo [3/5] Creating commit...
"%GIT_CMD%" commit -m "TrustVote Release: Fixed config imports, optimized Render cloud deployment, 2FA SMS OTP and WAL database"

echo.
echo [4/5] Setting default branch to main...
"%GIT_CMD%" branch -M main

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
"%GIT_CMD%" remote remove origin >nul 2>nul
"%GIT_CMD%" remote add origin %REPO_URL%
"%GIT_CMD%" push -u origin main --force

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
