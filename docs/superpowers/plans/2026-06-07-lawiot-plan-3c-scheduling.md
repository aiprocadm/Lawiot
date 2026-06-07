# Plan 3c — Scheduling & change-detection (django-q2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Periodically sweep a curator-managed seed-list of acts, re-fetch each from its official source, and create review drafts for anything that changed — running the whole stack (web + worker + db) under `docker compose up`.

**Architecture:** 3c is a thin orchestration layer over the existing 3a pipeline. The seed-list is represented by documents flagged `Document.auto_ingest=True` with a non-empty `source_url` (no new model). A pure-ish `sweep_targets()` service iterates those documents and calls the existing `ingest_target()` per target — which already does fetch → hash → change-detect → **draft** (never auto-publishes), with per-target failure isolation and quarantine. `django-q2` (broker = Postgres, no Redis) runs `ingestion.scheduling.run_sweep` on a daily cron `Schedule`. The app is containerized (Dockerfile + `web` + `qcluster` compose services).

**Tech Stack:** Django 5.2, PostgreSQL 16, `django-q2` (ORM broker), `croniter` (cron schedules), `gunicorn` + `whitenoise` (containerized web), `httpx` (existing fetcher), `pytest`/`pytest-django`.

---

## Context & references

- Spec: `docs/superpowers/specs/2026-06-05-lawiot-design.md` — §6 (Расписание), §11 (компоненты/деплой), §16 п.8 (this plan).
- Prior plans: `docs/superpowers/plans/2026-06-06-lawiot-plan-3a-ingestion-core.md` (the `ingest_target` pipeline 3c orchestrates), `…-3b-link-extraction.md`.
- Key existing code to reuse (do **not** reimplement):
  - `ingestion/services.py` → `IngestionTarget(document, url, target_key)`, `ingest_target(target, *, client=None) -> IngestionJob`. Already isolates failures into a `FAILED` job and retains `RawSource` (quarantine); already `SKIPPED` on unchanged hash; already creates **drafts** only.
  - `ingestion/fetching.py` → `fetch(url, *, client=None)`, constants `DEFAULT_TIMEOUT`, `MAX_RETRIES`, `USER_AGENT`.
  - `documents/models.py` → `Document` (has `source_url`, `slug`, `status`).
  - Test patterns: `ingestion/tests/test_services.py` (httpx `MockTransport`, `_client_returning`), `documents/tests/factories.py` (`make_document(**kwargs)`), `ingestion/tests/test_commands.py` (`call_command`).

## Design decisions (locked in brainstorming, 2026-06-07)

- **Seed-list = `Document.auto_ingest` + `source_url`** (reuse, no new model). `target_key = doc.slug` — same convention as the `ingest_url` command, so auto- and manual-ingest of one document share change-detection history.
- **Full containerization now**: Dockerfile + `web` (gunicorn+whitenoise) + `qcluster` services, plus the existing `db`.
- **Cron schedule** via `croniter` (configurable `SWEEP_CRON`, default `0 3 * * *`) rather than `Schedule.DAILY`, for flexibility.
- **Not in 3c** (boundaries): populating the real labor-law corpus + live acceptance against `pravo.gov.ru` (spec §16 п.10); curation polish / review-queue / draft↔current diff (3d); change *notifications* (out of v1, spec §3).

## Prerequisites (every task)

- DB container up: `docker compose up -d db` (host port 5433; see `windows-python-env` memory).
- Use the venv interpreter explicitly (bare `python` hangs on this machine): `.venv\Scripts\python.exe`.
- Run tests/lint **over the whole repo** (no path filter) at verification points — first-party apps are `accounts`, `documents`, `ingestion`, `search` (see `lawiot-lint-scope` memory). Baseline before this plan: **78 tests green**.

## File structure (created / modified)

| File | Responsibility |
|---|---|
| `documents/models.py` (modify) | Add `Document.auto_ingest` boolean (sweep opt-in). |
| `documents/migrations/0007_document_auto_ingest.py` (create, via makemigrations) | Schema migration for the flag. |
| `documents/admin.py` (modify) | Surface `auto_ingest` in the Document changelist (filter + inline-editable). |
| `documents/tests/test_models.py` (modify) | Test the flag default. |
| `ingestion/scheduling.py` (create) | `iter_targets()`, `SweepSummary`, `sweep_targets()`, `run_sweep()` — the orchestration layer. |
| `ingestion/management/commands/sweep_targets.py` (create) | Manual / cron entry point to run a sweep. |
| `ingestion/management/commands/ensure_sweep_schedule.py` (create) | Idempotent registration of the daily django-q2 `Schedule`. |
| `ingestion/tests/test_scheduling.py` (create) | Unit + integration tests for the above. |
| `requirements.txt` (modify) | `django-q2`, `croniter`, `gunicorn`, `whitenoise`. |
| `config/settings.py` (modify) | `django_q` app, `Q_CLUSTER` (ORM broker), `SWEEP_CRON`, whitenoise middleware, `STATIC_ROOT`. |
| `Dockerfile` (create) | App image. |
| `docker-compose.yml` (modify) | Add `web` + `qcluster` services. |
| `.env.example` (modify) | Document `SWEEP_CRON` and container env. |

---

## Task 1: `Document.auto_ingest` flag (model + migration + admin)

**Files:**
- Modify: `documents/models.py` (Document, after `source_url`)
- Create: `documents/migrations/0007_document_auto_ingest.py`
- Modify: `documents/admin.py` (DocumentAdmin)
- Test: `documents/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `documents/tests/test_models.py` (imports `make_document` are already at the top of that file; if not, add `from documents.tests.factories import make_document`):

```python
@pytest.mark.django_db
def test_document_auto_ingest_defaults_false():
    doc = make_document(slug="auto-flag", official_number="1")
    assert doc.auto_ingest is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_models.py::test_document_auto_ingest_defaults_false -v`
Expected: FAIL — `AttributeError: 'Document' object has no attribute 'auto_ingest'` (or a Django FieldError).

- [ ] **Step 3: Add the field**

In `documents/models.py`, add immediately after the `source_url` field of `Document`:

```python
    auto_ingest = models.BooleanField(
        default=False,
        help_text="Включить периодический авто-приём из source_url по расписанию.",
    )
```

- [ ] **Step 4: Generate the migration**

Run: `.venv\Scripts\python.exe manage.py makemigrations documents`
Expected: creates `documents/migrations/0007_document_auto_ingest.py`. Verify its content matches:

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0006_redaction_raw_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="auto_ingest",
            field=models.BooleanField(
                default=False,
                help_text="Включить периодический авто-приём из source_url по расписанию.",
            ),
        ),
    ]
```

- [ ] **Step 5: Surface the flag in admin**

In `documents/admin.py`, update `DocumentAdmin`:

```python
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "doc_type", "official_number", "status", "auto_ingest")
    list_filter = ("doc_type", "status", "auto_ingest")
    list_editable = ("auto_ingest",)
    search_fields = ("title", "official_number")
    prepopulated_fields = {"slug": ("official_number",)}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_models.py::test_document_auto_ingest_defaults_false -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add documents/models.py documents/migrations/0007_document_auto_ingest.py documents/admin.py documents/tests/test_models.py
git commit -m "feat(documents): auto_ingest flag on Document (sweep opt-in)"
```

---

## Task 2: `iter_targets()` — build sweep targets from flagged documents

**Files:**
- Create: `ingestion/scheduling.py`
- Test: `ingestion/tests/test_scheduling.py`

- [ ] **Step 1: Write the failing test**

Create `ingestion/tests/test_scheduling.py`:

```python
import pytest

from documents.tests.factories import make_document
from ingestion.scheduling import iter_targets


@pytest.mark.django_db
def test_iter_targets_selects_only_flagged_docs_with_source_url():
    make_document(
        slug="a", official_number="1", auto_ingest=True, source_url="https://e.test/a"
    )
    make_document(  # flagged but no URL → excluded
        slug="b", official_number="2", auto_ingest=True, source_url=""
    )
    make_document(  # has URL but not flagged → excluded
        slug="c", official_number="3", auto_ingest=False, source_url="https://e.test/c"
    )
    targets = list(iter_targets())
    assert len(targets) == 1
    t = targets[0]
    assert t.document.slug == "a"
    assert t.url == "https://e.test/a"
    assert t.target_key == "a"  # конвенция target_key = slug (как у ingest_url)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.scheduling'`.

- [ ] **Step 3: Create `iter_targets`**

Create `ingestion/scheduling.py`:

```python
from documents.models import Document
from ingestion.services import IngestionTarget


def iter_targets():
    """Цели авто-приёма: документы с флагом auto_ingest и непустым source_url.

    target_key = slug — та же конвенция, что у команды ingest_url, поэтому история
    обнаружения изменений (RawSource по target_key) общая для авто- и ручного приёма.
    """
    qs = Document.objects.filter(auto_ingest=True).exclude(source_url="")
    for document in qs.iterator():
        yield IngestionTarget(
            document=document,
            url=document.source_url,
            target_key=document.slug,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/scheduling.py ingestion/tests/test_scheduling.py
git commit -m "feat(ingestion): iter_targets — sweep targets from auto_ingest docs"
```

---

## Task 3: `sweep_targets()` + `SweepSummary` + `run_sweep()`

**Files:**
- Modify: `ingestion/scheduling.py`
- Test: `ingestion/tests/test_scheduling.py`

- [ ] **Step 1: Write the failing tests**

Append to `ingestion/tests/test_scheduling.py` (add the new imports to the existing import block at the top of the file):

```python
import httpx

from documents.models import Redaction
from ingestion.scheduling import run_sweep, sweep_targets

# HTML с маркером «Статья 1.» в UTF-8 — парсер 3a извлечёт одну статью → черновик.
HTML = "<p>Статья 1. Общие положения</p><p>текст</p>".encode("utf-8")


def _router(handler_by_path):
    def handler(request):
        return handler_by_path[request.url.path](request)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_sweep_creates_drafts_isolates_failures_and_counts():
    make_document(
        slug="ok", official_number="1", auto_ingest=True, source_url="https://e.test/ok"
    )
    make_document(
        slug="bad", official_number="2", auto_ingest=True, source_url="https://e.test/bad"
    )
    client = _router(
        {
            "/ok": lambda r: httpx.Response(
                200, headers={"content-type": "text/html"}, content=HTML
            ),
            "/bad": lambda r: httpx.Response(500, content=b"boom"),
        }
    )
    summary = sweep_targets(client=client)
    assert summary.total == 2
    assert summary.success == 1
    assert summary.failed == 1
    assert summary.skipped == 0
    assert Redaction.objects.filter(document__slug="ok").count() == 1   # черновик создан
    assert Redaction.objects.filter(document__slug="bad").count() == 0  # сбой изолирован


@pytest.mark.django_db
def test_sweep_skips_unchanged_on_second_run():
    make_document(
        slug="ok", official_number="1", auto_ingest=True, source_url="https://e.test/ok"
    )
    ok = {"/ok": lambda r: httpx.Response(
        200, headers={"content-type": "text/html"}, content=HTML
    )}
    first = sweep_targets(client=_router(ok))
    second = sweep_targets(client=_router(ok))
    assert first.success == 1
    assert second.success == 0
    assert second.skipped == 1


@pytest.mark.django_db
def test_sweep_continues_when_ingest_target_raises(monkeypatch):
    make_document(slug="a", official_number="1", auto_ingest=True, source_url="https://e.test/a")
    make_document(slug="b", official_number="2", auto_ingest=True, source_url="https://e.test/b")
    from ingestion import scheduling

    seen = []

    def boom(target, client=None):
        seen.append(target.target_key)
        raise RuntimeError("сбой уровня БД")

    monkeypatch.setattr(scheduling, "ingest_target", boom)
    summary = sweep_targets(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")))
    )
    assert summary.total == 2
    assert summary.failed == 2
    assert len(seen) == 2  # обход не прервался на первом исключении


@pytest.mark.django_db
def test_run_sweep_returns_summary_string():
    result = run_sweep()
    assert isinstance(result, str)
    assert "всего=" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_sweep'` / `'sweep_targets'` from `ingestion.scheduling`.

- [ ] **Step 3: Implement the sweep**

Replace the **entire contents** of `ingestion/scheduling.py` with the following — one import block at the top (no interleaved imports → avoids ruff E402); `iter_targets` from Task 2 is kept and the sweep is added:

```python
from dataclasses import dataclass

import httpx

from documents.models import Document
from ingestion.fetching import DEFAULT_TIMEOUT, MAX_RETRIES
from ingestion.models import IngestionJob
from ingestion.services import IngestionTarget, ingest_target


def iter_targets():
    """Цели авто-приёма: документы с флагом auto_ingest и непустым source_url.

    target_key = slug — та же конвенция, что у команды ingest_url, поэтому история
    обнаружения изменений (RawSource по target_key) общая для авто- и ручного приёма.
    """
    qs = Document.objects.filter(auto_ingest=True).exclude(source_url="")
    for document in qs.iterator():
        yield IngestionTarget(
            document=document,
            url=document.source_url,
            target_key=document.slug,
        )


@dataclass
class SweepSummary:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0

    def __str__(self):
        return (
            f"всего={self.total} успех={self.success} "
            f"пропущено={self.skipped} ошибок={self.failed}"
        )


_STATUS_FIELD = {
    IngestionJob.Status.SUCCESS: "success",
    IngestionJob.Status.SKIPPED: "skipped",
    IngestionJob.Status.FAILED: "failed",
}


def _new_client():
    # Один клиент на весь обход: переиспользование соединений (вежливость к источнику).
    # Параметры совпадают с ingestion.fetching.fetch; User-Agent добавляет сам fetch.
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        transport=httpx.HTTPTransport(retries=MAX_RETRIES),
        follow_redirects=True,
    )


def sweep_targets(*, client=None) -> SweepSummary:
    """Обойти все цели авто-приёма, для каждой вызвать ingest_target.

    Изоляция двойная: ingest_target сам ловит сетевые/парсинговые ошибки в FAILED-job,
    а внешний try/except ловит сбои уровня БД, чтобы один проблемный документ не оборвал
    весь обход. Возвращает агрегированную сводку.
    """
    summary = SweepSummary()
    owns_client = client is None
    client = client or _new_client()
    try:
        for target in iter_targets():
            summary.total += 1
            try:
                job = ingest_target(target, client=client)
                field = _STATUS_FIELD.get(job.status, "failed")
            except Exception:  # намеренная сетка: один сбойный документ не должен оборвать обход
                field = "failed"
            setattr(summary, field, getattr(summary, field) + 1)
    finally:
        if owns_client:
            client.close()
    return summary


def run_sweep() -> str:
    """Точка входа для планировщика django-q2 (func='ingestion.scheduling.run_sweep').

    Возвращает строку-сводку — django-q2 сохранит её в результате задачи (виден в admin).
    """
    return str(sweep_targets())
```

Note: this file fully supersedes the Task 2 version (same `iter_targets`, plus the sweep) — there should be exactly **one** import block at the top.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py -v`
Expected: PASS (5 tests in this file so far).

- [ ] **Step 5: Commit**

```bash
git add ingestion/scheduling.py ingestion/tests/test_scheduling.py
git commit -m "feat(ingestion): sweep_targets service + run_sweep task (isolated, summarized)"
```

---

## Task 4: `sweep_targets` management command

**Files:**
- Create: `ingestion/management/commands/sweep_targets.py`
- Test: `ingestion/tests/test_scheduling.py`

- [ ] **Step 1: Write the failing test**

Append to `ingestion/tests/test_scheduling.py` (add `from io import StringIO` and `from django.core.management import call_command` to the import block):

```python
@pytest.mark.django_db
def test_sweep_targets_command_reports_summary():
    out = StringIO()
    call_command("sweep_targets", stdout=out)  # без целей → нулевая сводка, без сети
    assert "Обход завершён" in out.getvalue()
    assert "всего=0" in out.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py::test_sweep_targets_command_reports_summary -v`
Expected: FAIL — `CommandError: Unknown command: 'sweep_targets'`.

- [ ] **Step 3: Create the command**

Create `ingestion/management/commands/sweep_targets.py`:

```python
from django.core.management.base import BaseCommand

from ingestion.scheduling import sweep_targets


class Command(BaseCommand):
    help = (
        "Обойти все цели авто-приёма (Document.auto_ingest + source_url): скачать, "
        "обнаружить изменения, создать черновики для изменившихся актов."
    )

    def handle(self, *args, **options):
        summary = sweep_targets()
        self.stdout.write(self.style.SUCCESS(f"Обход завершён: {summary}"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py::test_sweep_targets_command_reports_summary -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/management/commands/sweep_targets.py ingestion/tests/test_scheduling.py
git commit -m "feat(ingestion): sweep_targets management command"
```

---

## Task 5: Add dependencies (django-q2, croniter, gunicorn, whitenoise)

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt` (keep the existing lines; add a grouped block):

```
django-q2>=1.7
croniter>=2.0
gunicorn>=22.0
whitenoise>=6.6
```

- [ ] **Step 2: Install into the venv**

Run: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
Expected: installs `django-q2`, `croniter`, `gunicorn`, `whitenoise` (+ transitive deps) with no errors.

> If `django-q2>=1.7` reports an incompatibility with Django 5.2 / Python 3.13, bump to the newest published version and pin that exact line instead, then re-run. The rest of the plan is version-agnostic.

- [ ] **Step 3: Verify the app imports**

Run: `.venv\Scripts\python.exe -c "import django_q, croniter, whitenoise; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore(ingestion): add django-q2, croniter, gunicorn, whitenoise deps"
```

---

## Task 6: Wire django-q2 + whitenoise into settings

**Files:**
- Modify: `config/settings.py`
- Test: whole suite (regression) — adding `django_q` to INSTALLED_APPS pulls in its migrations.

- [ ] **Step 1: Register the app**

In `config/settings.py`, add `"django_q",` to `INSTALLED_APPS` immediately after `"django.contrib.postgres",` (third-party, before first-party apps):

```python
    "django.contrib.postgres",
    "django_q",
    "accounts",
```

- [ ] **Step 2: Add whitenoise middleware**

In `MIDDLEWARE`, insert whitenoise immediately after `SecurityMiddleware`:

```python
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
```

- [ ] **Step 3: Add STATIC_ROOT, SWEEP_CRON, and Q_CLUSTER**

In `config/settings.py`, add `STATIC_ROOT` right after the existing `STATICFILES_DIRS` line:

```python
STATIC_ROOT = BASE_DIR / "staticfiles"
```

Then append near the end of the file (after the `LOGIN_*` block):

```python
# --- Приём данных по расписанию (План 3c) ---------------------------------
# Cron-выражение ежедневного обхода целей авто-приёма. По умолчанию 03:00.
SWEEP_CRON = env("SWEEP_CRON", default="0 3 * * *")

# django-q2: брокер задач прямо в Postgres (без Redis).
Q_CLUSTER = {
    "name": "lawiot",
    "orm": "default",      # использовать БД Django как брокер
    "workers": 2,
    "timeout": 300,        # сек на задачу; должен быть < retry
    "retry": 660,          # сек до повторной выдачи «зависшей» задачи
    "max_attempts": 1,     # обход идемпотентен — не копим повторы при сбое
    "catch_up": False,     # не «отыгрывать» пропущенные прогоны после простоя
    "label": "Django Q",
}
```

- [ ] **Step 4: Verify the whole suite still passes (regression)**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: PASS — previous 78 + the new scheduling tests (≈85), no errors. (pytest-django applies `django_q`'s migrations to the test DB automatically.)

- [ ] **Step 5: Commit**

```bash
git add config/settings.py
git commit -m "feat(config): wire django-q2 (ORM broker) + whitenoise static"
```

---

## Task 7: `ensure_sweep_schedule` command (idempotent daily schedule)

**Files:**
- Create: `ingestion/management/commands/ensure_sweep_schedule.py`
- Test: `ingestion/tests/test_scheduling.py`

- [ ] **Step 1: Write the failing tests**

Append to `ingestion/tests/test_scheduling.py`:

```python
@pytest.mark.django_db
def test_ensure_sweep_schedule_is_idempotent():
    from django_q.models import Schedule

    call_command("ensure_sweep_schedule")
    call_command("ensure_sweep_schedule")  # повтор не создаёт дубль
    qs = Schedule.objects.filter(name="daily-sweep")
    assert qs.count() == 1
    sched = qs.get()
    assert sched.func == "ingestion.scheduling.run_sweep"
    assert sched.schedule_type == Schedule.CRON


@pytest.mark.django_db
def test_ensure_sweep_schedule_updates_cron(settings):
    from django_q.models import Schedule

    settings.SWEEP_CRON = "0 5 * * *"
    call_command("ensure_sweep_schedule")
    assert Schedule.objects.get(name="daily-sweep").cron == "0 5 * * *"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py -k ensure_sweep_schedule -v`
Expected: FAIL — `CommandError: Unknown command: 'ensure_sweep_schedule'`.

- [ ] **Step 3: Create the command**

Create `ingestion/management/commands/ensure_sweep_schedule.py`:

```python
from django.conf import settings
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Идемпотентно зарегистрировать/обновить ежедневное расписание обхода целей (django-q2)."

    SCHEDULE_NAME = "daily-sweep"

    def handle(self, *args, **options):
        schedule, created = Schedule.objects.update_or_create(
            name=self.SCHEDULE_NAME,
            defaults={
                "func": "ingestion.scheduling.run_sweep",
                "schedule_type": Schedule.CRON,
                "cron": settings.SWEEP_CRON,
                "repeats": -1,  # бесконечно
            },
        )
        verb = "создано" if created else "обновлено"
        self.stdout.write(
            self.style.SUCCESS(
                f"Расписание «{schedule.name}» {verb}: func={schedule.func}, cron={schedule.cron}"
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_scheduling.py -k ensure_sweep_schedule -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/management/commands/ensure_sweep_schedule.py ingestion/tests/test_scheduling.py
git commit -m "feat(ingestion): ensure_sweep_schedule command (idempotent daily schedule)"
```

---

## Task 8: Dockerfile (app image)

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore`**

Create `.dockerignore`:

```
.git
.venv
__pycache__
*.pyc
db.sqlite3
staticfiles
.env
docs
```

- [ ] **Step 2: Create the Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# psycopg[binary] ships wheels — no system build deps needed on slim.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Per-service command is set in docker-compose.yml (web vs qcluster).
```

- [ ] **Step 3: Verify the image builds**

Run: `docker build -t lawiot-app .`
Expected: build succeeds, ending with `naming to docker.io/library/lawiot-app`. (First build downloads the base image + deps; may take a few minutes.)

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "build(docker): app image (Dockerfile + .dockerignore)"
```

---

## Task 9: docker-compose `web` + `qcluster` services

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the services**

Edit `docker-compose.yml` to add `web` and `qcluster` under `services:` (keep the existing `db` service and the `volumes:` block unchanged):

```yaml
  web:
    build: .
    container_name: lawiot-web
    command: >
      sh -c "python manage.py migrate --noinput &&
             python manage.py collectstatic --noinput &&
             gunicorn config.wsgi:application --bind 0.0.0.0:8000"
    environment:
      DATABASE_URL: postgres://lawiot:lawiot@db:5432/lawiot
      SECRET_KEY: ${SECRET_KEY:-dev-insecure-key-change-me}
      DEBUG: ${DEBUG:-False}
      ALLOWED_HOSTS: ${ALLOWED_HOSTS:-localhost,127.0.0.1,web}
      SWEEP_CRON: ${SWEEP_CRON:-0 3 * * *}
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      # «Здоров», когда миграции применены — это и есть барьер для qcluster ниже.
      test: ["CMD-SHELL", "python manage.py migrate --check"]
      interval: 10s
      timeout: 10s
      retries: 12
      start_period: 20s
    restart: unless-stopped

  qcluster:
    build: .
    container_name: lawiot-qcluster
    command: >
      sh -c "python manage.py ensure_sweep_schedule &&
             python manage.py qcluster"
    environment:
      DATABASE_URL: postgres://lawiot:lawiot@db:5432/lawiot
      SECRET_KEY: ${SECRET_KEY:-dev-insecure-key-change-me}
      DEBUG: ${DEBUG:-False}
      ALLOWED_HOSTS: ${ALLOWED_HOSTS:-localhost,127.0.0.1,web}
      SWEEP_CRON: ${SWEEP_CRON:-0 3 * * *}
    depends_on:
      db:
        condition: service_healthy
      web:
        condition: service_healthy   # дождаться миграций, потом ставить расписание
    restart: unless-stopped
```

- [ ] **Step 2: Validate compose config**

Run: `docker compose config`
Expected: prints the fully-resolved compose file with `db`, `web`, `qcluster` and no errors.

- [ ] **Step 3: Boot the full stack (infra acceptance — no live ingestion)**

Run:
```bash
docker compose up -d --build
docker compose ps
```
Expected: `db` healthy, `web` healthy (after migrations), `qcluster` running (state `Up`).

- [ ] **Step 4: Confirm the schedule was registered and the app is healthy**

Run:
```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py shell -c "from django_q.models import Schedule; print(Schedule.objects.filter(name='daily-sweep').values_list('func','cron'))"
```
Expected: `check` → `System check identified no issues`; the shell prints `[('ingestion.scheduling.run_sweep', '0 3 * * *')]`.

- [ ] **Step 5: Tear down**

Run: `docker compose down`
Expected: containers stopped and removed; `lawiot_pgdata` volume retained.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "build(docker): web + qcluster compose services"
```

---

## Task 10: Document container env in `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Extend `.env.example`**

Replace `.env.example` with:

```
SECRET_KEY=dev-insecure-key-change-me
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
# venv-dev: PostgreSQL в контейнере на порту 5433 (см. docker-compose.yml).
# Сервисы web/qcluster в compose переопределяют это на db:5432 (внутренняя сеть).
DATABASE_URL=postgres://lawiot:lawiot@localhost:5433/lawiot
# План 3c: cron ежедневного обхода целей авто-приёма (по умолчанию 03:00).
SWEEP_CRON=0 3 * * *
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): document SWEEP_CRON and container database URL"
```

---

## Task 11: Final whole-repo verification

**Files:** none (verification only).

- [ ] **Step 1: Lint the whole repo (path-less)**

Run: `.venv\Scripts\python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 2: Run the whole test suite (path-less)**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: all green — 78 baseline + 9 new (1 in `test_models.py`, 8 in `test_scheduling.py`) = **87**, 0 failures.

- [ ] **Step 3: Confirm no stray migrations / model drift**

Run: `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 4 (optional): open the PR**

Only when the user asks to push/PR:
```bash
git push -u origin feature/lawiot-plan-3c-scheduling
gh pr create --base main --title "feat(ingestion): Plan 3c — scheduling & change-detection (django-q2)" --body "Implements docs/superpowers/plans/2026-06-07-lawiot-plan-3c-scheduling.md"
```

---

## Acceptance criteria

- `Document.auto_ingest` flag exists, defaults `False`, editable in the Document changelist.
- `sweep_targets()` iterates only flagged documents with a `source_url`, calls `ingest_target` per target, isolates per-target failures, and returns an accurate `SweepSummary` (total/success/skipped/failed). Unchanged content → `skipped`; new/changed → a **draft** (never published).
- `sweep_targets` and `ensure_sweep_schedule` management commands work; the schedule registration is idempotent and honors `SWEEP_CRON`.
- `django-q2` is wired with the Postgres ORM broker (no Redis); `run_sweep` is the scheduled callable.
- `docker compose up --build` brings up `db` + `web` (gunicorn, migrations applied, static collected) + `qcluster` (schedule ensured, worker running).
- Whole repo green: `ruff check .` clean, `pytest` all pass, `makemigrations --check` clean.

## Known limitations / carryover to 3d (or deploy step §16 п.10)

- **No live acceptance** against `pravo.gov.ru` and **no real seed-corpus** yet — that is spec §16 п.10 (separate step). 3c ships the *mechanism* only; tests use `MockTransport`.
- **No inter-target rate-limit/delay** (corpus is units–dozens, spec §15). If the corpus grows, add a configurable `SWEEP_DELAY` between targets.
- **Curation polish is 3d**: review queue, draft↔current diff, "reparse from RawSource" action, fully read-only ingestion admin.
- **qcluster is a single worker instance**; observability is whatever django-q2's admin provides. No external monitoring/alerting (notifications are out of v1, spec §3).
- **Web container** runs gunicorn + whitenoise with no TLS/reverse-proxy — that's a deployment concern for the §16 п.10 step.
- Long-standing deferred items from earlier plans still open (see `lawiot-overview` memory): `Link.to_document` on_delete policy, sanitizing search snippets, bulk `reindex_search`.
