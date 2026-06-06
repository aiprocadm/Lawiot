# Lawiot MVP — План 3a: Ядро приёма данных (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Построить тестируемое ядро приёма данных: модели «сырья» и аудита (`RawSource`, `IngestionJob`), чистый парсер (байты → структура статей), изолированный сетевой загрузчик, конвейер «скачать → сохранить сырьё → обнаружить изменение → разобрать → создать черновик», и ручной импорт как запасной путь. Опубликованный текст никогда не перезаписывается автоматически.

**Architecture:** Новое приложение `ingestion`. Сетевая операция (`fetching.py`, httpx) строго отделена от чистого разбора (`parsing.py`) — парсер тестируется на сохранённой фикстуре без обращения к сети. Парсер работает по **текстовым маркерам** («Статья N.»), а не по хрупкой HTML-разметке, поэтому один и тот же разбор обслуживает и автозагрузку (HTML→текст→разбор), и ручной импорт (вставленный текст). Оркестрация (`services.py`) изолирует сбои по цели, ведёт аудит в `IngestionJob`, идемпотентна по `(document, redaction_date)` и создаёт только **черновики**.

**Tech Stack:** Python 3.13 (`.venv`), Django 5.2, PostgreSQL 16 (Docker, host-порт 5433), **httpx** (загрузка), **beautifulsoup4** (разбор HTML, стандартный `html.parser` — без бинарного `lxml`), pytest + pytest-django.

**Спецификация:** [docs/superpowers/specs/2026-06-05-lawiot-design.md](../specs/2026-06-05-lawiot-design.md) — §5 (модели RawSource/IngestionJob), §6 (подсистема приёма), §12 (тестирование на фикстурах), §13 (обработка ошибок).

**Место в дорожной карте:** **План 3 из 3, под-план «a» (ядро)**. Реализует §16 шаг 6 (приём: RawSource, парсер на фикстурах, draft-редакции, ручной импорт) и большую часть §6. Строится поверх Планов 1–2 (Document/Redaction/Article/Link + поиск влиты в `main`). Ветка: `feature/lawiot-plan-3a-ingestion-core` (создана от `main`).

**Сознательно отложено в следующие под-планы:**
- **3b — извлечение связей** из текста (цитаты → `Link` со `status=suggested`), §6 шаг 6 / §16 шаг 7.
- **3c — расписание** (django-q2) и периодический обход сид-списка, §6 «Расписание» / §16 шаг 8.
- **3d — шлифовка курирования**: очередь ревью, текстовый diff «черновик↔текущая», действие «переразобрать из RawSource», форма ручного импорта в браузере, §7 / §16 шаг 9.
- **PDF** (`pdfminer.six`): 3a обрабатывает HTML/текст; PDF-разбор — отдельная задача, когда появятся реальные PDF-цели.
- **Разбор разделов/глав** (иерархия `kind=section/chapter`): 3a извлекает плоский список статей; иерархия — позже.

---

## Окружение исполнения

- Запуск Python — **только** через `.venv\Scripts\python.exe` (bare `python` — зависающая Store-заглушка).
- **Docker поднят**, контейнер `lawiot-db` healthy на порту **5433**; `DATABASE_URL` в `.env`. Тесты pytest-django создают `test_lawiot` на этом контейнере, поэтому он должен быть запущен.
- ruff: line-length 100, target py313.

---

## Структура файлов (План 3a)

```
requirements.txt                                  # MODIFY — + httpx, + beautifulsoup4
config/settings.py                                # MODIFY — + "ingestion" в INSTALLED_APPS
documents/models.py                               # MODIFY — Redaction.raw_source FK → ingestion.RawSource
documents/migrations/0006_redaction_raw_source.py # NEW (makemigrations)
ingestion/__init__.py                             # NEW app
ingestion/apps.py                                 # NEW
ingestion/models.py                               # NEW — RawSource, IngestionJob
ingestion/migrations/__init__.py                  # NEW
ingestion/migrations/0001_initial.py              # NEW (makemigrations)
ingestion/parsing.py                              # NEW — чистый парсер: байты → ParsedDocument
ingestion/fetching.py                             # NEW — httpx-загрузчик (сеть изолирована)
ingestion/services.py                             # NEW — оркестрация: ingest_target, import_manual, draft-логика
ingestion/admin.py                                # NEW — read-only аудит RawSource/IngestionJob
ingestion/fixtures_raw/__init__.py                # NEW — пометка пакета (для удобного пути в тестах не нужен, но не мешает)
ingestion/fixtures_raw/sample_tk.html             # NEW — фикстура HTML для тестов парсера
ingestion/management/__init__.py                  # NEW
ingestion/management/commands/__init__.py         # NEW
ingestion/management/commands/ingest_url.py       # NEW — разовая загрузка URL → черновик
ingestion/management/commands/import_document.py  # NEW — ручной импорт из файла → черновик
ingestion/tests/__init__.py                       # NEW
ingestion/tests/test_models.py                    # NEW
ingestion/tests/test_parsing.py                   # NEW
ingestion/tests/test_fetching.py                  # NEW
ingestion/tests/test_services.py                  # NEW
ingestion/tests/test_commands.py                  # NEW
ingestion/tests/test_admin.py                     # NEW
```

**Ответственность:**
- `ingestion/parsing.py` — **чистая функция** от байтов: никаких сети/БД. Легко тестируется на фикстуре.
- `ingestion/fetching.py` — **единственное** место с сетью; принимает инъектируемый `httpx.Client` для тестов с `MockTransport`.
- `ingestion/services.py` — оркестрация и БД-эффекты: сохранение сырья, обнаружение изменений, создание черновика, аудит, изоляция сбоев.
- `ingestion/models.py` — `RawSource` (оригинал + хэш), `IngestionJob` (лог запуска).

---

## Task 1: Каркас приложения `ingestion` + зависимости

**Files:**
- Create: `ingestion/__init__.py`, `ingestion/apps.py`, `ingestion/tests/__init__.py`, `ingestion/tests/test_models.py` (заготовка одного теста)
- Modify: `config/settings.py`, `requirements.txt`

- [ ] **Step 1: Написать падающий тест (приложение зарегистрировано)**

`ingestion/__init__.py`: пустой файл.
`ingestion/tests/__init__.py`: пустой файл.

`ingestion/tests/test_models.py`:
```python
def test_ingestion_app_is_installed():
    from django.apps import apps

    assert apps.is_installed("ingestion")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_models.py -v`
Expected: ошибка/сбой — приложения `ingestion` ещё нет в `INSTALLED_APPS` (а также не создан `apps.py`).

- [ ] **Step 3: Создать `apps.py`, зарегистрировать приложение, добавить зависимости**

`ingestion/apps.py`:
```python
from django.apps import AppConfig


class IngestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ingestion"
```

В `config/settings.py` добавить `"ingestion"` в `INSTALLED_APPS` после `"search"`:
```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "accounts",
    "documents",
    "search",
    "ingestion",
]
```

В `requirements.txt` добавить две строки (после `psycopg[binary]>=3.2`):
```
httpx>=0.27
beautifulsoup4>=4.12
```

- [ ] **Step 4: Установить зависимости и прогнать тест**

Run: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
Expected: устанавливаются `httpx` и `beautifulsoup4` (и их зависимости: httpcore, anyio, certifi, idna, sniffio, soupsieve) — все чистые wheels, без компиляции.

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_models.py -v`
Expected: PASS (`test_ingestion_app_is_installed`).

- [ ] **Step 5: Commit**

```bash
git add ingestion/__init__.py ingestion/apps.py ingestion/tests/__init__.py ingestion/tests/test_models.py config/settings.py requirements.txt
git commit -m "chore(ingestion): scaffold app + add httpx/beautifulsoup4 deps"
```

---

## Task 2: Модели `RawSource` и `IngestionJob` + FK `Redaction.raw_source`

**Files:**
- Create: `ingestion/models.py`
- Modify: `documents/models.py` (добавить `raw_source` в `Redaction`)
- Create (via makemigrations): `ingestion/migrations/0001_initial.py`, `documents/migrations/0006_redaction_raw_source.py`
- Test: `ingestion/tests/test_models.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Заменить содержимое `ingestion/tests/test_models.py` на:
```python
import pytest
from django.utils import timezone


def test_ingestion_app_is_installed():
    from django.apps import apps

    assert apps.is_installed("ingestion")


def test_redaction_has_raw_source_fk():
    from documents.models import Redaction
    from ingestion.models import RawSource

    field = Redaction._meta.get_field("raw_source")
    assert field.related_model is RawSource
    assert field.null is True


@pytest.mark.django_db
def test_rawsource_stores_content_and_metadata():
    from ingestion.models import RawSource

    rs = RawSource.objects.create(
        target_key="tk-rf",
        content=b"<p>hi</p>",
        content_hash="deadbeef",
        content_type="text/html",
        source_url="https://example.test/doc",
    )
    rs.refresh_from_db()
    assert bytes(rs.content) == b"<p>hi</p>"
    assert rs.content_hash == "deadbeef"
    assert rs.fetched_at is not None


@pytest.mark.django_db
def test_ingestionjob_create_and_link_redaction():
    from documents.tests.factories import make_redaction
    from ingestion.models import IngestionJob

    red = make_redaction()
    job = IngestionJob.objects.create(
        target_key="tk-rf",
        status=IngestionJob.Status.SUCCESS,
        started_at=timezone.now(),
        produced_redaction=red,
    )
    assert job.status == IngestionJob.Status.SUCCESS
    assert job.produced_redaction == red
    assert red.ingestion_jobs.count() == 1


@pytest.mark.django_db
def test_no_pending_migrations():
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_models.py -v`
Expected: FAIL — модуля `ingestion.models` нет; поля `Redaction.raw_source` нет.

- [ ] **Step 3: Создать модели и добавить FK на Redaction**

`ingestion/models.py`:
```python
from django.db import models


class RawSource(models.Model):
    """Оригинал скачанного/импортированного материала + хэш для обнаружения изменений."""

    target_key = models.CharField(max_length=255)
    content = models.BinaryField()
    content_hash = models.CharField(max_length=64, db_index=True)
    content_type = models.CharField(max_length=100, blank=True)
    source_url = models.URLField(blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fetched_at"]
        indexes = [models.Index(fields=["target_key", "-fetched_at"])]

    def __str__(self):
        return f"{self.target_key} ({self.content_type or 'raw'})"


class IngestionJob(models.Model):
    """Запись одного запуска конвейера приёма (аудит)."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Успех"
        FAILED = "failed", "Ошибка"
        SKIPPED = "skipped", "Пропущено"

    target_key = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    raw_source = models.ForeignKey(
        RawSource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="jobs",
    )
    produced_redaction = models.ForeignKey(
        "documents.Redaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ingestion_jobs",
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.target_key}: {self.get_status_display()}"
```

В `documents/models.py`, в классе `Redaction`, добавить поле сразу после `parser_version = models.CharField(max_length=50, blank=True)`:
```python
    raw_source = models.ForeignKey(
        "ingestion.RawSource",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="redactions",
    )
```

- [ ] **Step 4: Создать миграции, применить, прогнать тесты**

**Сначала создать пустой файл `ingestion/migrations/__init__.py`** — иначе для нового приложения `makemigrations` не сгенерирует `ingestion/0001` и впишет в `documents/0006` висящую зависимость `('ingestion', '__first__')`, которая упадёт на `migrate`.

Run: `.venv\Scripts\python.exe manage.py makemigrations`
Expected: созданы `ingestion/migrations/0001_initial.py` (RawSource + IngestionJob) и `documents/migrations/0006_redaction_raw_source.py` (AddField). Django сам проставит зависимость: `documents/0006` → `ingestion/0001` → `documents/0005`.

Run: `.venv\Scripts\python.exe manage.py migrate`
Expected: миграции применяются без ошибок.

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_models.py -v`
Expected: все тесты passed (включая `test_no_pending_migrations`).

- [ ] **Step 5: Commit**

```bash
git add ingestion/models.py ingestion/migrations documents/models.py documents/migrations/0006_redaction_raw_source.py ingestion/tests/test_models.py
git commit -m "feat(ingestion): RawSource + IngestionJob models; Redaction.raw_source FK"
```

---

## Task 3: Парсер (чистая функция: байты → структура)

**Files:**
- Create: `ingestion/parsing.py`, `ingestion/fixtures_raw/__init__.py`, `ingestion/fixtures_raw/sample_tk.html`
- Test: `ingestion/tests/test_parsing.py`

- [ ] **Step 1: Создать фикстуру**

`ingestion/fixtures_raw/__init__.py`: пустой файл.

`ingestion/fixtures_raw/sample_tk.html`:
```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <title>ТК РФ — служебный заголовок</title>
  <style>.x{color:red}</style>
</head>
<body>
  <h1>Трудовой кодекс Российской Федерации</h1>
  <p>Статья 80. Расторжение трудового договора по инициативе работника</p>
  <p>Работник имеет право расторгнуть трудовой договор, предупредив об этом
     работодателя в письменной форме не позднее чем за две недели.</p>
  <p>Статья 81. Расторжение трудового договора по инициативе работодателя</p>
  <p>Трудовой договор может быть расторгнут работодателем в случаях
     ликвидации организации либо прекращения деятельности.</p>
  <script>var ignored = 1;</script>
</body>
</html>
```

- [ ] **Step 2: Написать падающие тесты**

`ingestion/tests/test_parsing.py`:
```python
from pathlib import Path

import ingestion
from ingestion.parsing import html_to_text, parse_articles, parse_document

FIXTURES = Path(ingestion.__file__).parent / "fixtures_raw"


def test_html_to_text_strips_tags_scripts_and_head():
    html = b"<head><title>T</title><style>.x{}</style></head><body><h1>Hi</h1><script>x()</script><p>Body</p></body>"
    text = html_to_text(html, "text/html")
    assert "Hi" in text
    assert "Body" in text
    assert "x()" not in text       # script removed
    assert ".x{}" not in text      # style removed
    assert "T" not in text.splitlines()  # head/title removed


def test_parse_articles_splits_on_headers():
    text = "Статья 80. Заголовок один\nтекст один\nСтатья 81. Заголовок два\nтекст два"
    arts = parse_articles(text)
    assert [a.number for a in arts] == ["80", "81"]
    assert arts[0].title == "Заголовок один"
    assert arts[0].text == "текст один"
    assert arts[0].order == 1
    assert arts[1].order == 2
    assert arts[1].text == "текст два"


def test_parse_articles_handles_decimal_numbers():
    text = "Статья 312.1. Дистанционная работа\nположение"
    arts = parse_articles(text)
    assert arts[0].number == "312.1"
    assert arts[0].title == "Дистанционная работа"


def test_parse_document_on_html_fixture():
    content = (FIXTURES / "sample_tk.html").read_bytes()
    parsed = parse_document(content, "text/html")
    assert parsed.title == "Трудовой кодекс Российской Федерации"
    assert [a.number for a in parsed.articles] == ["80", "81"]
    assert "две недели" in parsed.articles[0].text
    assert "ликвидации организации" in parsed.articles[1].text
    # full_text сохраняет весь нормализованный текст
    assert "Трудовой кодекс" in parsed.full_text
    assert "работодателя" in parsed.full_text


def test_parse_document_accepts_plain_text():
    content = "Статья 1. Общие положения\nНастоящий акт регулирует отношения.".encode("utf-8")
    parsed = parse_document(content, "text/plain")
    assert [a.number for a in parsed.articles] == ["1"]
    assert parsed.articles[0].text == "Настоящий акт регулирует отношения."
```

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -v`
Expected: FAIL — модуля `ingestion.parsing` нет.

- [ ] **Step 4: Реализовать парсер**

`ingestion/parsing.py`:
```python
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

PARSER_VERSION = "1.0"

# Заголовок статьи: «Статья 81. Расторжение…» / «Статья 312.1. …»
ARTICLE_RE = re.compile(r"^Статья\s+(\d+(?:\.\d+)?)\.?\s*(.*)$")


@dataclass
class ParsedArticle:
    number: str
    title: str
    text: str
    order: int


@dataclass
class ParsedDocument:
    full_text: str
    title: str = ""
    articles: list[ParsedArticle] = field(default_factory=list)


def html_to_text(content: bytes, content_type: str = "text/html") -> str:
    """Извлечь читаемый текст. HTML → текст без тегов (script/style/head удаляются);
    нехтмл — декодируется как UTF-8. Результат нормализуется (без пустых строк)."""
    if "html" in (content_type or "").lower():
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
        raw = soup.get_text("\n")
    else:
        raw = content.decode("utf-8", errors="replace")
    lines = [line.strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_articles(text: str) -> list[ParsedArticle]:
    """Разбить нормализованный текст на статьи по заголовкам «Статья N.»."""
    articles: list[ParsedArticle] = []
    current: ParsedArticle | None = None
    body: list[str] = []
    order = 0
    for line in text.splitlines():
        match = ARTICLE_RE.match(line)
        if match:
            if current is not None:
                current.text = "\n".join(body).strip()
                articles.append(current)
            order += 1
            current = ParsedArticle(
                number=match.group(1), title=match.group(2).strip(), text="", order=order
            )
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        current.text = "\n".join(body).strip()
        articles.append(current)
    return articles


def parse_document(content: bytes, content_type: str = "text/html") -> ParsedDocument:
    """Полный разбор: текст + список статей + заголовок-эвристика (первая нестатейная строка)."""
    text = html_to_text(content, content_type)
    articles = parse_articles(text)
    title = ""
    for line in text.splitlines():
        if not ARTICLE_RE.match(line):
            title = line
            break
    return ParsedDocument(full_text=text, title=title, articles=articles)
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -v`
Expected: все тесты passed.

- [ ] **Step 6: Commit**

```bash
git add ingestion/parsing.py ingestion/fixtures_raw
git commit -m "feat(ingestion): pure text-marker parser (HTML/plain text -> articles)"
```

---

## Task 4: Загрузчик (сеть изолирована, инъекция клиента для тестов)

**Files:**
- Create: `ingestion/fetching.py`
- Test: `ingestion/tests/test_fetching.py`

- [ ] **Step 1: Написать падающие тесты**

`ingestion/tests/test_fetching.py`:
```python
import httpx
import pytest

from ingestion.fetching import USER_AGENT, fetch


def test_fetch_returns_content_type_and_final_url():
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<h1>hi</h1>"
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch("https://example.test/doc", client=client)
    assert result.content == b"<h1>hi</h1>"
    assert "html" in result.content_type
    assert result.source_url.endswith("/doc")
    assert result.fetched_at is not None


def test_fetch_sends_polite_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, content=b"ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch("https://example.test/", client=client)
    assert seen["ua"] == USER_AGENT


def test_fetch_raises_on_server_error():
    def handler(request):
        return httpx.Response(500, content=b"boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        fetch("https://example.test/", client=client)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_fetching.py -v`
Expected: FAIL — модуля `ingestion.fetching` нет.

- [ ] **Step 3: Реализовать загрузчик**

`ingestion/fetching.py`:
```python
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

# Вежливый идентификатор: внутренний справочник, не агрессивный краулер.
USER_AGENT = "LawiotBot/1.0 (internal legal reference)"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3


@dataclass
class FetchResult:
    content: bytes
    content_type: str
    source_url: str
    fetched_at: datetime


def fetch(url: str, *, client: httpx.Client | None = None) -> FetchResult:
    """Вежливо скачать URL. Сетевой эффект изолирован здесь, чтобы разбор оставался чистым.
    В тестах передаётся `client` с `httpx.MockTransport` — живая сеть не нужна."""
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            transport=httpx.HTTPTransport(retries=MAX_RETRIES),
            follow_redirects=True,
        )
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return FetchResult(
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            source_url=str(response.url),
            fetched_at=datetime.now(timezone.utc),
        )
    finally:
        if owns_client:
            client.close()
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_fetching.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add ingestion/fetching.py ingestion/tests/test_fetching.py
git commit -m "feat(ingestion): httpx fetcher with polite UA, timeout, retries (network-isolated)"
```

---

## Task 5: Сервисы приёма (хэш, сырьё, обнаружение изменений, черновик, конвейер, ручной импорт)

**Files:**
- Create: `ingestion/services.py`
- Test: `ingestion/tests/test_services.py`

- [ ] **Step 1: Написать падающие тесты**

`ingestion/tests/test_services.py`:
```python
from datetime import date, datetime, timezone

import httpx
import pytest

from documents.models import Redaction
from documents.tests.factories import make_document, make_redaction
from ingestion.models import IngestionJob, RawSource
from ingestion.parsing import parse_document
from ingestion.services import (
    IngestionTarget,
    PublishedRedactionExists,
    compute_hash,
    content_changed,
    create_draft_from_parsed,
    import_manual,
    ingest_target,
    store_raw_source,
)

HTML = b"<h1>Kodeks</h1><p>\xd0\xa1\xd1\x82\xd0\xb0\xd1\x82\xd1\x8c\xd1\x8f 81. Uvolnenie</p><p>tekst</p>"
# (HTML с «Статья 81. Uvolnenie» в UTF-8; текст статьи — «tekst».)


def _client_returning(content, content_type="text/html"):
    def handler(request):
        return httpx.Response(200, headers={"content-type": content_type}, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_compute_hash_is_stable():
    assert compute_hash(b"abc") == compute_hash(b"abc")
    assert compute_hash(b"abc") != compute_hash(b"abd")


@pytest.mark.django_db
def test_store_raw_source_sets_hash():
    rs = store_raw_source("k", b"hello", "text/plain", "https://e.test/")
    assert rs.content_hash == compute_hash(b"hello")
    assert RawSource.objects.count() == 1


@pytest.mark.django_db
def test_content_changed_detects_new_then_same():
    assert content_changed("k", compute_hash(b"v1")) is True
    store_raw_source("k", b"v1", "text/plain", "")
    assert content_changed("k", compute_hash(b"v1")) is False
    assert content_changed("k", compute_hash(b"v2")) is True


@pytest.mark.django_db
def test_create_draft_creates_articles_with_anchors():
    doc = make_document(slug="d1", official_number="1")
    parsed = parse_document(
        "Статья 81. Расторжение\nтекст статьи".encode("utf-8"), "text/plain"
    )
    red = create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.is_current is False
    assert red.parser_version == "1.0"
    art = red.articles.get()
    assert art.number == "81"
    assert art.anchor == "st-81"  # anchor сгенерирован в Article.save()


@pytest.mark.django_db
def test_create_draft_is_idempotent_on_same_date():
    doc = make_document(slug="d2", official_number="2")
    parsed = parse_document("Статья 1. A\nx".encode("utf-8"), "text/plain")
    r1 = create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    r2 = create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    assert r1.pk == r2.pk                       # та же редакция (upsert)
    assert Redaction.objects.filter(document=doc).count() == 1
    assert r2.articles.count() == 1             # статьи не задублировались


@pytest.mark.django_db
def test_create_draft_never_overwrites_published():
    doc = make_document(slug="d3", official_number="3")
    published = make_redaction(doc, redaction_date=date(2024, 1, 1), full_text="старое")
    published.publish()
    parsed = parse_document("Статья 1. A\nновое".encode("utf-8"), "text/plain")
    with pytest.raises(PublishedRedactionExists):
        create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    published.refresh_from_db()
    assert published.full_text == "старое"      # не перезаписано


@pytest.mark.django_db
def test_ingest_target_success_creates_draft_and_job():
    doc = make_document(slug="tk", official_number="197-ФЗ")
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk")
    job = ingest_target(target, client=_client_returning(HTML))
    assert job.status == IngestionJob.Status.SUCCESS
    assert job.produced_redaction is not None
    assert job.raw_source is not None
    assert job.finished_at is not None
    red = job.produced_redaction
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.articles.filter(number="81").exists()


@pytest.mark.django_db
def test_ingest_target_skips_unchanged_on_second_run():
    doc = make_document(slug="tk2", official_number="x")
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk2")
    first = ingest_target(target, client=_client_returning(HTML))
    second = ingest_target(target, client=_client_returning(HTML))
    assert first.status == IngestionJob.Status.SUCCESS
    assert second.status == IngestionJob.Status.SKIPPED
    assert RawSource.objects.filter(target_key="tk2").count() == 1   # дубль не сохранён
    assert Redaction.objects.filter(document=doc).count() == 1


@pytest.mark.django_db
def test_ingest_target_quarantines_on_fetch_error():
    doc = make_document(slug="tk3", official_number="y")
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk3")

    def handler(request):
        return httpx.Response(500, content=b"boom")

    job = ingest_target(target, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert job.status == IngestionJob.Status.FAILED
    assert "HTTPStatusError" in job.error
    assert Redaction.objects.filter(document=doc).count() == 0       # ничего не опубликовано/создано


@pytest.mark.django_db
def test_ingest_target_quarantines_but_keeps_raw_when_published_blocks_draft():
    doc = make_document(slug="tk4", official_number="z")
    # Уже есть опубликованная редакция на сегодняшнюю дату → черновик создать нельзя.
    today = datetime.now(timezone.utc).date()
    published = make_redaction(doc, redaction_date=today, full_text="официальное")
    published.publish()
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk4")
    job = ingest_target(target, client=_client_returning(HTML))
    assert job.status == IngestionJob.Status.FAILED
    assert "PublishedRedactionExists" in job.error
    # Карантин, а не тихий пропуск: сырьё сохранено для повторного разбора.
    assert RawSource.objects.filter(target_key="tk4").count() == 1


@pytest.mark.django_db
def test_import_manual_creates_draft_from_text():
    doc = make_document(slug="man", official_number="m")
    content = "Статья 1. Общие положения\nНастоящий акт регулирует.".encode("utf-8")
    red = import_manual(doc, content=content, content_type="text/plain")
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.articles.get().number == "1"
    assert RawSource.objects.filter(target_key="manual:man").count() == 1
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -v`
Expected: FAIL — модуля `ingestion.services` нет.

- [ ] **Step 3: Реализовать сервисы**

`ingestion/services.py`:
```python
import hashlib
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from documents.models import Article, Document, Redaction
from ingestion.fetching import fetch
from ingestion.models import IngestionJob, RawSource
from ingestion.parsing import PARSER_VERSION, parse_document


class PublishedRedactionExists(Exception):
    """Поднимается, когда приём попытался бы перезаписать опубликованную редакцию."""


@dataclass
class IngestionTarget:
    document: Document
    url: str
    target_key: str


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_raw_source(target_key, content, content_type="", source_url=""):
    return RawSource.objects.create(
        target_key=target_key,
        content=content,
        content_hash=compute_hash(content),
        content_type=content_type,
        source_url=source_url,
    )


def content_changed(target_key, content_hash):
    """True, если для цели ещё нет сырья или хэш отличается от последнего."""
    latest = (
        RawSource.objects.filter(target_key=target_key).order_by("-fetched_at").first()
    )
    return latest is None or latest.content_hash != content_hash


def create_draft_from_parsed(document, parsed, *, raw_source=None, redaction_date=None):
    """Создать/обновить ЧЕРНОВИК редакции из разобранного содержимого.
    Идемпотентно по (document, redaction_date). Опубликованную редакцию НИКОГДА не трогает."""
    redaction_date = redaction_date or timezone.now().date()
    with transaction.atomic():
        existing = Redaction.objects.filter(
            document=document, redaction_date=redaction_date
        ).first()
        if existing and existing.review_status == Redaction.ReviewStatus.PUBLISHED:
            raise PublishedRedactionExists(
                f"Опубликованная редакция от {redaction_date} не перезаписывается автоматически."
            )
        if existing:
            redaction = existing
            redaction.articles.all().delete()
        else:
            redaction = Redaction(document=document, redaction_date=redaction_date)
        redaction.full_text = parsed.full_text
        redaction.review_status = Redaction.ReviewStatus.DRAFT
        redaction.is_current = False
        redaction.ingested_at = timezone.now()
        redaction.parser_version = PARSER_VERSION
        redaction.raw_source = raw_source
        redaction.save()
        for parsed_article in parsed.articles:
            Article.objects.create(
                redaction=redaction,
                kind=Article.Kind.ARTICLE,
                number=parsed_article.number,
                title=parsed_article.title,
                text=parsed_article.text,
                order=parsed_article.order,
            )
    return redaction


def _finish(job, log_lines):
    job.log = "\n".join(log_lines)
    job.finished_at = timezone.now()
    job.save()
    return job


def ingest_target(target, *, client=None):
    """Конвейер по одной цели: скачать → сохранить сырьё → обнаружить изменение →
    разобрать → создать черновик. Сбой изолирован (FAILED-job), сырьё сохраняется (карантин)."""
    job = IngestionJob.objects.create(
        target_key=target.target_key,
        status=IngestionJob.Status.SUCCESS,
        started_at=timezone.now(),
    )
    log_lines = []
    try:
        result = fetch(target.url, client=client)
        log_lines.append(f"Скачано {len(result.content)} байт с {result.source_url}.")
        content_hash = compute_hash(result.content)
        if not content_changed(target.target_key, content_hash):
            job.status = IngestionJob.Status.SKIPPED
            log_lines.append("Содержимое не изменилось — пропуск.")
            return _finish(job, log_lines)
        raw = store_raw_source(
            target.target_key, result.content, result.content_type, result.source_url
        )
        job.raw_source = raw
        parsed = parse_document(result.content, result.content_type)
        log_lines.append(f"Разобрано статей: {len(parsed.articles)}.")
        redaction = create_draft_from_parsed(target.document, parsed, raw_source=raw)
        job.produced_redaction = redaction
        log_lines.append(f"Создан черновик редакции #{redaction.pk}.")
    except Exception as exc:  # изоляция: сбой одной цели не валит пакет
        job.status = IngestionJob.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"
        log_lines.append("ОШИБКА — см. поле error.")
    return _finish(job, log_lines)


def import_manual(document, *, content, content_type="text/plain", source_url="", redaction_date=None):
    """Запасной путь: куратор подаёт байты/текст напрямую → черновик редакции."""
    raw = store_raw_source(f"manual:{document.slug}", content, content_type, source_url)
    parsed = parse_document(content, content_type)
    return create_draft_from_parsed(
        document, parsed, raw_source=raw, redaction_date=redaction_date
    )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add ingestion/services.py ingestion/tests/test_services.py
git commit -m "feat(ingestion): ingest pipeline + manual import (idempotent drafts, quarantine, audit)"
```

---

## Task 6: Management-команды (`ingest_url`, `import_document`)

**Files:**
- Create: `ingestion/management/__init__.py`, `ingestion/management/commands/__init__.py`, `ingestion/management/commands/ingest_url.py`, `ingestion/management/commands/import_document.py`
- Test: `ingestion/tests/test_commands.py`

- [ ] **Step 1: Написать падающие тесты**

`ingestion/tests/test_commands.py`:
```python
from datetime import datetime, timezone

import pytest
from django.core.management import call_command

from documents.models import Redaction
from documents.tests.factories import make_document
from ingestion.fetching import FetchResult


@pytest.mark.django_db
def test_ingest_url_command_creates_draft(monkeypatch):
    doc = make_document(slug="tkurl", official_number="1")
    from ingestion import services

    def fake_fetch(url, client=None):
        return FetchResult(
            content="Статья 1. Тест\nтело".encode("utf-8"),
            content_type="text/html",
            source_url=url,
            fetched_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(services, "fetch", fake_fetch)
    call_command("ingest_url", "--slug", "tkurl", "--url", "https://e.test/d")
    red = Redaction.objects.get(document=doc)
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.articles.get().number == "1"


@pytest.mark.django_db
def test_ingest_url_command_unknown_slug_errors():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("ingest_url", "--slug", "nope", "--url", "https://e.test/d")


@pytest.mark.django_db
def test_import_document_command_creates_draft(tmp_path):
    doc = make_document(slug="tkfile", official_number="2")
    f = tmp_path / "act.txt"
    f.write_text("Статья 1. Общие положения\nНастоящий акт регулирует.", encoding="utf-8")
    call_command("import_document", "--slug", "tkfile", "--file", str(f))
    red = Redaction.objects.get(document=doc)
    assert red.articles.get().number == "1"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_commands.py -v`
Expected: FAIL — команд `ingest_url` / `import_document` нет.

- [ ] **Step 3: Реализовать команды**

`ingestion/management/__init__.py`: пустой файл.
`ingestion/management/commands/__init__.py`: пустой файл.

`ingestion/management/commands/ingest_url.py`:
```python
from django.core.management.base import BaseCommand, CommandError

from documents.models import Document
from ingestion.services import IngestionTarget, ingest_target


class Command(BaseCommand):
    help = "Скачать URL и создать черновик редакции для документа (по slug)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="slug существующего документа")
        parser.add_argument("--url", required=True, help="URL официального источника")
        parser.add_argument(
            "--key", default="", help="target_key (по умолчанию совпадает со slug)"
        )

    def handle(self, *args, **options):
        try:
            document = Document.objects.get(slug=options["slug"])
        except Document.DoesNotExist:
            raise CommandError(f"Документ со slug '{options['slug']}' не найден.")
        target = IngestionTarget(
            document=document,
            url=options["url"],
            target_key=options["key"] or options["slug"],
        )
        job = ingest_target(target)
        self.stdout.write(self.style.SUCCESS(f"Job #{job.pk}: {job.status}"))
        if job.log:
            self.stdout.write(job.log)
        if job.error:
            self.stderr.write(job.error)
```

`ingestion/management/commands/import_document.py`:
```python
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from documents.models import Document
from ingestion.services import import_manual


class Command(BaseCommand):
    help = "Ручной импорт: создать черновик редакции из локального файла (HTML/текст)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="slug существующего документа")
        parser.add_argument("--file", required=True, help="путь к файлу (.html/.htm/.txt)")

    def handle(self, *args, **options):
        try:
            document = Document.objects.get(slug=options["slug"])
        except Document.DoesNotExist:
            raise CommandError(f"Документ со slug '{options['slug']}' не найден.")
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")
        content = path.read_bytes()
        content_type = (
            "text/html" if path.suffix.lower() in {".html", ".htm"} else "text/plain"
        )
        redaction = import_manual(document, content=content, content_type=content_type)
        self.stdout.write(
            self.style.SUCCESS(
                f"Создан черновик #{redaction.pk} ({redaction.articles.count()} статей)."
            )
        )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_commands.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add ingestion/management ingestion/tests/test_commands.py
git commit -m "feat(ingestion): ingest_url + import_document management commands"
```

---

## Task 7: Admin — аудит сырья и запусков (read-only)

**Files:**
- Create: `ingestion/admin.py`
- Test: `ingestion/tests/test_admin.py`

- [ ] **Step 1: Написать падающие тесты**

`ingestion/tests/test_admin.py`:
```python
import pytest
from django.urls import reverse


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "curator", "c@example.test", "pass12345"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_rawsource_changelist_loads(staff_client):
    url = reverse("admin:ingestion_rawsource_changelist")
    assert staff_client.get(url).status_code == 200


@pytest.mark.django_db
def test_ingestionjob_changelist_loads(staff_client):
    url = reverse("admin:ingestion_ingestionjob_changelist")
    assert staff_client.get(url).status_code == 200
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_admin.py -v`
Expected: FAIL — модели не зарегистрированы в admin (`NoReverseMatch`).

- [ ] **Step 3: Реализовать admin**

`ingestion/admin.py`:
```python
from django.contrib import admin

from ingestion.models import IngestionJob, RawSource


@admin.register(RawSource)
class RawSourceAdmin(admin.ModelAdmin):
    list_display = ("target_key", "content_type", "content_hash", "fetched_at")
    list_filter = ("content_type",)
    search_fields = ("target_key", "source_url")
    readonly_fields = (
        "target_key",
        "content_type",
        "content_hash",
        "source_url",
        "fetched_at",
    )
    exclude = ("content",)  # сырые байты не показываем в форме


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display = (
        "target_key",
        "status",
        "started_at",
        "finished_at",
        "produced_redaction",
    )
    list_filter = ("status",)
    search_fields = ("target_key",)
    readonly_fields = (
        "target_key",
        "status",
        "started_at",
        "finished_at",
        "log",
        "error",
        "raw_source",
        "produced_redaction",
    )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_admin.py -v`
Expected: оба теста passed.

- [ ] **Step 5: Commit**

```bash
git add ingestion/admin.py ingestion/tests/test_admin.py
git commit -m "feat(ingestion): read-only admin for RawSource + IngestionJob audit"
```

---

## Task 8: Сквозная проверка и приёмка

**Files:**
- Test: полный прогон; ручная приёмка.

- [ ] **Step 1: Полный прогон тестов**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: все тесты passed (Планы 1+2 + ~24 новых теста Плана 3a).

- [ ] **Step 2: Django system check**

Run: `.venv\Scripts\python.exe manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 3: Линт**

Run: `.venv\Scripts\python.exe -m ruff check ingestion`
Expected: `All checks passed!` (при наличии замечаний — поправить и повторить).

- [ ] **Step 4: Ручная приёмка ручного импорта (для человека; субагент это НЕ запускает)**

```powershell
.venv\Scripts\python.exe manage.py shell -c "from documents.models import Document; Document.objects.get_or_create(slug='tk-ingest-demo', defaults={'doc_type':'code','title':'ТК РФ (приём-демо)','official_number':'197-ФЗ','status':'in_force'})"
.venv\Scripts\python.exe manage.py import_document --slug tk-ingest-demo --file ingestion/fixtures_raw/sample_tk.html
```
Expected: «Создан черновик #N (2 статей).»

Затем (интерактивно):
```powershell
.venv\Scripts\python.exe manage.py runserver
```
- Открыть `http://localhost:8000/admin/` → войти куратором → **Ingestion → Raw sources**: виден элемент `manual:tk-ingest-demo`; **Ingestion → Ingestion jobs**: (для ручного импорта job не создаётся — это нормально, провенанс через RawSource).
- **Documents → Redactions**: виден черновик с 2 статьями (80, 81), `review_status = draft`, привязан `raw_source`.
- Выбрать черновик → действие «Опубликовать выбранные редакции» → перейти на `http://localhost:8000/search/` → запрос «работодателя» → акт найден (после публикации вектор индексируется).
- Ctrl+C — остановить сервер.

- [ ] **Step 5: Commit (если остались незакоммиченные изменения)**

```bash
git status
# при необходимости:
git add -A && git commit -m "test(ingestion): full acceptance pass for Plan 3a"
```

---

## Self-Review (выполнено при написании плана)

**1. Покрытие спецификации:**
- §5 RawSource (`target_key`, `content`, `content_hash`, `fetched_at`, `content_type`, `source_url`) → Task 2. ✓
- §5 IngestionJob (`target_key`, `status`, `started_at`, `finished_at`, `log`, `error`, `produced_redaction`) + `raw_source` (диаграмма «использует RawSource») → Task 2. ✓
- §5 Redaction.`raw_source` → RawSource → Task 2 (FK). ✓
- §6 конвейер: Fetch (Task 4) → Store raw (Task 5 `store_raw_source`) → Change detection (Task 5 `content_changed`) → Parse (Task 3) → Draft redaction (Task 5 `create_draft_from_parsed`, только `draft`). ✓
- §6 «опубликованный текст никогда не перезаписывается» → `PublishedRedactionExists` (Task 5) + тест. ✓
- §6 надёжность: изоляция по цели (try/except в `ingest_target`), карантин не тихий пропуск (FAILED-job + сохранённое сырьё — тест `..._keeps_raw_when_published_blocks_draft`), идемпотентность (хэш + upsert по `(document, redaction_date)` — тест), аудит (`IngestionJob` каждый запуск). ✓
- §6 ручной импорт (запасной путь) → `import_manual` + команда `import_document` (Task 5–6). ✓
- §6 библиотеки: httpx ✓; HTML — beautifulsoup4 (на `html.parser`, осознанно без `lxml`); PDF (`pdfminer.six`) — отложено (отмечено в шапке). ✓ (с отклонением)
- §12 тестирование: парсер на сохранённой фикстуре (Task 3), раздельность fetch/parse (Task 3 vs 4), draft-поток (Task 5), без обращения к живому сайту (MockTransport). ✓
- §13 обработка ошибок: изоляция, карантин, идемпотентность, аудит, «никогда не публиковать автоматически». ✓
- Отложено явно (3b связи, 3c расписание, 3d шлифовка курирования/diff/форма импорта/reparse-action, PDF, иерархия разделов) — перечислено в шапке. ✓

**2. Плейсхолдеры:** не найдено — везде полный код/команды.

**3. Согласованность имён/типов:**
- `IngestionTarget(document, url, target_key)` — одинаково в сервисе (Task 5) и командах (Task 6).
- `FetchResult(content, content_type, source_url, fetched_at)` — определён в Task 4, используется в Task 5 (тесты monkeypatch) и Task 6 (тест).
- `ParsedDocument(full_text, title, articles)` / `ParsedArticle(number, title, text, order)` — Task 3, используются в Task 5.
- `create_draft_from_parsed(document, parsed, *, raw_source=None, redaction_date=None)` — сигнатура едина в `ingest_target`, `import_manual`, тестах.
- `IngestionJob.Status` (`success`/`failed`/`skipped`) — едины в модели, сервисе, тестах, admin.
- `RawSource.target_key` — соглашение: авто-цель = `slug`, ручной импорт = `manual:<slug>` (Task 5–6, тесты).
- `PARSER_VERSION = "1.0"` — Task 3, проверяется в тесте Task 5.
- Anchor статьи (`st-81`) генерируется в `Article.save()` (План 1) — `create_draft_from_parsed` создаёт статьи через `Article.objects.create()` (не `bulk_create`), чтобы `save()` отработал. ✓ (тест `..._with_anchors`).

**Известные ограничения v1 (для будущих под-планов, не блокеры):**
- `redaction_date` черновика по умолчанию = дата приёма (реальную дату редакции проставляет куратор). Если на эту дату уже есть **черновик** — он обновляется (это и есть идемпотентность); если **опубликованная** — приём уходит в карантин (FAILED). Разведение «реальная дата vs дата приёма» — задел на 3d.
- Парсер извлекает плоский список статей; разделы/главы и реквизиты из метаданных источника — позже (реквизиты пока заводит куратор/сид).
- `content` сырья хранится в БД (BinaryField). Для скромного корпуса v1 — приемлемо; при росте — вынести в файловое хранилище.

**Отложенные находки код-ревью 3a (адресовать в указанных под-планах):**
- **3d:** повторный разбор, дающий **0 статей** для документа, у которого они были (источник сменил формат), молча затирает прежние статьи черновика. Сейчас смягчено гейтом куратора (это черновик). Добавить предупреждение/защиту вместе с действием «переразобрать из RawSource».
- **3d:** эвристика заголовка (`parse_document`) берёт первую нестатейную строку — на реальном HTML `pravo.gov.ru` это может быть «хлебная крошка»/навигация. Настроить парсер на реальных фикстурах при наполнении корпуса.
- **3d:** `RawSourceAdmin`/`IngestionJobAdmin` сделать по-настоящему read-only (`has_add_permission`/`has_change_permission = False`) — **вместе** с admin-действием «переразобрать», иначе действие будет заблокировано правами.
- **Покрытие тестами:** карантин-с-сохранением-сырья проверен на пути `PublishedRedactionExists`; при добавлении новых стадий разбора (3b) добавить тест на сохранение `RawSource` при сбое разбора.

---

## Execution Handoff

План сохранён в `docs/superpowers/plans/2026-06-06-lawiot-plan-3a-ingestion-core.md`. Способ исполнения — субагентами по задачам (как в Планах 1–2) или инлайн с чекпойнтами.
