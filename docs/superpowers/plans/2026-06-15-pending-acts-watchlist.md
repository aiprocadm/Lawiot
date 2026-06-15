# Реестр ожидаемых актов (pending-watchlist) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать куратору всегда видимый в admin список актов, которые мы хотим в корпусе, но которых пока нет в ИПС (как 565-ФЗ), с подсказкой как завести — без скрейпинга/OCR/планировщика.

**Architecture:** Модель `PendingAct` с вычисляемым свойством `is_resolved` (выводится из состояния корпуса), регистрация в Django admin (admin-список = напоминание), декларативный `PENDING_ACTS` в seed-файле, материализуемый `seed_corpus` с авто-удалением разрешённых записей.

**Tech Stack:** Django (модель + admin + management-команда), pytest-django, PostgreSQL.

**Спека:** `docs/superpowers/specs/2026-06-15-pending-acts-watchlist-design.md`

---

## Окружение исполнителя

- Worktree: `D:\Кодинг\Lawiot.worktrees\pending-acts`, ветка `feature/lawiot-pending-acts-watchlist`. Все команды — из этого каталога.
- Интерпретатор (Windows-`python` — зависающий Store-stub, НЕ использовать): во всех командах ниже
  `PY` = `D:\Кодинг\Lawiot\.venv\Scripts\python.exe` (общий venv главного репо работает по абсолютному пути).
- `.env` уже скопирован в worktree (даёт `DATABASE_URL` на Postgres `lawiot-db`). Без него тесты молча уходят на SQLite и FTS-тесты падают.
- ruff: `D:\Кодинг\Lawiot\.venv\Scripts\ruff.exe`.

## Файловая структура

- **Modify:** `documents/models.py` — добавить класс `PendingAct` в конец файла (ссылается на уже определённые выше `Document` и `Redaction`).
- **Create (auto):** `documents/migrations/0013_pendingact.py` — через `makemigrations` (последняя миграция — 0012).
- **Modify:** `documents/seed/labor_law.py` — добавить `PENDING_ACTS`, заменить комментарий-список кандидатов.
- **Modify:** `documents/management/commands/seed_corpus.py` — материализовать `PENDING_ACTS` + удалить разрешённые.
- **Modify:** `documents/admin.py` — `PendingActAdmin` + `PendingActResolvedFilter`.
- **Create (test):** `documents/tests/test_pending_acts.py` — модель, seed, admin.

---

### Task 1: Модель `PendingAct` с `is_resolved`

**Files:**
- Modify: `documents/models.py` (добавить в конец файла)
- Create (test): `documents/tests/test_pending_acts.py`
- Create (auto): `documents/migrations/0013_pendingact.py`

- [ ] **Step 1: Написать падающие тесты модели**

Создать `documents/tests/test_pending_acts.py`:

```python
import pytest

from documents.models import Document, PendingAct, Redaction
from documents.tests.factories import make_document, make_redaction


@pytest.mark.django_db
def test_is_resolved_false_without_matching_document():
    pa = PendingAct.objects.create(
        slug="zanyatost-565-fz",
        title="О занятости населения в Российской Федерации",
        official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    assert pa.is_resolved is False


@pytest.mark.django_db
def test_is_resolved_false_with_only_draft():
    pa = PendingAct.objects.create(
        slug="zanyatost-565-fz",
        title="О занятости населения в Российской Федерации",
        official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    doc = make_document(
        slug="zanyatost-565-fz", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.DRAFT, is_current=False)
    assert pa.is_resolved is False


@pytest.mark.django_db
def test_is_resolved_true_with_published_current():
    pa = PendingAct.objects.create(
        slug="zanyatost-565-fz",
        title="О занятости населения в Российской Федерации",
        official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    doc = make_document(
        slug="zanyatost-565-fz", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True)
    assert pa.is_resolved is True


@pytest.mark.django_db
def test_is_resolved_false_when_number_matches_but_doc_type_differs():
    pa = PendingAct.objects.create(
        slug="x-565", title="Иной акт", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    doc = make_document(
        slug="x-565-decree", official_number="565-ФЗ", doc_type=Document.DocType.DECREE,
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True)
    assert pa.is_resolved is False
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_pending_acts.py -v`
Expected: ошибка импорта `ImportError: cannot import name 'PendingAct'` (модель ещё не существует).

- [ ] **Step 3: Добавить модель в конец `documents/models.py`**

```python
class PendingAct(models.Model):
    """Акт, который мы хотим в корпусе, но которого пока нет в доступном источнике
    (напр. 565-ФЗ: в ИПС нет консолидированного текста). Напоминание куратору —
    список виден в admin; «разрешён» выводится из состояния корпуса."""

    slug = models.SlugField(max_length=255, unique=True)
    title = models.TextField()
    official_number = models.CharField(max_length=100, blank=True)
    doc_type = models.CharField(max_length=20, choices=Document.DocType.choices)
    note = models.TextField(blank=True, help_text="Почему ждём / где искать.")
    ips_search_url = models.URLField(blank=True, help_text="Ссылка на поиск ИПС (браузер).")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at"]
        verbose_name = "ожидаемый акт"
        verbose_name_plural = "ожидаемые акты"

    def __str__(self):
        return f"{self.official_number}: {self.title[:60]} (ожидается)"

    @property
    def is_resolved(self) -> bool:
        """True, когда акт уже заведён: есть Document с теми же (official_number,
        doc_type) и опубликованной текущей редакцией."""
        return Document.objects.filter(
            official_number=self.official_number,
            doc_type=self.doc_type,
            redactions__is_current=True,
            redactions__review_status=Redaction.ReviewStatus.PUBLISHED,
        ).exists()
```

- [ ] **Step 4: Создать миграцию**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe manage.py makemigrations documents`
Expected: `Migrations for 'documents': documents\migrations\0013_pendingact.py - Create model PendingAct`.

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_pending_acts.py -v`
Expected: 4 passed (pytest-django создаёт тестовую БД из миграций).

- [ ] **Step 6: Коммит**

```bash
git add documents/models.py documents/migrations/0013_pendingact.py documents/tests/test_pending_acts.py
git commit -m "feat(documents): модель PendingAct (реестр ожидаемых актов) + is_resolved"
```

---

### Task 2: Seed-интеграция (`PENDING_ACTS` + materialize + авто-удаление)

**Files:**
- Modify: `documents/seed/labor_law.py`
- Modify: `documents/management/commands/seed_corpus.py`
- Modify (test): `documents/tests/test_pending_acts.py`

- [ ] **Step 1: Дописать падающие тесты seed_corpus**

Добавить в конец `documents/tests/test_pending_acts.py`:

```python
@pytest.mark.django_db
def test_seed_corpus_materializes_pending_acts():
    from django.core.management import call_command

    call_command("seed_corpus")
    assert PendingAct.objects.filter(slug="zanyatost-565-fz").exists()


@pytest.mark.django_db
def test_seed_corpus_removes_resolved_pending_act():
    from django.core.management import call_command

    # 565-ФЗ "разрешён": заведён и опубликован
    doc = make_document(
        slug="zanyatost-565-fz", official_number="565-ФЗ",
        doc_type=Document.DocType.FEDERAL_LAW,
        title="О занятости населения в Российской Федерации",
    )
    make_redaction(document=doc, review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True)

    call_command("seed_corpus")

    # разрешённая запись не остаётся в реестре
    assert not PendingAct.objects.filter(slug="zanyatost-565-fz").exists()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_pending_acts.py -k seed -v`
Expected: FAIL — `seed_corpus` пока не заводит `PendingAct` (`zanyatost-565-fz` не существует).

- [ ] **Step 3: Добавить `PENDING_ACTS` в `documents/seed/labor_law.py`**

Заменить хвостовой комментарий-список кандидатов (строки про «Кандидаты подзаконки …»)
на структурированный список после закрывающей `]` у `SEED_ACTS`:

```python
# Ожидаемые акты: хотим в корпусе, но пока нет доступного источника. Видны куратору
# в admin (модель PendingAct) как напоминание; заводятся вручную, когда появятся.
PENDING_ACTS = [
    {
        "slug": "zanyatost-565-fz",
        "doc_type": "federal_law",
        "title": "О занятости населения в Российской Федерации",
        "official_number": "565-ФЗ",
        "note": (
            "Активный закон 2023 г. не отдаётся классической ИПС через doc_itself "
            "(там только отменённый предшественник — Закон РФ 1032-1, «Утратил силу»); "
            "на publication.pravo.gov.ru — скан-PDF исходной редакции (нужен OCR, и это "
            "не консолидированный текст). Ждём появления консолидированного 565-ФЗ в ИПС."
        ),
        "ips_search_url": "http://pravo.gov.ru/proxy/ips/?start_search&fattrib=1",
    },
]
```

- [ ] **Step 4: Расширить `documents/management/commands/seed_corpus.py`**

Заменить весь файл на:

```python
from django.core.management.base import BaseCommand

from documents.models import Document, PendingAct
from documents.seed.labor_law import PENDING_ACTS, SEED_ACTS


class Command(BaseCommand):
    help = "Идемпотентно заводит метаданные актов стартового корпуса (без текста/редакций)."

    def handle(self, *args, **options):
        created = updated = 0
        for act in SEED_ACTS:
            defaults = {k: v for k, v in act.items() if k != "slug"}
            _, was_created = Document.objects.update_or_create(slug=act["slug"], defaults=defaults)
            created += was_created
            updated += not was_created
        self.stdout.write(
            self.style.SUCCESS(f"Сид-корпус: создано {created}, обновлено {updated}.")
        )

        # Реестр ожидаемых актов: материализуем декларативный список и чистим разрешённые.
        p_created = p_updated = p_removed = 0
        for act in PENDING_ACTS:
            defaults = {k: v for k, v in act.items() if k != "slug"}
            _, was_created = PendingAct.objects.update_or_create(
                slug=act["slug"], defaults=defaults
            )
            p_created += was_created
            p_updated += not was_created
        for pending in PendingAct.objects.all():
            if pending.is_resolved:
                pending.delete()
                p_removed += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Ожидаемые акты: создано {p_created}, обновлено {p_updated}, "
                f"удалено разрешённых {p_removed}."
            )
        )
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_pending_acts.py -v`
Expected: 6 passed.

- [ ] **Step 6: Коммит**

```bash
git add documents/seed/labor_law.py documents/management/commands/seed_corpus.py documents/tests/test_pending_acts.py
git commit -m "feat(seed): PENDING_ACTS + materialize в seed_corpus с авто-удалением разрешённых"
```

---

### Task 3: Admin (`PendingActAdmin` + фильтр + подсказка)

**Files:**
- Modify: `documents/admin.py`
- Modify (test): `documents/tests/test_pending_acts.py`

- [ ] **Step 1: Дописать падающие тесты admin**

Добавить в конец `documents/tests/test_pending_acts.py`:

```python
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_pendingact_admin_changelist_renders():
    User = get_user_model()
    admin_user = User.objects.create_superuser(
        username="admin_probe", email="a@b.c", password="x"
    )
    client = Client()
    client.force_login(admin_user)
    resp = client.get(
        reverse("admin:documents_pendingact_changelist"), HTTP_HOST="localhost"
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_pendingact_admin_change_form_shows_ingest_hint():
    pa = PendingAct.objects.create(
        slug="zanyatost-565-fz", title="О занятости населения в Российской Федерации",
        official_number="565-ФЗ", doc_type=Document.DocType.FEDERAL_LAW,
    )
    User = get_user_model()
    admin_user = User.objects.create_superuser(
        username="admin_probe2", email="a@b.c", password="x"
    )
    client = Client()
    client.force_login(admin_user)
    resp = client.get(
        reverse("admin:documents_pendingact_change", args=[pa.pk]), HTTP_HOST="localhost"
    )
    assert resp.status_code == 200
    assert b"ingest_url --slug zanyatost-565-fz" in resp.content
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_pending_acts.py -k admin -v`
Expected: FAIL — `NoReverseMatch` (PendingAct в admin не зарегистрирован).

- [ ] **Step 3: Зарегистрировать admin в `documents/admin.py`**

В строке импорта моделей добавить `PendingAct`:

```python
from documents.models import Article, Document, Link, PendingAct, Redaction
```

Добавить в конец файла:

```python
class PendingActResolvedFilter(admin.SimpleListFilter):
    title = "в корпусе"
    parameter_name = "resolved"

    def lookups(self, request, model_admin):
        return [("yes", "Да"), ("no", "Нет")]

    def queryset(self, request, queryset):
        value = self.value()
        if value not in {"yes", "no"}:
            return queryset
        resolved_ids = [pa.pk for pa in queryset if pa.is_resolved]
        if value == "yes":
            return queryset.filter(pk__in=resolved_ids)
        return queryset.exclude(pk__in=resolved_ids)


@admin.register(PendingAct)
class PendingActAdmin(admin.ModelAdmin):
    list_display = ("title", "official_number", "doc_type", "resolved", "added_at")
    list_filter = (PendingActResolvedFilter, "doc_type")
    search_fields = ("title", "official_number")
    readonly_fields = ("ingest_hint", "added_at")

    @admin.display(boolean=True, description="В корпусе")
    def resolved(self, obj):
        return obj.is_resolved

    @admin.display(description="Как завести")
    def ingest_hint(self, obj):
        return (
            f"python manage.py ingest_url --slug {obj.slug} "
            f'--url "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=<ND>&print=1"  '
            f"— затем ревью черновика и публикация вручную."
        )
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_pending_acts.py -v`
Expected: 8 passed.

- [ ] **Step 5: Коммит**

```bash
git add documents/admin.py documents/tests/test_pending_acts.py
git commit -m "feat(admin): PendingActAdmin — список-напоминание + фильтр + подсказка ingest"
```

---

### Task 4: Финальная верификация всего репозитория

**Files:** нет (только проверка).

- [ ] **Step 1: ruff по всему репо**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\ruff.exe check .`
Expected: `All checks passed!`

- [ ] **Step 2: Полный pytest на Postgres**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest -q`
Expected: все тесты проходят (новые 8 + существующие; ни одного провала/ошибки).

- [ ] **Step 3: Применить миграцию на dev-БД и проверить seed**

Run:
```bash
D:\Кодинг\Lawiot\.venv\Scripts\python.exe manage.py migrate
D:\Кодинг\Lawiot\.venv\Scripts\python.exe manage.py seed_corpus
```
Expected: `migrate` применяет `0013_pendingact`; `seed_corpus` печатает строку «Ожидаемые акты: создано 1 …» (565-ФЗ).

- [ ] **Step 4: Финальный коммит (если остались несохранённые изменения)**

```bash
git status
# если чисто — ничего не коммитим
```

---

## Замечания по реализации

- `PendingAct` определяется ПОСЛЕ `Document` и `Redaction` в `models.py` — оба нужны для `is_resolved`.
- `is_resolved` — свойство (не поле), поэтому `list_filter` использует кастомный `PendingActResolvedFilter` (перебор pk; таблица крошечная, это дёшево).
- Авто-удаление в `seed_corpus` идёт по `is_resolved`, а не по присутствию в `SEED_ACTS`: запись исчезает, когда акт реально опубликован. Записи, добавленные куратором вручную в admin и ещё не разрешённые, `seed_corpus` не трогает.
- Тесты используют `HTTP_HOST="localhost"` (в настройках `ALLOWED_HOSTS = ['localhost', '127.0.0.1']`), иначе admin-страницы вернут 400 DisallowedHost.
