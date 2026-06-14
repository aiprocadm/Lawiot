# B1 — Детект новой редакции по нормализованному тексту: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить детект изменения источника с хэша сырых байт на хэш нормализованного текста, чтобы дребезг HTML-разметки не вызывал ложных «новых редакций», а реальная поправка надёжно приводила к новой публикации.

**Architecture:** В `ingestion/services.py` change-detection переходит на `text_hash` (SHA-256 от `html_to_text(...)`). Новое поле `RawSource.text_hash` хранит его. `parse_document` расщепляется на `html_to_text` + `parse_text`, чтобы нормализовать содержимое один раз. Гейт авто-публикации, дедуп по дате, извлечение связей, diff и лента изменений не меняются.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django, httpx (MockTransport в тестах), BeautifulSoup (`html.parser`).

**Спека:** `docs/superpowers/specs/2026-06-14-ingestion-change-detection-hardening-design.md`

---

## Файловая структура

| Файл | Ответственность | Действие |
|---|---|---|
| `ingestion/parsing.py` | Нормализация + разбор | Modify: добавить `parse_text`, `parse_document` → тонкая обёртка |
| `ingestion/services.py` | Конвейер приёма + change-detection | Modify: `text_digest`, `compute_text_hash`, `text_changed`, `store_raw_source`, `ingest_target`; удалить `content_changed` |
| `ingestion/models.py` | Модели | Modify: поле `RawSource.text_hash` |
| `ingestion/migrations/0002_rawsource_text_hash.py` | Схема | Create (через makemigrations) |
| `ingestion/tests/test_change_detection.py` | Тесты детекта + сквозной | Create |
| `ingestion/tests/test_services.py` | Существующие тесты приёма | Modify: убрать `content_changed`, поправить импорт |

**Замечание по окружению:** django_db-тесты требуют Postgres. Host-контейнер `lawiot-db` на порту 5433 (или WSL-фолбэк). Команда прогона: `.venv\Scripts\python.exe -m pytest <путь> --create-db -q`.

---

## Task 1: Расщепить `parse_document` на `html_to_text` + `parse_text`

**Files:**
- Modify: `ingestion/parsing.py:134-148`
- Test: `ingestion/tests/test_parsing.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `ingestion/tests/test_parsing.py`:

```python
def test_parse_text_parses_already_normalized_text():
    from ingestion.parsing import parse_text

    text = "Кодекс\nСтатья 1. Цели\nтекст статьи"
    parsed = parse_text(text)
    assert parsed.full_text == text
    assert parsed.title == "Кодекс"
    nums = [a.number for a in parsed.articles if a.kind == "article"]
    assert nums == ["1"]


def test_parse_document_delegates_to_parse_text():
    from ingestion.parsing import parse_document, parse_text

    html = b"<p>\xd0\x9a\xd0\xbe\xd0\xb4\xd0\xb5\xd0\xba\xd1\x81</p><p>\xd0\xa1\xd1\x82\xd0\xb0\xd1\x82\xd1\x8c\xd1\x8f 1. X</p><p>t</p>"
    doc = parse_document(html, "text/html")
    # parse_document(content) == parse_text(html_to_text(content))
    assert doc.full_text == parse_text(doc.full_text).full_text
    assert [a.number for a in doc.articles] == ["1"]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_parse_text_parses_already_normalized_text -q`
Expected: FAIL — `ImportError: cannot import name 'parse_text'`.

- [ ] **Step 3: Реализовать `parse_text`, сделать `parse_document` обёрткой**

Заменить функцию `parse_document` в `ingestion/parsing.py` (строки ~134-148) на:

```python
def parse_text(text: str) -> ParsedDocument:
    """Разбор УЖЕ нормализованного текста (результат html_to_text):
    структура (разделы/главы/статьи) + заголовок-эвристика + реквизиты."""
    articles = parse_structure(text)
    title = detect_title(text)
    num = NUMBER_HINT_RE.search(text)
    dt = DATE_HINT_RE.search(text)
    return ParsedDocument(
        full_text=text,
        title=title,
        articles=articles,
        detected_number=num.group(1) if num else "",
        detected_date=dt.group(1) if dt else "",
        detected_redaction_date=detect_redaction_date(text),
    )


def parse_document(content: bytes, content_type: str = "text/html") -> ParsedDocument:
    """Полный разбор: нормализовать содержимое и разобрать (тонкая обёртка над parse_text)."""
    return parse_text(html_to_text(content, content_type))
```

- [ ] **Step 4: Запустить тесты парсинга — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -q`
Expected: PASS (новые два + все существующие).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/parsing.py ingestion/tests/test_parsing.py
git commit -m "refactor(parsing): расщепить parse_document на html_to_text + parse_text

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Хелперы хэша нормализованного текста (`text_digest`, `compute_text_hash`)

**Files:**
- Modify: `ingestion/services.py` (импорт из parsing; новые функции рядом с `compute_hash`)
- Test: `ingestion/tests/test_change_detection.py` (Create)

- [ ] **Step 1: Написать падающий тест**

Создать `ingestion/tests/test_change_detection.py`:

```python
import httpx
import pytest

from ingestion.parsing import html_to_text
from ingestion.services import compute_text_hash, text_digest

# Два HTML, различающиеся ТОЛЬКО несущественным токеном в разметке
# (span без текста → html_to_text даёт идентичный текст).
HTML_A = b"<html><body><span id='t' data-v='111'></span><p>Statya 1. Celi</p><p>tekst</p></body></html>"
HTML_B = b"<html><body><span id='t' data-v='999'></span><p>Statya 1. Celi</p><p>tekst</p></body></html>"
# HTML с реально другим текстом.
HTML_C = b"<html><body><span id='t' data-v='111'></span><p>Statya 1. Celi</p><p>drugoy tekst</p></body></html>"


def _client_returning(content, content_type="text/html"):
    def handler(request):
        return httpx.Response(200, headers={"content-type": content_type}, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_text_hash_ignores_markup_churn():
    assert compute_text_hash(HTML_A, "text/html") == compute_text_hash(HTML_B, "text/html")


def test_text_hash_detects_real_text_change():
    assert compute_text_hash(HTML_A, "text/html") != compute_text_hash(HTML_C, "text/html")


def test_text_digest_matches_compute_text_hash():
    assert text_digest(html_to_text(HTML_A, "text/html")) == compute_text_hash(HTML_A, "text/html")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_change_detection.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_text_hash'`.

- [ ] **Step 3: Реализовать хелперы**

В `ingestion/services.py` обновить импорт из parsing (строка ~11):

```python
from ingestion.parsing import PARSER_VERSION, html_to_text, parse_document, parse_text
```

Добавить рядом с `compute_hash` (после строки ~34):

```python
def text_digest(text: str) -> str:
    """SHA-256 нормализованного текста. Триггер «новая редакция» (стабилен к дребезгу разметки)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_text_hash(content: bytes, content_type: str = "") -> str:
    return text_digest(html_to_text(content, content_type))
```

(`parse_document` остаётся в импорте — он используется в `import_manual`/`reparse_redaction`; `parse_text` понадобится в Task 4.)

- [ ] **Step 4: Запустить — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_change_detection.py -q`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/services.py ingestion/tests/test_change_detection.py
git commit -m "feat(ingestion): хелперы text_digest/compute_text_hash для детекта по тексту

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Поле `RawSource.text_hash` + миграция + `store_raw_source` его проставляет

**Files:**
- Modify: `ingestion/models.py:9` (после `content_hash`)
- Create: `ingestion/migrations/0002_rawsource_text_hash.py` (через makemigrations)
- Modify: `ingestion/services.py` (`store_raw_source`)
- Test: `ingestion/tests/test_change_detection.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `ingestion/tests/test_change_detection.py`:

```python
@pytest.mark.django_db
def test_store_raw_source_sets_text_hash():
    from ingestion.services import store_raw_source

    rs = store_raw_source("k", HTML_A, "text/html", "https://e.test/")
    assert rs.text_hash == compute_text_hash(HTML_A, "text/html")
    assert rs.content_hash  # сырой хэш по-прежнему заполнен
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_change_detection.py::test_store_raw_source_sets_text_hash --create-db -q`
Expected: FAIL — `TypeError`/`FieldError`: у `RawSource` нет `text_hash`.

- [ ] **Step 3: Добавить поле модели**

В `ingestion/models.py` после строки `content_hash = ...` (строка 9):

```python
    content_hash = models.CharField(max_length=64, db_index=True)
    text_hash = models.CharField(max_length=64, blank=True, db_index=True)
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `.venv\Scripts\python.exe manage.py makemigrations ingestion`
Expected: создан `ingestion/migrations/0002_rawsource_text_hash.py` (AddField `text_hash`).

- [ ] **Step 5: Обновить `store_raw_source`**

Заменить `store_raw_source` в `ingestion/services.py` (строки ~37-44):

```python
def store_raw_source(target_key, content, content_type="", source_url="", text_hash=None):
    return RawSource.objects.create(
        target_key=target_key,
        content=content,
        content_hash=compute_hash(content),
        text_hash=text_hash if text_hash is not None else compute_text_hash(content, content_type),
        content_type=content_type,
        source_url=source_url,
    )
```

- [ ] **Step 6: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_change_detection.py --create-db -q`
Expected: PASS (4 теста).

- [ ] **Step 7: Коммит**

```bash
git add ingestion/models.py ingestion/migrations/0002_rawsource_text_hash.py ingestion/services.py ingestion/tests/test_change_detection.py
git commit -m "feat(ingestion): RawSource.text_hash + store_raw_source проставляет его

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `text_changed` + перевод `ingest_target` на детект по тексту; удалить `content_changed`

**Files:**
- Modify: `ingestion/services.py` (`text_changed`; `ingest_target`; удалить `content_changed`)
- Modify: `ingestion/tests/test_services.py` (убрать `content_changed` из импорта; удалить его тест)
- Test: `ingestion/tests/test_change_detection.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `ingestion/tests/test_change_detection.py`:

```python
@pytest.mark.django_db
def test_text_changed_new_then_same():
    from ingestion.services import store_raw_source, text_changed

    h = compute_text_hash(HTML_A, "text/html")
    assert text_changed("k", h) is True
    store_raw_source("k", HTML_A, "text/html", "", text_hash=h)
    assert text_changed("k", h) is False
    assert text_changed("k", compute_text_hash(HTML_C, "text/html")) is True


@pytest.mark.django_db
def test_ingest_target_skips_on_markup_only_churn():
    from documents.tests.factories import make_document
    from ingestion.models import IngestionJob, RawSource
    from ingestion.services import IngestionTarget, ingest_target

    doc = make_document(slug="churn", official_number="x")
    t = IngestionTarget(document=doc, url="https://e.test/x", target_key="churn")
    first = ingest_target(t, client=_client_returning(HTML_A))
    second = ingest_target(t, client=_client_returning(HTML_B))  # отличается только токеном
    assert first.status == IngestionJob.Status.SUCCESS
    assert second.status == IngestionJob.Status.SKIPPED
    assert RawSource.objects.filter(target_key="churn").count() == 1
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_change_detection.py::test_ingest_target_skips_on_markup_only_churn --create-db -q`
Expected: FAIL — `ImportError: cannot import name 'text_changed'` (и/или churn даёт SUCCESS дважды, т.к. сырой хэш различается).

- [ ] **Step 3: Добавить `text_changed`, удалить `content_changed`**

В `ingestion/services.py` заменить функцию `content_changed` (строки ~47-50) на:

```python
def text_changed(target_key, text_hash) -> bool:
    """True, если для цели ещё нет сырья или хэш нормализованного текста отличается."""
    latest = RawSource.objects.filter(target_key=target_key).order_by("-fetched_at").first()
    return latest is None or latest.text_hash != text_hash
```

- [ ] **Step 4: Перевести `ingest_target` на детект по тексту**

В `ingestion/services.py`, в `ingest_target`, заменить блок скачивания/детекта/разбора
(строки ~141-152, от `result = fetch(...)` до `parsed = parse_document(...)`) на:

```python
        result = fetch(target.url, client=client)
        log_lines.append(f"Скачано {len(result.content)} байт с {result.source_url}.")
        text = html_to_text(result.content, result.content_type)
        text_hash = text_digest(text)
        if not text_changed(target.target_key, text_hash):
            job.status = IngestionJob.Status.SKIPPED
            log_lines.append("Нормализованный текст не изменился — пропуск.")
            return _finish(job, log_lines)
        raw = store_raw_source(
            target.target_key,
            result.content,
            result.content_type,
            result.source_url,
            text_hash=text_hash,
        )
        job.raw_source = raw
        parsed = parse_text(text)
```

(Остальная часть `ingest_target` — счёт статей, гейт, авто-публикация, связи — без изменений.)

- [ ] **Step 5: Поправить существующие тесты**

В `ingestion/tests/test_services.py`:
- В импорте из `ingestion.services` (строки ~10-22) **удалить** строку `content_changed,`.
- **Удалить** тест `test_content_changed_detects_new_then_same` (строки ~47-52) — его заменяет `test_text_changed_new_then_same` в новом файле.

- [ ] **Step 6: Убедиться, что `content_changed` больше нигде не используется**

Run: `.venv\Scripts\python.exe -m pytest ingestion/ --create-db -q`
Expected: PASS — весь пакет `ingestion`. Если что-то падает с `content_changed` — заменить вызов на `text_changed` или удалить устаревшее обращение.

- [ ] **Step 7: Коммит**

```bash
git add ingestion/services.py ingestion/tests/test_services.py ingestion/tests/test_change_detection.py
git commit -m "feat(ingestion): детект новой редакции по нормализованному тексту (text_changed)

Сырой SHA-256 заменён на хэш html_to_text: дребезг разметки ИПС больше не
даёт ложного «изменилось». content_changed удалён.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Сквозной тест — вторая редакция публикуется, вытесняет первую, diff и лента

**Files:**
- Test: `ingestion/tests/test_change_detection.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `ingestion/tests/test_change_detection.py`:

```python
from datetime import date

# Две сводные редакции одного акта. R2 = изменён текст ст.1 + новая дата поправки.
R1_HTML = (
    "<h1>Кодекс</h1>"
    "<p>(В редакции Федерального закона от 29.12.2025 № 500-ФЗ)</p>"
    "<p>Статья 1. Предмет</p><p>старый текст</p>"
    "<p>Статья 2. Сфера</p><p>текст два</p>"
).encode("utf-8")

R2_HTML = (
    "<h1>Кодекс</h1>"
    "<p>(В редакции Федерального закона от 15.01.2026 № 5-ФЗ)</p>"
    "<p>Статья 1. Предмет</p><p>НОВЫЙ текст</p>"
    "<p>Статья 2. Сфера</p><p>текст два</p>"
).encode("utf-8")


@pytest.mark.django_db
def test_second_redaction_publishes_supersedes_and_diffs():
    from documents.diffing import diff_articles
    from documents.models import Redaction
    from documents.tests.factories import make_document
    from ingestion.models import IngestionJob
    from ingestion.services import IngestionTarget, ingest_target

    doc = make_document(slug="e2e", official_number="500-ФЗ", auto_publish=True)
    t = IngestionTarget(document=doc, url="https://e.test/e2e", target_key="e2e")

    # R1 — первая публикация (текущей нет → гейт пропускает)
    job1 = ingest_target(t, client=_client_returning(R1_HTML))
    assert job1.status == IngestionJob.Status.SUCCESS
    r1 = Redaction.objects.get(document=doc, redaction_date=date(2025, 12, 29))
    assert r1.review_status == Redaction.ReviewStatus.PUBLISHED
    assert r1.is_current is True

    # R2 — новая редакция (новый текст ст.1, новая дата → новый text_hash)
    job2 = ingest_target(t, client=_client_returning(R2_HTML))
    assert job2.status == IngestionJob.Status.SUCCESS
    r2 = Redaction.objects.get(document=doc, redaction_date=date(2026, 1, 15))
    assert r2.review_status == Redaction.ReviewStatus.PUBLISHED
    assert r2.is_current is True
    assert r2.published_at is not None

    r1.refresh_from_db()
    assert r1.is_current is False  # вытеснена

    # diff R1→R2: ст.1 изменена, ст.2 без изменений
    diffs = {
        d.number: d.status
        for d in diff_articles(list(r1.articles.all()), list(r2.articles.all()))
    }
    assert diffs["1"] == "changed"
    assert diffs["2"] == "same"

    # R2 в ленте опубликованных
    published_pks = list(
        Redaction.objects.filter(review_status=Redaction.ReviewStatus.PUBLISHED).values_list(
            "pk", flat=True
        )
    )
    assert r2.pk in published_pks

    # повторный приём тем же R2 → текст не изменился → SKIPPED
    job3 = ingest_target(t, client=_client_returning(R2_HTML))
    assert job3.status == IngestionJob.Status.SKIPPED
```

- [ ] **Step 2: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_change_detection.py::test_second_redaction_publishes_supersedes_and_diffs --create-db -q`
Expected: PASS. (Логика уже реализована в Tasks 1-4; этот тест — характеризация сквозного сценария «обновление при публикации».)

Если падает — диагностировать: дата редакции (`detect_redaction_date` ждёт «от ДД.ММ.ГГГГ № N-ФЗ»), гейт (`_is_safe_to_publish`: 2 ст. ≥ 0.8·2), `auto_publish=True`.

- [ ] **Step 3: Коммит**

```bash
git add ingestion/tests/test_change_detection.py
git commit -m "test(ingestion): сквозной сценарий 2-й редакции (публикация→вытеснение→diff)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Финальная проверка

- [ ] **Прогнать весь пакет ingestion и documents**

Run: `.venv\Scripts\python.exe -m pytest ingestion/ documents/ --create-db -q`
Expected: PASS (все, включая существующие).

- [ ] **Линт**

Run: `.venv\Scripts\python.exe -m ruff check .`
Expected: чисто.

- [ ] **Замечание по dev-БД:** миграцию `ingestion/0002` на общую dev-БД применяет пользователь (`manage.py migrate ingestion`) — классификатор миграций блокирует Claude. Первый пост-деплойный `sweep` разово переингестит каждую цель (text_hash="" на старых строках) — ожидаемо и безвредно (дедуп по дате не создаёт дублей).

---

## Самопроверка плана (выполнена при написании)

- **Покрытие спеки:** §4.1 поле → Task 3; §4.2 parse_text → Task 1; §4.3 хелперы/store_raw_source/text_changed/ingest_target → Tasks 2-4; §5 дребезг-skip → Task 4; §6 юнит+сквозной+skip-on-rerun+регресс → Tasks 2,4,5; §7 миграция → Task 3. Пробелов нет.
- **Плейсхолдеры:** нет (весь код приведён).
- **Согласованность типов:** `text_digest(text)→str`, `compute_text_hash(content, ct)→str`, `text_changed(target_key, text_hash)→bool`, `store_raw_source(..., text_hash=None)`, `parse_text(text)→ParsedDocument` — единообразны во всех задачах.
