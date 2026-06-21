# Lawiot

## Запуск тестов локально

Тесты используют Postgres (см. `DATABASE_URL` в `.env` → `localhost:5433`,
контейнер `lawiot-db` из `docker-compose.yml`). **Если контейнер БД не поднят,
`pytest` зависает** на подключении к базе.

### Через хелпер (рекомендуется)

```powershell
.\run-tests.ps1
```

Скрипт сам поднимает контейнер `lawiot-db`, ждёт готовности Postgres и
запускает `pytest`. Любые аргументы передаются в `pytest` напрямую:

```powershell
.\run-tests.ps1 -k discovery -x              # фильтр по имени, стоп на первом падении
.\run-tests.ps1 documents/tests/test_views.py # один файл
```

### Вручную

```powershell
docker compose up -d db                  # поднять Postgres (идемпотентно)
.venv\Scripts\python.exe -m pytest -q    # прогон
```

### Прочие проверки

```powershell
.venv\Scripts\python.exe -m ruff check .            # линтер
.venv\Scripts\python.exe manage.py check            # системные проверки Django
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run  # нет ли несозданных миграций
```
