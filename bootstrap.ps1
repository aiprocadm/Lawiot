<#
.SYNOPSIS
    Провижининг окружения для свежего checkout/worktree: venv + зависимости + .env.

.DESCRIPTION
    На чистой машине (или в новом git-worktree) проект не запускается: нет `.venv`
    и нет `.env` (оба в .gitignore). Скрипт делает разовую подготовку идемпотентно:

      1. Находит Python 3.13 (проект закреплён на py313: torch/sentence-transformers
         тянут wheels именно под эту версию — см. requirements.txt / pyproject.toml).
      2. Создаёт `.venv` (если ещё нет).
      3. Ставит зависимости из requirements.txt.
      4. Создаёт `.env` из `.env.example` (если ещё нет) — годен для локальной
         разработки (DEBUG=True, БД на localhost:5433).

    После прогона: `.\run-tests.ps1` поднимет Postgres и запустит тесты.

.EXAMPLE
    .\bootstrap.ps1
    Полная подготовка окружения с нуля.

.EXAMPLE
    .\bootstrap.ps1 -Recreate
    Удалить существующий .venv и пересоздать его с нуля.
#>
[CmdletBinding()]
param(
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'

# Корень репозитория = папка со скриптом (работает из любого CWD).
$repoRoot = $PSScriptRoot
$venvDir = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

# 1. Найти Python 3.13. Предпочитаем py-launcher (`py -3.13`); если его нет —
#    пробуем `python`, но только если это действительно 3.13.
Write-Host '==> Ищу Python 3.13...' -ForegroundColor Cyan
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
$pythonCmd = $null
$pythonArgs = @()
if ($pyLauncher) {
    & py -3.13 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $pythonCmd = 'py'
        $pythonArgs = @('-3.13')
    }
}
if (-not $pythonCmd) {
    $bare = Get-Command python -ErrorAction SilentlyContinue
    if ($bare -and ((& python --version 2>&1) -match '3\.13\.')) {
        $pythonCmd = 'python'
    }
}
if (-not $pythonCmd) {
    Write-Error @'
Не найден Python 3.13. Установите его (python.org) или через py-launcher.
Проект закреплён на 3.13: torch/sentence-transformers публикуют wheels под эту
версию; на 3.14 установка зависимостей, скорее всего, упадёт.
'@
    exit 1
}
Write-Host ("==> Использую: {0} {1}" -f $pythonCmd, ($pythonArgs -join ' ')) -ForegroundColor Green

# 2. Создать venv (идемпотентно; -Recreate пересоздаёт).
if ($Recreate -and (Test-Path $venvDir)) {
    Write-Host '==> Удаляю существующий .venv (-Recreate)...' -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDir
}
if (-not (Test-Path $venvPython)) {
    Write-Host '==> Создаю .venv...' -ForegroundColor Cyan
    & $pythonCmd @pythonArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Error 'Не удалось создать .venv.'; exit 1 }
} else {
    Write-Host '==> .venv уже существует — пропускаю создание.' -ForegroundColor DarkGray
}

# 3. Установить зависимости. Обновляем pip, затем requirements.txt.
Write-Host '==> Обновляю pip...' -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Error 'Не удалось обновить pip.'; exit 1 }

Write-Host '==> Ставлю зависимости (requirements.txt; тянет torch — может быть долго)...' -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $repoRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Write-Error 'Установка зависимостей упала.'; exit 1 }

# 4. Создать .env из примера (если ещё нет). НЕ перезаписываем существующий.
$envFile = Join-Path $repoRoot '.env'
$envExample = Join-Path $repoRoot '.env.example'
if (-not (Test-Path $envFile)) {
    Write-Host '==> Создаю .env из .env.example (локальный dev-конфиг)...' -ForegroundColor Cyan
    Copy-Item $envExample $envFile
} else {
    Write-Host '==> .env уже существует — не трогаю.' -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '==> Готово. Дальше:' -ForegroundColor Green
Write-Host '    .\run-tests.ps1            # поднять Postgres и прогнать тесты' -ForegroundColor Gray
Write-Host '    .venv\Scripts\python.exe manage.py runserver   # локальный сервер' -ForegroundColor Gray
