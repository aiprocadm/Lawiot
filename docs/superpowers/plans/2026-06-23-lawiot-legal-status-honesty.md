# Слой правового статуса и честности (Р1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать Lawiot честным к происхождению текста — пометить уровень/источник/статус текста и показать дисклеймер + ссылку на первоисточник на всех материалах (ТЗ §0.1 Р1/Р2, КП-12, НФТ-8).

**Architecture:** Полностью аддитивный слой. Новые поля модели с дефолтами (`official`/`federal`) бэкфилят существующие строки; UI-правки аддитивны и под `{% if %}`. Ядро (парсинг, консолидация, поиск, публикация) не меняется.

**Tech Stack:** Django 5.2, PostgreSQL, pytest-django, Pico CSS, python-docx.

**Spec:** `docs/superpowers/specs/2026-06-23-legal-status-honesty-design.md`

**Прогон тестов:** `pwsh -File run-tests.ps1 <pytest-args>` (поднимает Docker Postgres `lawiot-db`). При мёртвом Docker — WSL-фолбэк (см. память `wsl-postgres-test-fallback`). Все новые тесты — в изолированном `documents/tests/test_legal_status.py`; hotspot `documents/tests/test_views.py` НЕ трогаем.

---

## Карта файлов

| Файл | Что делаем |
|---|---|
| `documents/models.py` | +`Document.SourceStatus`, `Document.Level`, поля `source_status`/`level`/`region_code`; +`Redaction.TextStatus`, поле `text_status` |
| `documents/migrations/0016_legal_status_fields.py` | автогенерируемая миграция (4 поля) |
| `ingestion/services.py` | в `create_draft_from_parsed` явно проставить `text_status=OFFICIAL` (1 строка) |
| `templates/base.html` | глобальный футер-дисклеймер + CSS бейджа происхождения |
| `templates/documents/document_detail.html` | ссылка «Официальный источник», паспорт-строки `Уровень`/`Источник`/`Происхождение текста` |
| `templates/documents/document_print.html` | строка дисклеймера |
| `documents/views.py:document_export_docx` | унифицированный дисклеймер + строка источника |
| `documents/seed/labor_law.py` | явные `level`/`source_status` в SEED_ACTS |
| `documents/tests/test_legal_status.py` | новые тесты (создаётся) |

---

## Task 1: Поля модели + миграция

**Files:**
- Modify: `documents/models.py` (класс `Document` ~10-57, класс `Redaction` ~59-104)
- Create: `documents/migrations/0016_legal_status_fields.py` (через makemigrations)
- Test: `documents/tests/test_legal_status.py`

- [ ] **Step 1: Написать падающий тест дефолтов полей**

Создать `documents/tests/test_legal_status.py`:

```python
import datetime

import pytest
from django.utils import timezone

from documents.models import Article, Document, Redaction


@pytest.mark.django_db
def test_new_document_defaults_to_federal_official():
    doc = Document.objects.create(slug="d1", doc_type="code", title="Акт")
    assert doc.level == Document.Level.FEDERAL
    assert doc.source_status == Document.SourceStatus.OFFICIAL
    assert doc.region_code == ""


@pytest.mark.django_db
def test_new_redaction_defaults_to_official_text():
    doc = Document.objects.create(slug="d2", doc_type="code", title="Акт")
    red = Redaction.objects.create(document=doc, redaction_date=datetime.date(2020, 1, 1))
    assert red.text_status == Redaction.TextStatus.OFFICIAL
    assert red.get_text_status_display() == "Официальная редакция"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py -v`
Expected: FAIL — `AttributeError: type object 'Document' has no attribute 'Level'`.

- [ ] **Step 3: Добавить поля в `Document`**

В `documents/models.py` в класс `Document`, рядом с существующими `class DocType` / `class Status`, добавить:

```python
    class SourceStatus(models.TextChoices):
        OFFICIAL = "official", "Официальный источник"
        UNOFFICIAL = "unofficial", "Неофициальный источник"

    class Level(models.TextChoices):
        FEDERAL = "federal", "Федеральный"
        REGIONAL = "regional", "Региональный"
        MUNICIPAL = "municipal", "Муниципальный"
```

И поля (после строки `status = models.CharField(... default=Status.IN_FORCE)`):

```python
    source_status = models.CharField(
        max_length=20, choices=SourceStatus.choices, default=SourceStatus.OFFICIAL
    )
    level = models.CharField(
        max_length=20,
        choices=Level.choices,
        default=Level.FEDERAL,
        help_text="Уровень нормативки (Р2). Региональный/муниципальный — на будущее.",
    )
    region_code = models.CharField(
        max_length=10, blank=True, help_text="Код субъекта РФ; пусто на федеральном уровне."
    )
```

- [ ] **Step 4: Добавить поле в `Redaction`**

В класс `Redaction`, рядом с `class ReviewStatus`, добавить:

```python
    class TextStatus(models.TextChoices):
        OFFICIAL = "official", "Официальная редакция"
        RECONSTRUCTION = "reconstruction", "Автоматическая реконструкция"
```

И поле (после `review_status = models.CharField(...)`):

```python
    text_status = models.CharField(
        max_length=20,
        choices=TextStatus.choices,
        default=TextStatus.OFFICIAL,
        help_text=(
            "Происхождение текста (Р1): official — из официального сводного раздела ИПС; "
            "reconstruction — собрано движком/куратором. Ортогонально review_status."
        ),
    )
```

- [ ] **Step 5: Сгенерировать миграцию**

Run: `.venv\Scripts\python.exe manage.py makemigrations documents -n legal_status_fields`
Expected: создан `documents/migrations/0016_legal_status_fields.py` с `AddField` ×4. Зависит от `0015_merge_20260620_1458`.

- [ ] **Step 6: Запустить тесты — зелёные**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py -v`
Expected: PASS (оба теста).

- [ ] **Step 7: Коммит**

```bash
git add documents/models.py documents/migrations/0016_legal_status_fields.py documents/tests/test_legal_status.py
git commit -m "feat(documents): поля source_status/level/region_code/text_status (Р1/Р2)"
```

---

## Task 2: Явная пометка официальности при приёме

**Files:**
- Modify: `ingestion/services.py:create_draft_from_parsed` (~64-109)
- Test: `documents/tests/test_legal_status.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_legal_status.py`:

```python
@pytest.mark.django_db
def test_ingested_draft_marked_official():
    from ingestion.parsing import parse_text
    from ingestion.services import create_draft_from_parsed

    doc = Document.objects.create(slug="d3", doc_type="code", title="Акт")
    parsed = parse_text("Статья 1. Право на труд.", "code")
    red = create_draft_from_parsed(doc, parsed, redaction_date=datetime.date(2022, 1, 1))
    assert red.text_status == Redaction.TextStatus.OFFICIAL
```

- [ ] **Step 2: Запустить — убедиться, что проходит уже сейчас (дефолт) или падает**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_ingested_draft_marked_official -v`
Expected: PASS (поле дефолтится `official`). Тест закрепляет инвариант; Step 3 делает пометку явной, чтобы будущая смена дефолта не сломала приём.

- [ ] **Step 3: Проставить статус явно**

В `ingestion/services.py`, функция `create_draft_from_parsed`, после строки
`redaction.review_status = Redaction.ReviewStatus.DRAFT` добавить:

```python
        # Источник приёма — официальный сводный раздел ИПС (Р1.1): текст официальный.
        # Явно (не полагаясь на дефолт поля) — оба пути (ingest_target/import_manual)
        # идут через эту функцию.
        redaction.text_status = Redaction.TextStatus.OFFICIAL
```

- [ ] **Step 4: Запустить — зелёный**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_ingested_draft_marked_official -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add ingestion/services.py documents/tests/test_legal_status.py
git commit -m "feat(ingestion): явно помечать черновик редакции official (Р1)"
```

---

## Task 3: Глобальный дисклеймер в футере (КП-12/НФТ-8)

**Files:**
- Modify: `templates/base.html` (после `{% block content %}{% endblock %}` ~52, и CSS ~10-26)
- Test: `documents/tests/test_legal_status.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_legal_status.py`:

```python
DISCLAIMER_MARK = "не является источником официального опубликования"


@pytest.mark.django_db
def test_disclaimer_in_footer_on_pages(client, django_user_model):
    user = django_user_model.objects.create_user("r-foot", password="x")
    client.force_login(user)
    Document.objects.create(slug="d-foot", doc_type="code", title="Акт")
    # список актов и страница поиска — обе наследуют base.html
    assert DISCLAIMER_MARK in client.get("/").content.decode()
    assert DISCLAIMER_MARK in client.get("/search/").content.decode()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_disclaimer_in_footer_on_pages -v`
Expected: FAIL (дисклеймера нет).

- [ ] **Step 3: Добавить футер в `base.html`**

В `templates/base.html` заменить блок

```html
    {% block content %}{% endblock %}
  </main>
```

на

```html
    {% block content %}{% endblock %}
    <footer>
      <small>
        Lawiot — справочный навигатор по открытым правовым данным.
        Не является источником официального опубликования и не заменяет
        юридическую консультацию. Официальный источник:
        <a href="http://pravo.gov.ru" rel="noopener" target="_blank">pravo.gov.ru</a>.
      </small>
    </footer>
  </main>
```

- [ ] **Step 4: Добавить CSS бейджа происхождения** (понадобится в Task 4; делаем здесь, в общем блоке стилей)

В `templates/base.html` в `<style>` после строки `.status-not_in_force { background: #757575; }` добавить:

```css
  .text-status-badge { display: inline-block; padding: 0.1rem 0.5rem;
    border-radius: 0.4rem; font-size: 0.85em; }
  .text-status-official { background: #e8f5e9; color: #1b5e20; }
  .text-status-reconstruction { background: #fff3e0; color: #e65100; }
```

- [ ] **Step 5: Запустить — зелёный**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_disclaimer_in_footer_on_pages -v`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add templates/base.html documents/tests/test_legal_status.py
git commit -m "feat(ui): глобальный дисклеймер в футере + стиль бейджа происхождения (КП-12)"
```

---

## Task 4: Карточка акта — источник, уровень, происхождение текста

**Files:**
- Modify: `templates/documents/document_detail.html` (header `<p>` ~8-11, паспорт `<dl>` ~12-32)
- Test: `documents/tests/test_legal_status.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `documents/tests/test_legal_status.py`:

```python
def _published_doc(*, source_url="", text_status="official"):
    doc = Document.objects.create(
        slug="card-act",
        doc_type="federal_law",
        title="Карточный акт",
        official_number="1-ФЗ",
        status="in_force",
        source_url=source_url,
    )
    Redaction.objects.create(
        document=doc,
        redaction_date=datetime.date(2020, 1, 2),
        review_status="published",
        is_current=True,
        published_at=timezone.now(),
        full_text="текст",
        text_status=text_status,
    )
    return doc


@pytest.mark.django_db
def test_card_shows_level_source_and_origin(client, django_user_model):
    user = django_user_model.objects.create_user("r-card", password="x")
    client.force_login(user)
    _published_doc()
    html = client.get("/doc/card-act/").content.decode()
    assert "Уровень" in html
    assert "Федеральный" in html
    assert "Источник" in html
    assert "Официальный источник" in html  # значение source_status display
    assert "Происхождение текста" in html
    assert "Официальная редакция" in html


@pytest.mark.django_db
def test_card_source_link_present_only_when_url_set(client, django_user_model):
    user = django_user_model.objects.create_user("r-link", password="x")
    client.force_login(user)
    _published_doc(source_url="http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=1&print=1")
    html = client.get("/doc/card-act/").content.decode()
    assert 'href="http://pravo.gov.ru/proxy/ips/?doc_itself=&amp;nd=1&amp;print=1"' in html


@pytest.mark.django_db
def test_card_no_source_link_when_url_blank(client, django_user_model):
    user = django_user_model.objects.create_user("r-nolink", password="x")
    client.force_login(user)
    _published_doc(source_url="")
    html = client.get("/doc/card-act/").content.decode()
    assert ">Официальный первоисточник<" not in html  # ссылка-якорь отсутствует
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py -k card -v`
Expected: FAIL (полей нет в шаблоне).

- [ ] **Step 3: Добавить ссылку «Официальный первоисточник» в шапку**

В `templates/documents/document_detail.html` заменить блок

```html
    <p>
      <a href="{% url 'document_print' document.slug %}">Версия для печати</a> ·
      <a href="{% url 'assistant' %}?doc={{ document.slug }}">Спросить ассистента об этом акте</a>
    </p>
```

на

```html
    <p>
      <a href="{% url 'document_print' document.slug %}">Версия для печати</a> ·
      <a href="{% url 'assistant' %}?doc={{ document.slug }}">Спросить ассистента об этом акте</a>
      {% if document.source_url %} ·
      <a href="{{ document.source_url }}" rel="noopener" target="_blank">Официальный первоисточник</a>
      {% endif %}
    </p>
```

- [ ] **Step 4: Добавить паспорт-строки уровня/источника/происхождения**

В том же файле заменить строку

```html
      <dt>Действующая редакция</dt><dd>{{ redaction.redaction_date|date:"d.m.Y" }}</dd>
```

на

```html
      <dt>Уровень</dt><dd>{{ document.get_level_display }}</dd>
      <dt>Источник</dt><dd>{{ document.get_source_status_display }}</dd>
      <dt>Действующая редакция</dt><dd>{{ redaction.redaction_date|date:"d.m.Y" }}</dd>
      <dt>Происхождение текста</dt>
      <dd><span class="text-status-badge text-status-{{ redaction.text_status }}">{{ redaction.get_text_status_display }}</span></dd>
```

- [ ] **Step 5: Запустить — зелёные**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py -k card -v`
Expected: PASS (3 теста).

- [ ] **Step 6: Коммит**

```bash
git add templates/documents/document_detail.html documents/tests/test_legal_status.py
git commit -m "feat(ui): карточка — уровень, источник, происхождение текста, ссылка на первоисточник"
```

---

## Task 5: Дисклеймер на странице печати

**Files:**
- Modify: `templates/documents/document_print.html` (`.meta` блок ~26-30)
- Test: `documents/tests/test_legal_status.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_legal_status.py`:

```python
@pytest.mark.django_db
def test_print_page_has_disclaimer(client, django_user_model):
    user = django_user_model.objects.create_user("r-print", password="x")
    client.force_login(user)
    _published_doc()
    html = client.get("/doc/card-act/print/").content.decode()
    assert DISCLAIMER_MARK in html
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_print_page_has_disclaimer -v`
Expected: FAIL (печать — standalone-шаблон, не наследует base.html, дисклеймера нет).

- [ ] **Step 3: Добавить дисклеймер в печать**

В `templates/documents/document_print.html` после блока `<p class="meta"> … </p>` (перед `{% for node in article_tree %}`) добавить:

```html
  <p class="meta">
    Не является источником официального опубликования и не заменяет юридическую
    консультацию. Официальный источник: pravo.gov.ru.
  </p>
```

- [ ] **Step 4: Запустить — зелёный**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_print_page_has_disclaimer -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add templates/documents/document_print.html documents/tests/test_legal_status.py
git commit -m "feat(ui): дисклеймер на странице печати (КП-12)"
```

---

## Task 6: Дисклеймер и источник в docx-экспорте

**Files:**
- Modify: `documents/views.py:document_export_docx` (~322-329)
- Test: `documents/tests/test_legal_status.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_legal_status.py`:

```python
@pytest.mark.django_db
def test_docx_export_has_disclaimer(client, django_user_model):
    import io

    from docx import Document as Dx

    user = django_user_model.objects.create_user("r-docx", password="x")
    client.force_login(user)
    _published_doc(source_url="http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=1&print=1")
    resp = client.get("/doc/card-act/export.docx")
    assert resp.status_code == 200
    dx = Dx(io.BytesIO(resp.content))
    texts = "\n".join(p.text for p in dx.paragraphs)
    assert DISCLAIMER_MARK in texts
    assert "pravo.gov.ru" in texts
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_docx_export_has_disclaimer -v`
Expected: FAIL (нынешний дисклеймер docx — другая формулировка, нет `DISCLAIMER_MARK`).

- [ ] **Step 3: Обновить дисклеймер docx + добавить источник**

В `documents/views.py:document_export_docx` заменить строку

```python
    docx.add_paragraph("Справочная информация на основе корпуса, не официальное опубликование.")
```

на

```python
    docx.add_paragraph(
        "Не является источником официального опубликования и не заменяет "
        "юридическую консультацию. Официальный источник: pravo.gov.ru."
    )
    if document.source_url:
        docx.add_paragraph(f"Официальный первоисточник: {document.source_url}")
```

- [ ] **Step 4: Запустить — зелёный**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_docx_export_has_disclaimer -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add documents/views.py documents/tests/test_legal_status.py
git commit -m "feat(ui): унифицированный дисклеймер + источник в docx-экспорте"
```

---

## Task 7: Явные level/source_status в сиде

**Files:**
- Modify: `documents/seed/labor_law.py` (4 словаря SEED_ACTS)
- Test: `documents/tests/test_legal_status.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_legal_status.py`:

```python
@pytest.mark.django_db
def test_seed_stamps_level_and_source_status():
    from django.core.management import call_command

    Document.objects.create(slug="tk-rf", doc_type="code", title="ТК РФ")
    call_command("seed_corpus")
    doc = Document.objects.get(slug="tk-rf")
    assert doc.level == Document.Level.FEDERAL
    assert doc.source_status == Document.SourceStatus.OFFICIAL
```

- [ ] **Step 2: Запустить — убедиться, что проходит уже сейчас или падает**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_seed_stamps_level_and_source_status -v`
Expected: PASS (дефолты модели уже дают federal/official). Step 3 фиксирует значения декларативно в сиде для будущих региональных актов.

- [ ] **Step 3: Добавить ключи в каждый словарь SEED_ACTS**

В `documents/seed/labor_law.py` в каждый из 4 словарей `SEED_ACTS` добавить строки (например, рядом с `"status": "in_force",`):

```python
        "level": "federal",
        "source_status": "official",
```

- [ ] **Step 4: Запустить — зелёный**

Run: `pwsh -File run-tests.ps1 documents/tests/test_legal_status.py::test_seed_stamps_level_and_source_status -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add documents/seed/labor_law.py documents/tests/test_legal_status.py
git commit -m "feat(seed): явные level=federal/source_status=official в SEED_ACTS"
```

---

## Финальная проверка

- [ ] **Весь набор тестов зелёный**

Run: `pwsh -File run-tests.ps1`
Expected: все прежние тесты + новые в `test_legal_status.py` проходят.

- [ ] **Линт и системная проверка чисты**

Run: `.venv\Scripts\python.exe -m ruff check .` → `All checks passed!`
Run: `.venv\Scripts\python.exe manage.py check` → `System check identified no issues`.

- [ ] **Открыть PR** (base main). Хвост после мержа: `manage.py migrate documents` (0016) + `manage.py seed_corpus` на dev-БД. NB: если параллельная сессия добавила миграцию в `documents` — после мержа решить `makemigrations --merge` (известный паттерн).

---

## Self-review (выполнено при написании плана)

- **Покрытие спеки:** §3 модель → Task 1; §4 установка значений → Task 2 + Task 7; §5 UI футер → Task 3, карточка → Task 4, печать → Task 5, docx → Task 6; §6 тесты → во всех тасках, изолированный файл. Все пункты покрыты.
- **Плейсхолдеры:** нет — каждый шаг содержит реальный код/команду/ожидаемый вывод.
- **Согласованность типов:** `Document.Level`/`Document.SourceStatus`/`Redaction.TextStatus` и `text_status`/`level`/`source_status`/`region_code` используются единообразно во всех тасках и тестах; `get_*_display` совпадают с метками choices.
