# Запуск «Проекты ИИ» одной командой: инфраструктура + бэкенд (8010) + фронтенд (3010).
#   .\start.ps1            — запустить всё и открыть браузер
#   .\start.ps1 -NoBrowser — без открытия браузера
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Test-PortBusy([int]$Port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host "[1/4] Инфраструктура (Postgres 5432, Neo4j 7474/7687, Qdrant 6333)…" -ForegroundColor Cyan
docker compose -f "$root\docker-compose.yml" up -d

# --- бутстрап при первом запуске ---
if (-not (Test-Path "$root\backend\.venv\Scripts\python.exe")) {
    Write-Host "[бутстрап] Создаю venv и ставлю зависимости бэкенда…" -ForegroundColor Yellow
    py -3.13 -m venv "$root\backend\.venv"
    & "$root\backend\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
    & "$root\backend\.venv\Scripts\python.exe" -m pip install -q -r "$root\backend\requirements.txt"
}
if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "[бутстрап] Ставлю зависимости фронтенда…" -ForegroundColor Yellow
    Push-Location "$root\frontend"
    npm install
    Pop-Location
}
if (-not (Test-Path "$root\.env")) {
    Write-Host "ВНИМАНИЕ: нет .env — скопируй .env.example в .env и заполни секреты." -ForegroundColor Red
    exit 1
}

Write-Host "[2/4] Бэкенд → http://localhost:8010" -ForegroundColor Cyan
if (Test-PortBusy 8010) {
    Write-Host "  порт 8010 занят — бэкенд уже запущен, пропускаю" -ForegroundColor DarkGray
} else {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "`$host.UI.RawUI.WindowTitle='Проекты ИИ — бэкенд (8010)'; Set-Location '$root\backend'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8010"
    )
}

Write-Host "[3/4] Фронтенд → http://localhost:3010" -ForegroundColor Cyan
if (Test-PortBusy 3010) {
    Write-Host "  порт 3010 занят — фронтенд уже запущен, пропускаю" -ForegroundColor DarkGray
} else {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "`$host.UI.RawUI.WindowTitle='Проекты ИИ — фронтенд (3010)'; Set-Location '$root\frontend'; npm run dev"
    )
}

Write-Host "[4/4] Готово." -ForegroundColor Green
if (-not $NoBrowser) {
    Start-Sleep -Seconds 3
    Start-Process "http://localhost:3010"
}
Write-Host "Бэкенд и фронтенд работают в отдельных окнах — закрой окно, чтобы остановить сервис."
