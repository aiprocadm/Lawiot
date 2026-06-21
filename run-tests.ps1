<#
.SYNOPSIS
    Локальный прогон тестов: поднимает контейнер Postgres и запускает pytest.

.DESCRIPTION
    Тесты ходят в Postgres (DATABASE_URL → localhost:5433, контейнер lawiot-db).
    Если контейнер не поднят, pytest зависает на подключении к БД. Скрипт
    гарантирует готовность БД («барьер»), затем запускает pytest из .venv.

    Любые аргументы передаются в pytest без изменений.

.EXAMPLE
    .\run-tests.ps1
    Прогнать весь набор.

.EXAMPLE
    .\run-tests.ps1 -k discovery -x
    Только тесты с «discovery» в имени, остановиться на первом падении.

.EXAMPLE
    .\run-tests.ps1 documents/tests/test_views.py
    Один файл.
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = 'Stop'

# Корень репозитория = папка со скриптом (работает из любого CWD).
$repoRoot = $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Error "Не найден venv: $python. Создайте окружение и установите requirements.txt."
    exit 1
}

# 1. Поднять контейнер БД (идемпотентно — no-op, если уже запущен).
Write-Host '==> Поднимаю контейнер Postgres (lawiot-db)...' -ForegroundColor Cyan
& docker compose up -d db
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Не удалось поднять контейнер db. Запущен ли Docker Desktop?'
    exit 1
}

# 2. Барьер готовности: ждём, пока Postgres начнёт принимать подключения.
Write-Host '==> Жду готовности Postgres...' -ForegroundColor Cyan
$ready = $false
foreach ($attempt in 1..30) {
    & docker exec lawiot-db pg_isready -U lawiot *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Write-Error 'Postgres не стал доступен за 60 секунд. Проверьте: docker logs lawiot-db'
    exit 1
}
Write-Host '==> БД готова. Запускаю pytest.' -ForegroundColor Green

# 3. Прогон тестов. Аргументы скрипта прозрачно уходят в pytest.
& $python -m pytest @PytestArgs
exit $LASTEXITCODE
