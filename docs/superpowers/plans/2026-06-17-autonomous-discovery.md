# Автономное обнаружение подзаконных актов — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Система сама находит новые приказы/постановления Минтруда на портале опубликования, ведёт их реестр (`PendingAct`), best-effort предлагает `nd` из ИПС, а куратор одним действием привязывает акт к чистому HTML-источнику ИПС и включает авто-ингест.

**Architecture:** Конвейер из 4 звеньев: (1) клиент JSON-API `publication.pravo.gov.ru` → (2) `discover()` пишет `PendingAct` → (3) best-effort `resolve_nd` + действие куратора в admin создаёт `Document(auto_ingest=True, auto_publish=False, source_url=ИПС)` → (4) существующий `ingest_target`/`parse_points` (PR #41). Звено 4 уже есть. Точность текста — из ИПС HTML, без OCR.

**Tech Stack:** Django 5.2, httpx (сеть изолирована, в тестах `httpx.MockTransport`), django-q2 (расписание), PostgreSQL. Спека: `docs/superpowers/specs/2026-06-17-autonomous-discovery-design.md`.

**Реальные параметры API (выверены спайком 2026-06-17):**
- Список: `GET http://publication.pravo.gov.ru/api/Documents?SignatoryAuthorityId=<GUID>&PageSize=<10|20|50>&Index=<стр., 1-based>`
- Ответ: `{"itemsTotalCount", "itemsPerPage", "currentPage", "pagesTotalCount", "items":[...]}`
- Поля item: `eoNumber, complexName, name, number, documentDate ("2026-05-08T00:00:00"), signatoryAuthorityId, documentTypeId, title, pagesCount, jdRegNumber, jdRegDate, id, pdfFileLength`
- Минтруд (федеральный) GUID: `2c4929b0-9323-4541-9705-76185b9e284b`
- Тип «Приказ» GUID: `2dddb344-d3e2-4785-a899-7aa12bd47b6f`; «Постановление»: `fd5a8766-f6fd-4ac2-8fd9-66f414d314ac`
- PDF (не используем — сканы): `…/file/pdf?eoNumber=<EO>`
- Фикстура реального ответа: `ingestion/fixtures_raw/publication_mintrud_page1.json` (уже в репозитории, 2 приказа)

**Окружение тестов:** Postgres. Docker `lawiot-db`:5433 в этой среде мёртв → прогон django_db через WSL-фолбэк (см. `wsl-postgres-test-fallback`). Чистые тесты (MockTransport, без БД) гоняются на Windows-venv `D:\Кодинг\Lawiot\.venv\Scripts\python.exe` напрямую. Контроллер subagent-driven гоняет БД-тесты.

**Зависимость:** PR #41 (`parse_points`) — для сквозного разбора на выходе. Звенья 1–3 от его кода не зависят. Миграция `PendingAct` — следующий свободный номер (`0014` от main, `0015` если #41 смержён раньше); назначить при `makemigrations`.

---

### Task 1: Расширение модели PendingAct + миграция

**Files:**
- Modify: `documents/models.py` (класс `PendingAct`, ~248–278)
- Create: `documents/migrations/00NN_pendingact_discovery.py` (генерируется)
- Test: `documents/tests/test_pendingact_discovery.py`

- [ ] **Step 1: Написать падающий тест** — создать `documents/tests/test_pendingact_discovery.py`:

```python
import pytest
from django.db import IntegrityError

from documents.models import Document, PendingAct


@pytest.mark.django_db
def test_partial_unique_eo_number_blocks_duplicates():
    PendingAct.objects.create(
        slug="a-1", title="A", doc_type=Document.DocType.ORDER, eo_number="0001202606090026"
    )
    with pytest.raises(IntegrityError):
        PendingAct.objects.create(
            slug="a-2", title="B", doc_type=Document.DocType.ORDER, eo_number="0001202606090026"
        )


@pytest.mark.django_db
def test_blank_eo_number_allows_many_manual_rows():
    PendingAct.objects.create(slug="m-1", title="M1", doc_type=Document.DocType.ORDER)
    PendingAct.objects.create(slug="m-2", title="M2", doc_type=Document.DocType.ORDER)
    assert PendingAct.objects.filter(eo_number="").count() == 2


@pytest.mark.django_db
def test_discovery_defaults():
    pa = PendingAct.objects.create(slug="d-1", title="D", doc_type=Document.DocType.ORDER)
    assert pa.source == "manual"
    assert pa.resolution_status == "new"
    assert pa.ips_nd == ""
```

- [ ] **Step 2: Запустить — убедиться, что падает** (контроллер; БД-тест):
Expected: FAIL — у `PendingAct` ещё нет полей `eo_number`/`source`/`resolution_status`/`ips_nd`.

- [ ] **Step 3: Добавить поля и ограничение.** В `documents/models.py`, класс `PendingAct`: добавить поля после `added_at` и `Meta.constraints`. Итоговый класс:

```python
class PendingAct(models.Model):
    """Акт, который мы хотим в корпусе, но которого пока нет в доступном источнике
    (напр. 565-ФЗ: в ИПС нет консолидированного текста). Напоминание куратору —
    список виден в admin; «разрешён» выводится из состояния корпуса."""

    class Source(models.TextChoices):
        AUTO = "auto", "Авто"
        MANUAL = "manual", "Вручную"

    class ResolutionStatus(models.TextChoices):
        NEW = "new", "Новый"
        CANDIDATE = "candidate", "Есть кандидат"
        BOUND = "bound", "Привязан"
        DISMISSED = "dismissed", "Отклонён"

    slug = models.SlugField(max_length=255, unique=True)
    title = models.TextField()
    official_number = models.CharField(max_length=100, blank=True)
    doc_type = models.CharField(max_length=20, choices=Document.DocType.choices)
    note = models.TextField(blank=True, help_text="Почему ждём / где искать.")
    ips_search_url = models.URLField(blank=True, help_text="Ссылка на поиск ИПС (браузер).")
    added_at = models.DateTimeField(auto_now_add=True)
    # --- автообнаружение (publication.pravo.gov.ru) ---
    eo_number = models.CharField(
        max_length=40, blank=True, help_text="Номер ЭО портала опубликования (пусто у ручных)."
    )
    publication_url = models.URLField(blank=True, help_text="Ссылка на акт/PDF на портале.")
    document_date = models.DateField(null=True, blank=True)
    issuing_body = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    ips_nd = models.CharField(
        max_length=40, blank=True, help_text="Привязанный nd ИПС (резолвер/куратор)."
    )
    resolution_status = models.CharField(
        max_length=12, choices=ResolutionStatus.choices, default=ResolutionStatus.NEW
    )

    class Meta:
        ordering = ["added_at"]
        verbose_name = "ожидаемый акт"
        verbose_name_plural = "ожидаемые акты"
        constraints = [
            models.UniqueConstraint(
                fields=["eo_number"],
                condition=~models.Q(eo_number=""),
                name="uniq_pendingact_eo",
            ),
        ]

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

(`Q` уже импортирован в `models.py`: `from django.db.models import F, Q, Value`.)

- [ ] **Step 4: Сгенерировать миграцию** (Windows-venv, БД не нужна):

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe manage.py makemigrations documents`
Expected: создаётся `documents/migrations/00NN_*.py` (AddField ×6 + AddConstraint). Запомнить фактический номер.

- [ ] **Step 5: Запустить тесты** (контроллер, WSL):
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add documents/models.py documents/migrations/00*_*.py documents/tests/test_pendingact_discovery.py
git commit -m "feat(documents): поля автообнаружения в PendingAct + partial-unique eo_number"
```

---

### Task 2: Клиент API портала — PublicationDoc + разбор записи

**Files:**
- Create: `ingestion/publication.py`
- Test: `ingestion/tests/test_publication_parse.py`

- [ ] **Step 1: Написать падающий тест** — создать `ingestion/tests/test_publication_parse.py`:

```python
import json
from datetime import date
from pathlib import Path

from ingestion.publication import PublicationDoc, doc_type_for, parse_item

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures_raw" / "publication_mintrud_page1.json"


def _items():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]


def test_parse_item_maps_fields():
    doc = parse_item(_items()[0])
    assert isinstance(doc, PublicationDoc)
    assert doc.eo_number == "0001202606090026"
    assert doc.number == "200н"
    assert doc.document_date == date(2026, 5, 8)
    assert doc.doc_type == "order"  # приказ
    assert doc.pdf_url.endswith("eoNumber=0001202606090026")


def test_doc_type_for_known_and_unknown():
    assert doc_type_for("2dddb344-d3e2-4785-a899-7aa12bd47b6f") == "order"
    assert doc_type_for("fd5a8766-f6fd-4ac2-8fd9-66f414d314ac") == "decree"
    assert doc_type_for("00000000-0000-0000-0000-000000000000") == "other"
```

- [ ] **Step 2: Запустить — убедиться, что падает:**
Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_publication_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: ingestion.publication`.

- [ ] **Step 3: Создать `ingestion/publication.py`:**

```python
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from ingestion.fetching import DEFAULT_TIMEOUT, MAX_RETRIES, USER_AGENT

PUBLICATION_BASE = "http://publication.pravo.gov.ru"
# Федеральный Минтруд (signatoryAuthorityId портала опубликования).
FEDERAL_MINTRUD_ID = "2c4929b0-9323-4541-9705-76185b9e284b"

# GUID типов документа портала → значения Document.DocType (строки, без импорта
# модели — клиент остаётся свободным от Django; значения совпадают с DocType).
DOC_TYPE_BY_GUID = {
    "2dddb344-d3e2-4785-a899-7aa12bd47b6f": "order",  # Приказ
    "fd5a8766-f6fd-4ac2-8fd9-66f414d314ac": "decree",  # Постановление
}

PAGE_SIZE = 50  # допустимые значения портала: 10 | 20 | 50


def doc_type_for(guid: str) -> str:
    return DOC_TYPE_BY_GUID.get(guid, "other")


@dataclass
class PublicationDoc:
    eo_number: str
    number: str
    name: str
    complex_name: str
    document_date: date | None
    signatory_authority_id: str
    document_type_id: str
    doc_type: str
    pages_count: int
    reg_number: str
    pdf_url: str


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def parse_item(item: dict) -> PublicationDoc:
    eo = item.get("eoNumber", "")
    type_id = item.get("documentTypeId", "")
    return PublicationDoc(
        eo_number=eo,
        number=item.get("number", ""),
        name=item.get("name", ""),
        complex_name=item.get("complexName", ""),
        document_date=_to_date(item.get("documentDate")),
        signatory_authority_id=item.get("signatoryAuthorityId", ""),
        document_type_id=type_id,
        doc_type=doc_type_for(type_id),
        pages_count=item.get("pagesCount") or 0,
        reg_number=item.get("jdRegNumber", "") or "",
        pdf_url=f"{PUBLICATION_BASE}/file/pdf?eoNumber={eo}",
    )


def _new_client() -> httpx.Client:
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        transport=httpx.HTTPTransport(retries=MAX_RETRIES),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def iter_documents(
    authority_id: str,
    *,
    client: httpx.Client | None = None,
    since_date: date | None = None,
    max_pages: int | None = None,
) -> Iterator[PublicationDoc]:
    """Перебрать опубликованные акты органа постранично (новые сверху).

    since_date: если задан — остановиться, как только встретился акт старше даты
    (портал отдаёт по убыванию даты публикации). max_pages: предохранитель.
    Сеть изолирована здесь; в тестах передаётся client с httpx.MockTransport.
    """
    owns_client = client is None
    client = client or _new_client()
    try:
        index = 1
        while True:
            resp = client.get(
                f"{PUBLICATION_BASE}/api/Documents",
                params={
                    "SignatoryAuthorityId": authority_id,
                    "PageSize": PAGE_SIZE,
                    "Index": index,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            if not items:
                return
            for raw in items:
                doc = parse_item(raw)
                if since_date and doc.document_date and doc.document_date < since_date:
                    return
                yield doc
            if index >= (data.get("pagesTotalCount") or index):
                return
            if max_pages is not None and index >= max_pages:
                return
            index += 1
    finally:
        if owns_client:
            client.close()
```

- [ ] **Step 4: Запустить тесты — 2 PASS:**
Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_publication_parse.py -v`
Expected: PASS.

- [ ] **Step 5: Ruff + commit**

```bash
D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check ingestion/publication.py ingestion/tests/test_publication_parse.py
git add ingestion/publication.py ingestion/tests/test_publication_parse.py
git commit -m "feat(ingestion): клиент API публикации — PublicationDoc + разбор записи"
```

---

### Task 3: Пагинация iter_documents (тест на MockTransport)

**Files:**
- Modify: (никаких — `iter_documents` уже написан в Task 2)
- Test: `ingestion/tests/test_publication_iter.py`

- [ ] **Step 1: Написать тест пагинации** — создать `ingestion/tests/test_publication_iter.py`:

```python
import json
from pathlib import Path

import httpx

from ingestion.publication import FEDERAL_MINTRUD_ID, iter_documents

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures_raw" / "publication_mintrud_page1.json"


def _payload(index):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # Делаем «двухстраничный» источник: стр.1 = items фикстуры, стр.2 — пусто.
    data["pagesTotalCount"] = 2
    if index >= 2:
        data["items"] = []
    return data


def _client(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        index = int(request.url.params.get("Index", "1"))
        calls.append(index)
        return httpx.Response(200, json=_payload(index))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_iter_documents_walks_pages_until_empty():
    calls = []
    docs = list(iter_documents(FEDERAL_MINTRUD_ID, client=_client(calls)))
    assert [d.number for d in docs] == ["200н", "193н"]
    assert calls == [1, 2]  # дошёл до пустой второй страницы и остановился


def test_iter_documents_respects_max_pages():
    calls = []
    list(iter_documents(FEDERAL_MINTRUD_ID, client=_client(calls), max_pages=1))
    assert calls == [1]  # дальше первой страницы не пошёл
```

- [ ] **Step 2: Запустить — 2 PASS** (код уже есть из Task 2):
Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_publication_iter.py -v`
Expected: PASS. (Если падает — значит логика остановки/`max_pages` в `iter_documents` неверна; поправить там.)

- [ ] **Step 3: Commit**

```bash
git add ingestion/tests/test_publication_iter.py
git commit -m "test(ingestion): пагинация iter_documents на MockTransport"
```

---

### Task 4: Обнаружение discover() + DiscoverySummary

**Files:**
- Create: `ingestion/discovery.py`
- Test: `ingestion/tests/test_discovery.py`

- [ ] **Step 1: Написать падающий тест** — создать `ingestion/tests/test_discovery.py`:

```python
import json
from pathlib import Path

import httpx
import pytest

from documents.models import Document, PendingAct
from ingestion.discovery import DiscoverySummary, discover

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures_raw" / "publication_mintrud_page1.json"


def _one_page_client():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["pagesTotalCount"] = 1

    def handler(request):
        return httpx.Response(200, json=data)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_discover_creates_pending_acts():
    summary = discover(["auth-1"], client=_one_page_client())
    assert isinstance(summary, DiscoverySummary)
    assert summary.created == 2
    pa = PendingAct.objects.get(eo_number="0001202606090026")
    assert pa.official_number == "200н"
    assert pa.doc_type == Document.DocType.ORDER
    assert pa.source == PendingAct.Source.AUTO
    assert pa.publication_url.endswith("eoNumber=0001202606090026")


@pytest.mark.django_db
def test_discover_is_idempotent():
    discover(["auth-1"], client=_one_page_client())
    summary = discover(["auth-1"], client=_one_page_client())
    assert summary.created == 0
    assert summary.skipped == 2
    assert PendingAct.objects.count() == 2


@pytest.mark.django_db
def test_discover_skips_already_in_corpus(monkeypatch):
    # Если акт уже в корпусе (is_resolved=True), PendingAct не создаём.
    monkeypatch.setattr(PendingAct, "is_resolved", property(lambda self: True))
    summary = discover(["auth-1"], client=_one_page_client())
    assert summary.created == 0
    assert PendingAct.objects.count() == 0
```

- [ ] **Step 2: Запустить — убедиться, что падает** (контроллер, WSL):
Expected: FAIL — `ModuleNotFoundError: ingestion.discovery`.

- [ ] **Step 3: Создать `ingestion/discovery.py`:**

```python
from dataclasses import dataclass
from datetime import date

import httpx
from django.utils.text import slugify

from documents.models import PendingAct
from ingestion.publication import FEDERAL_MINTRUD_ID, PublicationDoc, iter_documents

# Органы, которые обходим по умолчанию (стартуем с федерального Минтруда).
DISCOVERY_AUTHORITIES = [FEDERAL_MINTRUD_ID]


@dataclass
class DiscoverySummary:
    total: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0

    def __str__(self):
        return (
            f"всего={self.total} создано={self.created} "
            f"пропущено={self.skipped} ошибок={self.failed}"
        )


def _slug_for(doc: PublicationDoc) -> str:
    base = slugify(f"{doc.doc_type}-{doc.number}-{doc.eo_number}")
    return base or f"act-{doc.eo_number}"


def _upsert(doc: PublicationDoc) -> str:
    """Создать/пропустить PendingAct по eo_number. Возвращает 'created'|'skipped'."""
    existing = PendingAct.objects.filter(eo_number=doc.eo_number).first()
    if existing is not None:
        return "skipped"
    pending = PendingAct(
        slug=_slug_for(doc),
        title=doc.name or doc.complex_name,
        official_number=doc.number,
        doc_type=doc.doc_type,  # "order"/"decree"/"other" — значения Document.DocType
        eo_number=doc.eo_number,
        publication_url=doc.pdf_url,
        document_date=doc.document_date,
        source=PendingAct.Source.AUTO,
    )
    if pending.is_resolved:  # уже в корпусе — не плодим напоминание
        return "skipped"
    pending.save()
    return "created"


def discover(
    authority_ids=None,
    *,
    client: httpx.Client | None = None,
    since_date: date | None = None,
    max_pages: int | None = None,
) -> DiscoverySummary:
    """Обойти органы, завести PendingAct для новых актов. Идемпотентно по eo_number.
    Изоляция по органу: сбой одного не валит остальные."""
    summary = DiscoverySummary()
    authority_ids = authority_ids or DISCOVERY_AUTHORITIES
    for authority_id in authority_ids:
        try:
            for doc in iter_documents(
                authority_id, client=client, since_date=since_date, max_pages=max_pages
            ):
                summary.total += 1
                result = _upsert(doc)
                setattr(summary, result, getattr(summary, result) + 1)
        except Exception:  # сетка: сбой по одному органу не обрывает обход
            summary.failed += 1
    return summary


def run_discovery() -> str:
    """Точка входа django-q2 (func='ingestion.discovery.run_discovery')."""
    return str(discover())
```

- [ ] **Step 4: Запустить тесты — 3 PASS** (контроллер, WSL):
Expected: PASS.

- [ ] **Step 5: Ruff + commit**

```bash
D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check ingestion/discovery.py ingestion/tests/test_discovery.py
git add ingestion/discovery.py ingestion/tests/test_discovery.py
git commit -m "feat(ingestion): обнаружение актов discover() + DiscoverySummary"
```

---

### Task 5: Расписание + команды + настройка

**Files:**
- Modify: `config/settings.py` (после `SWEEP_CRON`)
- Create: `ingestion/management/commands/discover_acts.py`
- Create: `ingestion/management/commands/ensure_discovery_schedule.py`
- Test: `ingestion/tests/test_discovery_commands.py`

- [ ] **Step 1: Написать падающий тест** — создать `ingestion/tests/test_discovery_commands.py`:

```python
import pytest
from django.core.management import call_command
from django_q.models import Schedule


@pytest.mark.django_db
def test_ensure_discovery_schedule_is_idempotent():
    call_command("ensure_discovery_schedule")
    call_command("ensure_discovery_schedule")
    qs = Schedule.objects.filter(name="daily-discovery")
    assert qs.count() == 1
    assert qs.first().func == "ingestion.discovery.run_discovery"
```

- [ ] **Step 2: Запустить — убедиться, что падает** (контроллер, WSL):
Expected: FAIL — нет команды `ensure_discovery_schedule`.

- [ ] **Step 3a: `config/settings.py`** — добавить после строки с `SWEEP_CRON = env(...)`:

```python
# Cron-выражение ежедневного обхода портала опубликования (обнаружение актов).
DISCOVERY_CRON = env("DISCOVERY_CRON", default="0 4 * * *")
```

- [ ] **Step 3b: создать `ingestion/management/commands/ensure_discovery_schedule.py`:**

```python
from django.conf import settings
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Идемпотентно зарегистрировать/обновить расписание обнаружения актов (django-q2)."

    SCHEDULE_NAME = "daily-discovery"

    def handle(self, *args, **options):
        schedule, created = Schedule.objects.update_or_create(
            name=self.SCHEDULE_NAME,
            defaults={
                "func": "ingestion.discovery.run_discovery",
                "schedule_type": Schedule.CRON,
                "cron": settings.DISCOVERY_CRON,
                "repeats": -1,
            },
        )
        verb = "создано" if created else "обновлено"
        self.stdout.write(
            self.style.SUCCESS(
                f"Расписание «{schedule.name}» {verb}: func={schedule.func}, cron={schedule.cron}"
            )
        )
```

- [ ] **Step 3c: создать `ingestion/management/commands/discover_acts.py`:**

```python
from django.core.management.base import BaseCommand

from ingestion.discovery import discover


class Command(BaseCommand):
    help = "Ручной обход портала опубликования: завести PendingAct для новых актов."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-pages", type=int, default=None, help="Предел страниц на орган (отладка)."
        )

    def handle(self, *args, max_pages, **options):
        summary = discover(max_pages=max_pages)
        self.stdout.write(self.style.SUCCESS(str(summary)))
```

- [ ] **Step 4: Запустить тест — PASS** (контроллер, WSL):
Expected: PASS.

- [ ] **Step 5: Ruff + commit**

```bash
D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check ingestion/management/commands/discover_acts.py ingestion/management/commands/ensure_discovery_schedule.py ingestion/tests/test_discovery_commands.py
git add config/settings.py ingestion/management/commands/discover_acts.py ingestion/management/commands/ensure_discovery_schedule.py ingestion/tests/test_discovery_commands.py
git commit -m "feat(ingestion): расписание daily-discovery + команды discover_acts/ensure_discovery_schedule"
```

---

### Task 6: Best-effort резолвер nd из ИПС

**Files:**
- Create: `ingestion/ips_resolve.py`
- Test: `ingestion/tests/test_ips_resolve.py`

- [ ] **Step 1: Написать падающий тест** — создать `ingestion/tests/test_ips_resolve.py`:

```python
import httpx
import pytest

from documents.models import Document, PendingAct
from ingestion.ips_resolve import ResolveResult, resolve_nd


def _client_returning(html, status=200):
    def handler(request):
        return httpx.Response(status, content=html.encode("cp1251"))

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_resolve_extracts_nd_candidates():
    act = PendingAct(slug="x", title="Об утверждении формы", doc_type=Document.DocType.ORDER)
    html = '<a href="?doc_itself=&nd=102074279">Приказ ...</a>'
    res = resolve_nd(act, client=_client_returning(html))
    assert isinstance(res, ResolveResult)
    assert "102074279" in res.candidates


@pytest.mark.django_db
def test_resolve_soft_empty_on_server_error():
    act = PendingAct(slug="y", title="Что-то", doc_type=Document.DocType.ORDER)
    res = resolve_nd(act, client=_client_returning("500", status=500))
    assert res.candidates == []
    assert res.note  # пояснение, не исключение
```

- [ ] **Step 2: Запустить — убедиться, что падает** (контроллер, WSL):
Expected: FAIL — `ModuleNotFoundError: ingestion.ips_resolve`.

- [ ] **Step 3: Создать `ingestion/ips_resolve.py`:**

```python
import re
from dataclasses import dataclass, field

import httpx

from ingestion.fetching import DEFAULT_TIMEOUT, MAX_RETRIES, USER_AGENT

IPS_BASE = "http://pravo.gov.ru/proxy/ips/"
_ND_RE = re.compile(r"nd=(\d+)")


@dataclass
class ResolveResult:
    candidates: list[str] = field(default_factory=list)
    note: str = ""


def _new_client() -> httpx.Client:
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        transport=httpx.HTTPTransport(retries=MAX_RETRIES),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def resolve_nd(act, *, client: httpx.Client | None = None) -> ResolveResult:
    """Best-effort: попытаться найти кандидатов nd в ИПС по названию акта.

    ИПС-поиск нестабилен headless (stateful JS-фреймсет, часто 500) — поэтому
    пустой результат штатен: куратор введёт nd вручную. Любой сетевой/HTTP-сбой
    превращается в мягкий пустой результат, НЕ в исключение."""
    owns_client = client is None
    client = client or _new_client()
    try:
        resp = client.get(
            IPS_BASE, params={"searchlist": "", "intelsearch": act.title[:120]}
        )
        if resp.status_code != 200:
            return ResolveResult(note=f"ИПС вернул {resp.status_code}")
        body = resp.content.decode("cp1251", errors="replace")
        candidates = []
        for nd in _ND_RE.findall(body):
            if nd not in candidates:
                candidates.append(nd)
        note = "" if candidates else "кандидатов не найдено"
        return ResolveResult(candidates=candidates, note=note)
    except Exception as exc:  # best-effort: сбой → пустой результат
        return ResolveResult(note=f"ошибка резолва: {type(exc).__name__}")
    finally:
        if owns_client:
            client.close()
```

- [ ] **Step 4: Запустить тесты — 2 PASS** (контроллер, WSL):
Expected: PASS.

- [ ] **Step 5: Ruff + commit**

```bash
D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check ingestion/ips_resolve.py ingestion/tests/test_ips_resolve.py
git add ingestion/ips_resolve.py ingestion/tests/test_ips_resolve.py
git commit -m "feat(ingestion): best-effort резолвер nd из ИПС"
```

---

### Task 7: Админка — список находок + действие «привязать к ИПС»

**Files:**
- Modify: `documents/admin.py` (`PendingActAdmin`, ~111–129)
- Test: `documents/tests/test_pendingact_admin.py`

- [ ] **Step 1: Написать падающий тест** — создать `documents/tests/test_pendingact_admin.py`:

```python
import pytest

from documents.admin import bind_to_ips
from documents.models import Document, PendingAct


@pytest.mark.django_db
def test_bind_to_ips_creates_auto_ingest_document():
    act = PendingAct.objects.create(
        slug="prikaz-320n-eo1",
        title="Об утверждении формы трудовых книжек",
        official_number="320н",
        doc_type=Document.DocType.ORDER,
        eo_number="0001202106020001",
        ips_nd="102074279",
        issuing_body="Минтруд России",
    )
    bind_to_ips(None, None, PendingAct.objects.filter(pk=act.pk))
    doc = Document.objects.get(slug="prikaz-320n-eo1")
    assert doc.doc_type == Document.DocType.ORDER
    assert doc.official_number == "320н"
    assert doc.auto_ingest is True
    assert doc.auto_publish is False
    assert "nd=102074279" in doc.source_url
    act.refresh_from_db()
    assert act.resolution_status == PendingAct.ResolutionStatus.BOUND


@pytest.mark.django_db
def test_bind_to_ips_skips_without_nd():
    act = PendingAct.objects.create(
        slug="no-nd", title="Без nd", doc_type=Document.DocType.ORDER
    )
    bind_to_ips(None, None, PendingAct.objects.filter(pk=act.pk))
    assert not Document.objects.filter(slug="no-nd").exists()
    act.refresh_from_db()
    assert act.resolution_status == PendingAct.ResolutionStatus.NEW
```

- [ ] **Step 2: Запустить — убедиться, что падает** (контроллер, WSL):
Expected: FAIL — нет `bind_to_ips` в `documents/admin.py`.

- [ ] **Step 3: В `documents/admin.py`** добавить функцию-действие (модульного уровня) и подключить её к `PendingActAdmin`. Импорт `Document` уже есть (строка 9). Добавить ПЕРЕД `@admin.register(PendingAct)`:

```python
@admin.action(description="Привязать к ИПС и включить авто-ингест")
def bind_to_ips(modeladmin, request, queryset):
    """Из ips_nd строим ИПС-источник и создаём/обновляем Document с auto_ingest.
    Без авто-публикации (auto_publish=False — лестница доверия)."""
    bound = 0
    for act in queryset:
        nd = (act.ips_nd or "").strip()
        if not nd:
            continue
        source_url = f"http://pravo.gov.ru/proxy/ips/?doc_itself=&nd={nd}&print=1"
        Document.objects.update_or_create(
            slug=act.slug,
            defaults={
                "title": act.title,
                "official_number": act.official_number,
                "doc_type": act.doc_type,
                "issuing_body": act.issuing_body,
                "source_url": source_url,
                "auto_ingest": True,
                "auto_publish": False,
            },
        )
        act.resolution_status = PendingAct.ResolutionStatus.BOUND
        act.save(update_fields=["resolution_status"])
        bound += 1
    if request is not None:
        modeladmin.message_user(request, f"Привязано актов: {bound}.")
```

И заменить класс `PendingActAdmin` на:

```python
@admin.register(PendingAct)
class PendingActAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "official_number",
        "doc_type",
        "source",
        "resolution_status",
        "document_date",
        "resolved",
        "added_at",
    )
    list_filter = (PendingActResolvedFilter, "doc_type", "source", "resolution_status")
    search_fields = ("title", "official_number", "eo_number")
    readonly_fields = ("ingest_hint", "added_at", "eo_number", "publication_url")
    actions = [bind_to_ips]

    @admin.display(boolean=True, description="В корпусе")
    def resolved(self, obj):
        return obj.is_resolved

    @admin.display(description="Как завести")
    def ingest_hint(self, obj):
        return (
            f"Заполните ips_nd и примените действие «Привязать к ИПС». "
            f"Либо вручную: python manage.py ingest_url --slug {obj.slug} "
            f'--url "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=<ND>&print=1"'
        )
```

- [ ] **Step 4: Запустить тесты — 2 PASS** (контроллер, WSL):
Expected: PASS.

- [ ] **Step 5: Ruff + commit**

```bash
D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check documents/admin.py documents/tests/test_pendingact_admin.py
git add documents/admin.py documents/tests/test_pendingact_admin.py
git commit -m "feat(admin): список находок PendingAct + действие «привязать к ИПС»"
```

---

## Финальная проверка (контроллер)

- [ ] Весь набор тестов зелёный (WSL Postgres-фолбэк): `bash run_wsl_tests.sh -q --create-db` (новая миграция → `--create-db`).
- [ ] `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check .` чист.
- [ ] `D:\Кодинг\Lawiot\.venv\Scripts\python.exe manage.py check` без ошибок.
- [ ] Финальное холистическое ревью (opus).

## Замечания по архитектуре

- **Изоляция:** клиент API (`publication.py`) и резолвер (`ips_resolve.py`) — чистые сетевые слои за интерфейсом, тестируются на `MockTransport`. `discovery.py` — оркестрация (зеркалит `scheduling.py`). Каждый файл — одно назначение.
- **Лестница доверия:** ни один `Document` не создаётся без действия куратора; `auto_publish=False` всегда; резолвер только предлагает.
- **Идемпотентность:** обнаружение дедуплицирует по `eo_number`; расписание — `update_or_create`; привязка — `update_or_create` по slug.
- **YAGNI:** OCR нет; надёжный автopoиск ИПС — позже (резолвер best-effort); один орган (Минтруд), расширение — правкой `DISCOVERY_AUTHORITIES`.
