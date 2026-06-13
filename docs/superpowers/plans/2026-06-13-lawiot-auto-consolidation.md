# Автоматическая консолидация (auto-publish) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ежедневный sweep pravo.gov.ru сам публикует свежую сводную редакцию акта как текущую, без куратора, с защитой от мусора.

**Architecture:** Четыре точечных изменения поверх готового конвейера приёма (План 3c): извлечение реальной даты редакции из ИПС-цитат поправок; пер-актовый флаг `Document.auto_publish`; защитный гейт `_is_safe_to_publish`; шаг авто-публикации в `ingest_target`. Новых приложений нет; переиспользуются `Redaction.publish()`, `/changes/`, reader-diff, поиск.

**Tech Stack:** Django 5.2, PostgreSQL (FTS), pytest, httpx (MockTransport в тестах), BeautifulSoup (html.parser).

**Spec:** `docs/superpowers/specs/2026-06-13-auto-consolidation-design.md`

---

## Окружение и общие правила

- **Worktree:** `D:\Кодинг\Lawiot.worktrees\auto-consolidation`, ветка `feature/lawiot-auto-consolidation`. Все команды — отсюда.
- **Python:** ТОЛЬКО `D:\Кодинг\Lawiot\.venv\Scripts\python.exe` (голый `python` на этой машине — зависающая Store-заглушка).
- **Тесты:** нужен Postgres-контейнер `lawiot-db` (host-порт 5433). Если параллельная сессия гоняет pytest, возможна коллизия БД `test_lawiot` — тогда уникализировать имя теста через `DATABASE_URL` и `--create-db` (см. spec/память). Обычный прогон: `… -m pytest <path> -v`.
- **Линт по всему репо в конце:** `… -m ruff check .` и `… -m pytest` без путей (требование lint-scope — покрывать все приложения).
- Стиль кода — ручной перенос ~88 символов, как в окружающих файлах; комментарии по-русски, как в проекте.

---

## File Structure

| Файл | Ответственность | Действие |
|---|---|---|
| `ingestion/parsing.py` | `detect_redaction_date` + поле `ParsedDocument.detected_redaction_date` + проводка в `parse_document` | Modify |
| `ingestion/tests/test_parsing.py` | Юнит-тесты `detect_redaction_date` | Modify |
| `ingestion/tests/test_real_fixtures.py` | Проверка даты на живой фикстуре ТК РФ (2025-12-29) | Modify |
| `documents/models.py` | Поле `Document.auto_publish` | Modify |
| `documents/migrations/00XX_document_auto_publish.py` | Миграция поля | Create (через makemigrations) |
| `documents/admin.py` | `auto_publish` в `DocumentAdmin` | Modify |
| `documents/tests/test_models.py` | Тест дефолта `auto_publish` | Modify |
| `ingestion/services.py` | `AUTOPUBLISH_MIN_RATIO`, `_is_safe_to_publish`, шаг авто-публикации + `redaction_date` + `PublishedRedactionExists`→SKIPPED в `ingest_target` | Modify |
| `ingestion/tests/test_services.py` | Тесты гейта и авто-публикации | Modify |

---

## Task 1: Извлечение даты редакции (`detect_redaction_date`)

**Files:**
- Modify: `ingestion/parsing.py`
- Test: `ingestion/tests/test_parsing.py`, `ingestion/tests/test_real_fixtures.py`

Дата редакции = максимум дат из цитат поправок вида «(В редакции … от DD.MM.YYYY № NNN-ФЗ)». Привязка к `№ NNN-ФЗ/ФКЗ` отсекает посторонние даты из тела статей.

- [ ] **Step 1: Написать падающие юнит-тесты**

В конец `ingestion/tests/test_parsing.py` добавить (вверху файла должен быть `from datetime import date`; если его нет — добавить отдельной строкой к импортам):

```python
from datetime import date

from ingestion.parsing import detect_redaction_date


def test_detect_redaction_date_picks_max_citation_date():
    text = (
        "Одобрен 26 декабря 2001 года "
        "(В редакции федеральных законов от 24.07.2002 № 97-ФЗ, "
        "от 29.12.2025 № 999-ФЗ, от 30.06.2006 № 90-ФЗ)"
    )
    assert detect_redaction_date(text) == date(2025, 12, 29)


def test_detect_redaction_date_handles_fkz_and_letter_N():
    text = "часть дополнена (В редакции Федерального конституционного закона от 05.02.2014 N 2-ФКЗ)"
    assert detect_redaction_date(text) == date(2014, 2, 5)


def test_detect_redaction_date_ignores_bare_dates_without_law_number():
    # «голая» дата в теле статьи (без «№ NNN-ФЗ») не должна попасть в результат
    text = "Договор от 01.01.2099 действует со дня подписания."
    assert detect_redaction_date(text) is None


def test_detect_redaction_date_returns_none_when_no_citations():
    assert detect_redaction_date("Статья 1. Без единой цитаты закона.") is None
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -k detect_redaction_date -v`
Expected: FAIL — `ImportError: cannot import name 'detect_redaction_date'`.

- [ ] **Step 3: Реализовать**

В `ingestion/parsing.py` добавить `from datetime import date` к импортам (первая строка-импорт), затем рядом с `DATE_HINT_RE` (после строки 17) добавить:

```python
# Дата инкорпорированной поправки: «… от ДД.ММ.ГГГГ № NNN-ФЗ» (или -ФКЗ).
# Максимум таких дат = дата последней поправки = дата редакции (см. spec §4.1).
REDACTION_DATE_RE = re.compile(
    r"от (\d{2})\.(\d{2})\.(\d{4})\s*(?:№|N)\s*\d+-(?:ФКЗ|ФЗ)", re.IGNORECASE
)
```

Добавить функцию (например, сразу после `detect_title`):

```python
def detect_redaction_date(text: str) -> date | None:
    """Дата редакции = максимум дат из цитат поправок «… от ДД.ММ.ГГГГ № NNN-ФЗ».
    None, если ни одной цитаты-закона нет (тогда авто-публикация не сработает)."""
    dates = [
        date(int(y), int(m), int(d))
        for d, m, y in REDACTION_DATE_RE.findall(text or "")
    ]
    return max(dates) if dates else None
```

В `@dataclass ParsedDocument` добавить поле (после `detected_date`):

```python
    detected_redaction_date: date | None = None
```

В `parse_document` (после вычисления `dt`) пробросить:

```python
    return ParsedDocument(
        full_text=text,
        title=title,
        articles=articles,
        detected_number=num.group(1) if num else "",
        detected_date=dt.group(1) if dt else "",
        detected_redaction_date=detect_redaction_date(text),
    )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -k detect_redaction_date -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Тест на реальной фикстуре**

В `ingestion/tests/test_real_fixtures.py` добавить тест (файл уже читает фикстуру `tk_rf_real.html` и зовёт `parse_document`; повторить тот же способ чтения, что в существующих тестах файла — открыть `ingestion/fixtures_raw/tk_rf_real.html` в режиме `"rb"` и передать байты в `parse_document`):

```python
from datetime import date


def test_real_tk_rf_redaction_date_is_latest_amendment():
    from pathlib import Path

    from ingestion.parsing import parse_document

    content = Path("ingestion/fixtures_raw/tk_rf_real.html").read_bytes()
    parsed = parse_document(content, "text/html")
    assert parsed.detected_redaction_date == date(2025, 12, 29)
```

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_real_fixtures.py -k redaction_date -v`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add ingestion/parsing.py ingestion/tests/test_parsing.py ingestion/tests/test_real_fixtures.py
git commit -m "feat(ingestion): detect_redaction_date — дата редакции из цитат поправок (§17)"
```

---

## Task 2: Флаг `Document.auto_publish`

**Files:**
- Modify: `documents/models.py`
- Create: `documents/migrations/00XX_document_auto_publish.py` (через makemigrations)
- Modify: `documents/admin.py`
- Test: `documents/tests/test_models.py`

- [ ] **Step 1: Написать падающий тест**

В конец `documents/tests/test_models.py` добавить (вверху файла должны быть `import pytest` и `from documents.tests.factories import make_document` — если `make_document` не импортирован, добавить импорт):

```python
@pytest.mark.django_db
def test_document_auto_publish_defaults_false():
    doc = make_document()
    assert doc.auto_publish is False
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_models.py -k auto_publish -v`
Expected: FAIL — `AttributeError: 'Document' object has no attribute 'auto_publish'`.

- [ ] **Step 3: Добавить поле**

В `documents/models.py`, в классе `Document`, сразу после поля `auto_ingest` (строки 30–33) добавить:

```python
    auto_publish = models.BooleanField(
        default=False,
        help_text="Авто-публиковать свежую редакцию из source_url как текущую, без куратора.",
    )
```

- [ ] **Step 4: Создать миграцию**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe manage.py makemigrations documents`
Expected: создан файл `documents/migrations/00XX_document_auto_publish.py` (номер — следующий по порядку), `Add field auto_publish to document`.

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_models.py -k auto_publish -v`
Expected: PASS.

- [ ] **Step 6: Показать флаг в админке**

В `documents/admin.py`, в `DocumentAdmin`, заменить три строки на:

```python
    list_display = ("title", "doc_type", "official_number", "status", "auto_ingest", "auto_publish")
    list_filter = ("doc_type", "status", "auto_ingest", "auto_publish")
    list_editable = ("auto_ingest", "auto_publish")
```

(`search_fields` и `prepopulated_fields` оставить как есть.)

- [ ] **Step 7: Коммит**

```bash
git add documents/models.py documents/migrations/ documents/admin.py documents/tests/test_models.py
git commit -m "feat(documents): флаг auto_publish + миграция + админка (§17)"
```

---

## Task 3: Защитный гейт `_is_safe_to_publish`

**Files:**
- Modify: `ingestion/services.py`
- Test: `ingestion/tests/test_services.py`

Гейт не даёт опубликовать мусор: 0 статей и пустой текст, либо резкое падение числа статей против текущей редакции (обрезанный/ошибочный ответ источника).

- [ ] **Step 1: Написать падающие тесты**

В конец `ingestion/tests/test_services.py` добавить (вверху файла уже есть `from documents.tests.factories import make_document, make_redaction`; добавить к этому импорту `make_article`; в импорт из `ingestion.services` добавить `_is_safe_to_publish` и `AUTOPUBLISH_MIN_RATIO`):

```python
def _redaction_with_n_articles(n, **kwargs):
    red = make_redaction(**kwargs)
    for i in range(n):
        make_article(redaction=red, number=str(i + 1), order=i + 1)
    return red


@pytest.mark.django_db
def test_gate_blocks_zero_articles_and_empty_text():
    new = make_redaction(full_text="")
    assert _is_safe_to_publish(new, None) is False


@pytest.mark.django_db
def test_gate_allows_first_redaction_with_articles():
    new = _redaction_with_n_articles(3)
    assert _is_safe_to_publish(new, None) is True


@pytest.mark.django_db
def test_gate_allows_unstructured_text_when_no_current():
    new = make_redaction(full_text="Длинный неструктурированный текст акта.")
    assert _is_safe_to_publish(new, None) is True


@pytest.mark.django_db
def test_gate_blocks_sharp_drop_vs_current():
    doc = make_document()
    current = _redaction_with_n_articles(10, document=doc, redaction_date=date(2023, 1, 1))
    new = _redaction_with_n_articles(3, document=doc, redaction_date=date(2024, 1, 1))
    assert _is_safe_to_publish(new, current) is False  # 3 < 0.8 * 10


@pytest.mark.django_db
def test_gate_allows_equal_or_more_articles():
    doc = make_document()
    current = _redaction_with_n_articles(10, document=doc, redaction_date=date(2023, 1, 1))
    same = _redaction_with_n_articles(10, document=doc, redaction_date=date(2024, 1, 1))
    more = _redaction_with_n_articles(12, document=doc, redaction_date=date(2025, 1, 1))
    assert _is_safe_to_publish(same, current) is True
    assert _is_safe_to_publish(more, current) is True
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -k gate -v`
Expected: FAIL — `ImportError: cannot import name '_is_safe_to_publish'`.

- [ ] **Step 3: Реализовать гейт**

В `ingestion/services.py` после импортов (после строки 11) добавить константу:

```python
# Минимальная доля статей новой редакции от текущей при авто-публикации.
# Резкое падение = вероятно обрезанный/ошибочный ответ источника — не публикуем.
AUTOPUBLISH_MIN_RATIO = 0.8
```

И функцию (например, перед `ingest_target`):

```python
def _article_count(redaction):
    return redaction.articles.filter(kind=Article.Kind.ARTICLE).count()


def _is_safe_to_publish(new_redaction, current_redaction):
    """True, если новую редакцию безопасно авто-публиковать (см. spec §4.3)."""
    new_count = _article_count(new_redaction)
    has_text = bool((new_redaction.full_text or "").strip())
    if new_count == 0 and not has_text:
        return False
    if current_redaction is None:
        return new_count >= 1 or has_text
    current_count = _article_count(current_redaction)
    if current_count == 0:
        return True
    return new_count >= AUTOPUBLISH_MIN_RATIO * current_count
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -k gate -v`
Expected: PASS (6 тестов).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/services.py ingestion/tests/test_services.py
git commit -m "feat(ingestion): защитный гейт _is_safe_to_publish для авто-публикации (§17)"
```

---

## Task 4: Шаг авто-публикации в `ingest_target`

**Files:**
- Modify: `ingestion/services.py`
- Test: `ingestion/tests/test_services.py`

Проброс реальной даты в черновик; авто-публикация при `auto_publish` + дата + гейт; `PublishedRedactionExists` → SKIPPED.

- [ ] **Step 1: Написать падающие тесты**

В конец `ingestion/tests/test_services.py` добавить. HTML с цитатой-датой и одной статьёй:

```python
# HTML с цитатой поправки (→ дата редакции 15.03.2024) и одной статьёй.
HTML_DATED = (
    "<h1>Кодекс</h1>"
    "<p>(В редакции Федерального закона от 15.03.2024 № 50-ФЗ)</p>"
    "<p>Статья 1. Предмет</p><p>текст статьи</p>"
).encode("utf-8")

# Более свежая редакция: дата 20.06.2025, две статьи (рост → гейт пропускает).
HTML_DATED_NEWER = (
    "<h1>Кодекс</h1>"
    "<p>(В редакции Федерального закона от 20.06.2025 № 88-ФЗ)</p>"
    "<p>Статья 1. Предмет</p><p>текст</p>"
    "<p>Статья 2. Сфера</p><p>текст</p>"
).encode("utf-8")


@pytest.mark.django_db
def test_ingest_sets_real_redaction_date():
    doc = make_document(auto_publish=False)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    ingest_target(target, client=_client_returning(HTML_DATED))
    red = Redaction.objects.get(document=doc)
    assert red.redaction_date == date(2024, 3, 15)
    assert red.review_status == Redaction.ReviewStatus.DRAFT  # auto_publish off → черновик


@pytest.mark.django_db
def test_auto_publish_publishes_safe_redaction():
    doc = make_document(auto_publish=True)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    job = ingest_target(target, client=_client_returning(HTML_DATED))
    red = Redaction.objects.get(document=doc)
    assert red.review_status == Redaction.ReviewStatus.PUBLISHED
    assert red.is_current is True
    assert red.published_at is not None
    assert job.status == IngestionJob.Status.SUCCESS


@pytest.mark.django_db
def test_auto_publish_skips_when_no_date():
    # HTML без цитаты-закона → даты нет → не публикуем, остаётся черновик.
    html = b"<h1>Akt</h1><p>\xd0\xa1\xd1\x82\xd0\xb0\xd1\x82\xd1\x8c\xd1\x8f 1. X</p><p>t</p>"
    doc = make_document(auto_publish=True)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    ingest_target(target, client=_client_returning(html))
    red = Redaction.objects.get(document=doc)
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.is_current is False


@pytest.mark.django_db
def test_auto_publish_blocked_by_gate_keeps_draft():
    doc = make_document(auto_publish=True)
    # текущая опубликованная редакция с 10 статьями
    current = make_redaction(
        document=doc, redaction_date=date(2023, 1, 1),
        review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True,
    )
    for i in range(10):
        make_article(redaction=current, number=str(i + 1), order=i + 1)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    ingest_target(target, client=_client_returning(HTML_DATED))  # 1 статья < 0.8*10
    new = Redaction.objects.get(document=doc, redaction_date=date(2024, 3, 15))
    assert new.review_status == Redaction.ReviewStatus.DRAFT
    current.refresh_from_db()
    assert current.is_current is True  # текущая не тронута


@pytest.mark.django_db
def test_ingest_skips_when_same_date_already_published():
    doc = make_document(auto_publish=True)
    # уже опубликованная редакция на ту же дату, что даст HTML_DATED (15.03.2024)
    make_redaction(
        document=doc, redaction_date=date(2024, 3, 15),
        review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True,
    )
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    job = ingest_target(target, client=_client_returning(HTML_DATED))
    assert job.status == IngestionJob.Status.SKIPPED
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -k "auto_publish or real_redaction_date or same_date" -v`
Expected: FAIL (даты ставятся «сегодня»; авто-публикации нет; `PublishedRedactionExists` даёт FAILED, а не SKIPPED).

- [ ] **Step 3: Переписать `ingest_target`**

Заменить тело функции `ingest_target` (строки ~104–145) на:

```python
def ingest_target(target, *, client=None):
    """Конвейер по одной цели: скачать → сохранить сырьё → обнаружить изменение →
    разобрать → создать черновик → (если auto_publish и безопасно) опубликовать.
    Сбой изолирован (FAILED-job), сырьё сохраняется (карантин)."""
    job = IngestionJob.objects.create(
        target_key=target.target_key,
        status=IngestionJob.Status.FAILED,
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
        n_articles = sum(1 for a in parsed.articles if a.kind == "article")
        log_lines.append(
            f"Разобрано узлов структуры: {len(parsed.articles)} (статей: {n_articles})."
        )
        # текущую опубликованную редакцию фиксируем ДО создания черновика (для гейта)
        current = Redaction.objects.filter(
            document=target.document, is_current=True
        ).first()
        try:
            redaction = create_draft_from_parsed(
                target.document,
                parsed,
                raw_source=raw,
                redaction_date=parsed.detected_redaction_date,
            )
        except PublishedRedactionExists as exc:
            job.status = IngestionJob.Status.SKIPPED
            log_lines.append(str(exc))
            return _finish(job, log_lines)
        job.produced_redaction = redaction
        job.status = IngestionJob.Status.SUCCESS
        log_lines.append(f"Создан черновик редакции #{redaction.pk}.")
        try:
            n_links = extract_links_for_redaction(redaction)
            log_lines.append(f"Предложено связей: {n_links}.")
        except Exception as link_exc:  # извлечение связей вторично — не валит приём
            log_lines.append(f"Извлечение связей не удалось: {link_exc}")
        # авто-публикация (§17): только при флаге, извлечённой дате и пройденном гейте
        if target.document.auto_publish:
            if parsed.detected_redaction_date is None:
                log_lines.append("Авто-публикация пропущена: не извлечена дата редакции.")
            elif not _is_safe_to_publish(redaction, current):
                log_lines.append(
                    "Авто-публикация пропущена: гейт безопасности не пройден "
                    "(0 статей или резкое падение против текущей)."
                )
            else:
                redaction.publish()
                log_lines.append(f"Авто-опубликована редакция #{redaction.pk}.")
                try:
                    extract_links_for_redaction(redaction)  # после публикации: самоссылки
                except Exception as link_exc:
                    log_lines.append(f"Переизвлечение связей не удалось: {link_exc}")
    except Exception as exc:  # изоляция: сбой одной цели не валит пакет
        job.status = IngestionJob.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"
        log_lines.append("ОШИБКА — см. поле error.")
    return _finish(job, log_lines)
```

- [ ] **Step 4: Запустить новые тесты — убедиться, что проходят**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -k "auto_publish or real_redaction_date or same_date" -v`
Expected: PASS (5 тестов).

- [ ] **Step 5: Прогнать весь файл services — нет регрессий**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -v`
Expected: PASS (старые тесты приёма + новые). Если упадёт старый тест на дату по умолчанию — проверить, что его HTML без цитаты-закона (тогда дата = «сегодня», поведение не изменилось).

- [ ] **Step 6: Коммит**

```bash
git add ingestion/services.py ingestion/tests/test_services.py
git commit -m "feat(ingestion): авто-публикация свежей редакции в ingest_target (§17)"
```

---

## Task 5: Полная проверка репозитория

**Files:** нет (только прогон).

- [ ] **Step 1: Линт всего репо**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check .`
Expected: `All checks passed!`. Исправить любые E402/F401 в тронутых файлах.

- [ ] **Step 2: Формат тронутых файлов**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff format --check ingestion/ documents/`
Если падает только на НЕ тронутых нами файлах (преекзистинг-дрейф) — игнорировать; на наших — прогнать `ruff format` по конкретному файлу и закоммитить.

- [ ] **Step 3: Весь тестовый набор**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest`
(При коллизии с параллельной сессией — добавить уникальный `DATABASE_URL` + `--create-db`, см. раздел «Окружение».)
Expected: всё зелёное. Базовая линия — 181 тест на main; ждём 181 + ~16 новых.

- [ ] **Step 4: Финальный коммит (если формат что-то менял)**

```bash
git add -A
git commit -m "chore: ruff-format тронутых файлов (auto-consolidation)"
```

---

## Выкатка (после merge, вручную пользователем)

НЕ часть кода — операционные шаги, требующие общей dev-БД и решения куратора:

1. Применить миграции на dev-БД: `manage.py migrate` (классификатор блокирует Claude на общей dev-БД — делает пользователь).
2. Dry-run: `manage.py ingest_url tk-rf` (или дождаться sweep), убедиться, что у черновика `redaction_date` = реальная (последняя поправка), а не «сегодня».
3. Только убедившись в дате — включить `auto_publish=True` для `tk-rf` в `documents/seed/labor_law.py` (отдельным PR/правкой) и в админке.
4. `sout-426-fz` оставить выключенным до приёмки его парсера.

---

## Self-Review (проверено при написании плана)

- **Покрытие spec:** §4.1 дата → Task 1; §4.2 флаг → Task 2; §4.3 гейт → Task 3; §4.4 + §5 поток + §6 ошибки (SKIPPED/гейт) → Task 4; §7 тесты → распределены по задачам + Task 5; §8 выкатка → раздел «Выкатка». Пробелов нет.
- **Плейсхолдеры:** отсутствуют — весь код приведён целиком.
- **Согласованность имён:** `detect_redaction_date`, `ParsedDocument.detected_redaction_date`, `_is_safe_to_publish`, `AUTOPUBLISH_MIN_RATIO`, `_article_count` — используются одинаково в реализации и тестах. `create_draft_from_parsed(..., redaction_date=...)` — сигнатура совпадает с существующей (строка 49 services.py).
- **Регрессии:** проброс `redaction_date=parsed.detected_redaction_date` для существующих тестов без цитат-законов даёт `None` → дефолт «сегодня» (прежнее поведение сохранено).
