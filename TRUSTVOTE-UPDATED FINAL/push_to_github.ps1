# TrustVote - Automated GitHub Deployment Script (PowerShell)
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  TRUSTVOTE - STATE ELECTION COMMISSION MAHARASHTRA" -ForegroundColor Green
Write-Host "  AUTOMATED GITHUB REPOSITORY DEPLOYMENT" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# Check Git installation
$gitPath = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitPath) {
    # Check standard install locations
    $possiblePaths = @(
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\bin\git.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\git.exe"
    )
    foreach ($p in $possiblePaths) {
        if (Test-Path $p) {
            $env:Path += ";$(Split-Path $p)"
            $gitPath = $p
            break
        }
    }
}

if (-not $gitPath) {
    Write-Host "[ERROR] Git is not installed on this system." -ForegroundColor Red
    Write-Host "Please download and install Git for Windows from: https://git-scm.com/download/win" -ForegroundColor Yellow
    Write-Host "After installation completes, re-run this script."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[1/5] Initializing Git repository..." -ForegroundColor Cyan
git init

Write-Host "`n[2/5] Staging project files..." -ForegroundColor Cyan
git add .

Write-Host "`n[3/5] Creating commit..." -ForegroundColor Cyan
git commit -m "SEC Maharashtra TrustVote: Immutable Blockchain Ledger, Maharashtra Map Telemetry, and Biometric Voting System"

Write-Host "`n[4/5] Setting default branch to main..." -ForegroundColor Cyan
git branch -M main

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  ENTER YOUR GITHUB REPOSITORY LINK:" -ForegroundColor Yellow
Write-Host "  Example: https://github.com/your-username/trustvote.git" -ForegroundColor Gray
Write-Host "========================================================" -ForegroundColor Cyan
$repoUrl = Read-Host "Repository URL"

if ([string]::IsNullOrWhiteSpace($repoUrl)) {
    Write-Host "[ERROR] No repository URL entered. Aborting." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`n[5/5] Linking remote repository and pushing..." -ForegroundColor Cyan
git remote remove origin 2>$null
git remote add origin $repoUrl
git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n========================================================" -ForegroundColor Green
    Write-Host "  [SUCCESS] Successfully pushed to GitHub!" -ForegroundColor Green
    Write-Host "  Your repository is live at: $repoUrl" -ForegroundColor Yellow
    Write-Host "========================================================" -ForegroundColor Green
} else {
    Write-Host "`n[NOTICE] If prompted by GitHub, sign in using your browser or personal access token." -ForegroundColor Yellow
}

Read-Host "`nPress Enter to exit"
