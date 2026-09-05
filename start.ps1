# Start Project AI with one command: infrastructure + backend (8010) + frontend (3010).
#   .\start.ps1            - start everything and open the browser
#   .\start.ps1 -NoBrowser - start without opening the browser
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Test-PortBusy([int]$Port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host "[1/4] Infrastructure (Postgres 5432, Neo4j 7474/7687, Qdrant 6333)..." -ForegroundColor Cyan
docker compose -f "$root\docker-compose.yml" up -d

# --- first-run bootstrap ---
if (-not (Test-Path "$root\backend\.venv\Scripts\python.exe")) {
    Write-Host "[bootstrap] Creating the venv and installing backend dependencies..." -ForegroundColor Yellow
    py -3.13 -m venv "$root\backend\.venv"
    & "$root\backend\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
    & "$root\backend\.venv\Scripts\python.exe" -m pip install -q -r "$root\backend\requirements.txt"
}
if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "[bootstrap] Installing frontend dependencies..." -ForegroundColor Yellow
    Push-Location "$root\frontend"
    npm install
    Pop-Location
}
if (-not (Test-Path "$root\.env")) {
    Write-Host "ERROR: no .env found - copy .env.example to .env and fill in the secrets." -ForegroundColor Red
    exit 1
}

Write-Host "[2/4] Backend -> http://localhost:8010" -ForegroundColor Cyan
if (Test-PortBusy 8010) {
    Write-Host "  port 8010 is busy - the backend is already running, skipping" -ForegroundColor DarkGray
} else {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "`$host.UI.RawUI.WindowTitle='Project AI - backend (8010)'; Set-Location '$root\backend'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8010"
    )
}

Write-Host "[3/4] Frontend -> http://localhost:3010" -ForegroundColor Cyan
if (Test-PortBusy 3010) {
    Write-Host "  port 3010 is busy - the frontend is already running, skipping" -ForegroundColor DarkGray
} else {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "`$host.UI.RawUI.WindowTitle='Project AI - frontend (3010)'; Set-Location '$root\frontend'; npm run dev"
    )
}

Write-Host "[4/4] Done." -ForegroundColor Green
if (-not $NoBrowser) {
    Start-Sleep -Seconds 3
    Start-Process "http://localhost:3010"
}
Write-Host "The backend and frontend run in separate windows - close a window to stop that service."
