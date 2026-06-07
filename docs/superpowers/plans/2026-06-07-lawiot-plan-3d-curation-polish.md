# Lawiot — План 3d: Шлифовка курирования (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Довести подсистему курирования до состояния «всё делается из браузера»: очередь ревью, текстовый diff «черновик↔текущая», публикация и переразбор из admin, форма ручного импорта; плюс три отложенных хвоста (Link `on_delete`, sanitize сниппетов поиска, bulk-переиндексация).

**Architecture:** Всё внутри Django admin (подход выбран на брейншторме). Новых приложений нет. Расширяем `documents/admin.py` (действия + кастомные admin-views через `get_urls`), добавляем чистые модули `documents/diffing.py`, `documents/admin_views.py`, `documents/forms.py`, `documents/signals.py`, сервис `ingestion.services.reparse_redaction`, шаблоны под `templates/admin/documents/redaction/`. Каркас публикации (`Redaction.publish()` — атомарно + переиндексация) и импорта (`ingestion.services.import_manual`) уже существует и переиспользуется как есть.

**Tech Stack:** Django (admin, ORM, templates), PostgreSQL FTS (`SearchVector`/`ts_headline`/`to_tsvector`), Python `difflib`, pytest-django. Без новых зависимостей.

---

## Контекст для исполнителя (что УЖЕ есть — не переписывать)

Прочти эти места перед стартом — план на них опирается:

- `documents/models.py`
  - `Redaction.publish()` (строки ~90–98): в одной транзакции снимает `is_current` с прежней текущей редакции того же документа, ставит `review_status=PUBLISHED`, `is_current=True`, вызывает `update_search_index()`. **Атомарная публикация + переиндексация уже готова.**
  - `Redaction.update_search_index()` (~100–113): пишет `search_vector` редакции (заголовок документа — вес A, `full_text` — вес B) и её статей (number/title — A, text — B), конфиг `russian`.
  - Поля `Redaction`: `redaction_date` (DateField, «Действует с»), `full_text`, `review_status` (`ReviewStatus.DRAFT`/`PUBLISHED`), `is_current`, `ingested_at` (DateTimeField, null), `parser_version`, `raw_source` (FK→`ingestion.RawSource`, `SET_NULL`), `search_vector`.
  - DB-инвариант: partial-unique `uniq_current_redaction_per_document` (одна `is_current=True` на документ).
  - `Article`: `redaction` FK, `kind`, `number`, `title`, `text`, `order`, `parent`, `anchor` (авто из `number` в `save()`), `search_vector`.
  - `Link`: `from_document` (CASCADE), `to_document` (FK→Document, **сейчас CASCADE**, `null=True`), `raw_citation`, `link_type`, `origin`, `status`, `context`.
- `ingestion/services.py`
  - `import_manual(document, *, content, content_type="text/plain", source_url="", redaction_date=None)` (~135): сохраняет сырьё → `parse_document` → `create_draft_from_parsed` → `extract_links_for_redaction`. Возвращает `Redaction`.
  - `create_draft_from_parsed(document, parsed, *, raw_source=None, redaction_date=None)` (~47): идемпотентно по `(document, redaction_date)`; если по этой дате уже **опубликованная** редакция — `raise PublishedRedactionExists`; если черновик — удаляет его статьи и пересоздаёт; иначе создаёт новый черновик.
  - `PublishedRedactionExists` (Exception, ~14).
- `ingestion/parsing.py`: `parse_document(content: bytes, content_type: str) -> Parsed`; `Parsed.full_text: str`, `Parsed.articles: list` где у статьи есть `.number/.title/.text/.order`; константа `PARSER_VERSION`. Маркер статьи в тексте — «Статья N.».
- `ingestion/models.py`: `RawSource(target_key, content [BinaryField], content_hash, content_type, source_url, fetched_at)`, обратная связь `redactions`; `IngestionJob(target_key, status [Status.SUCCESS/FAILED/SKIPPED], started_at, finished_at, log, error, raw_source, produced_redaction)`.
- `search/services.py`: `_headline(field, query)` (сейчас `start_sel="<mark>"`/`stop_sel="</mark>"`); `search_documents(...)` фильтрует `is_current=True AND review_status=PUBLISHED`; собирает `SearchResult(document, rank, snippet, article_anchor, article_label)` и кладёт сырой `snippet` напрямую.
- `templates/search/search.html:33`: `{{ r.snippet|safe }}`.
- `documents/management/commands/reindex_search.py`: цикл по опубликованным редакциям, на каждой `update_search_index()`.
- `documents/admin.py`: `RedactionAdmin` (есть `ArticleInline`, действие `publish_selected`), `LinkAdmin` (`confirm_selected`), `DocumentAdmin`.
- `ingestion/admin.py`: `RawSourceAdmin`, `IngestionJobAdmin` — `readonly_fields` есть, но `has_add/change/delete_permission` НЕ переопределены.

## Предусловия окружения (см. memory [[windows-python-env]], [[lawiot-lint-scope]])

- Python — только через venv: **`.venv\Scripts\python.exe`** (bare `python` на этой машине зависает на Store-заглушке).
- БД — Postgres в контейнере на порту **5433**; перед тестами поднять: `docker compose up -d db`. `DATABASE_URL` живёт в `.env`.
- Тесты гоняем **по всему репо** (без фильтра пути): `.venv\Scripts\python.exe -m pytest`. Линт: `.venv\Scripts\python.exe -m ruff check .`. Стартовый зелёный набор — **87 тестов**.
- Каждый коммит завершается строкой-трейлером:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Конвенция сообщений коммитов: `feat(app): …`, `fix(app): …`, `perf(app): …`, `style(app): …`, `test(app): …`.

---

## Карта файлов

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `ingestion/admin.py` | Modify | Полностью read-only аудит-админки (Task 1) |
| `ingestion/services.py` | Modify | `reparse_redaction` + `ReparseYieldedNothing` (Task 2) |
| `documents/admin.py` | Modify | Действие «Переразобрать» (Task 3); `get_urls`/`change_list_template` (Tasks 5,7,8) |
| `documents/diffing.py` | Create | Чистая логика diff по статьям (Task 4) |
| `documents/admin_views.py` | Create | Views: diff / очередь / импорт (Tasks 5,6,7,8) |
| `documents/forms.py` | Create | `ManualImportForm` (Task 8) |
| `documents/signals.py` | Create | `pre_delete` сохранение цитат (Task 9) |
| `documents/apps.py` | Modify | `ready()` подключает signals (Task 9) |
| `documents/models.py` | Modify | `Link.to_document` → `SET_NULL` (Task 9) |
| `documents/migrations/0008_*.py` | Create | AlterField для `Link.to_document` (Task 9) |
| `search/services.py` | Modify | Sanitize сниппетов (Task 10) |
| `documents/management/commands/reindex_search.py` | Modify | Bulk-переиндексация (Task 11) |
| `templates/admin/documents/redaction/diff.html` | Create | Шаблон diff (Task 5) |
| `templates/admin/documents/redaction/review_queue.html` | Create | Шаблон очереди (Task 7) |
| `templates/admin/documents/redaction/import_form.html` | Create | Шаблон формы импорта (Task 8) |
| `templates/admin/documents/redaction/change_list.html` | Create | Ссылки «Очередь»/«Импорт» в тулбаре (Task 7) |
| `documents/tests/test_*` , `ingestion/tests/test_*` | Create/Modify | Тесты по задачам |

Порядок: Tasks 1–8 — курирование (ядро), 9–11 — хвосты, 12 — финальная проверка. Задачи слабо связаны; коммитим после каждой.

---

### Task 1: Read-only аудит-админки (находка #1283)

**Files:**
- Modify: `ingestion/admin.py`
- Test: `ingestion/tests/test_admin.py`

- [ ] **Step 1: Написать падающие тесты**

В `ingestion/tests/test_admin.py` добавить (фикстура `staff_client` уже есть в файле):

```python
@pytest.mark.django_db
def test_rawsource_admin_blocks_add(staff_client):
    # has_add_permission=False должно давать 403 даже суперпользователю
    assert staff_client.get(reverse("admin:ingestion_rawsource_add")).status_code == 403


@pytest.mark.django_db
def test_ingestionjob_admin_blocks_add(staff_client):
    assert staff_client.get(reverse("admin:ingestion_ingestionjob_add")).status_code == 403
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_admin.py -q`
Expected: FAIL — сейчас add-страница отдаёт 200 (форма доступна).

- [ ] **Step 3: Сделать админки read-only**

В `ingestion/admin.py` добавить в **оба** класса (`RawSourceAdmin`, `IngestionJobAdmin`) методы:

```python
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

(`readonly_fields` оставить — они обеспечивают аккуратную view-страницу при `has_view_permission`, который по умолчанию True.)

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_admin.py -q`
Expected: PASS (включая прежние `*_changelist_loads` — changelist остаётся доступен на чтение).

- [ ] **Step 5: Commit**

```bash
git add ingestion/admin.py ingestion/tests/test_admin.py
git commit -m "feat(ingestion): read-only RawSource/IngestionJob admin (#1283)"
```

---

### Task 2: Сервис `reparse_redaction` + защита от затирания (находка #1281)

**Files:**
- Modify: `ingestion/services.py`
- Test: `ingestion/tests/test_services.py`

- [ ] **Step 1: Написать падающие тесты**

В `ingestion/tests/test_services.py` добавить:

```python
import pytest

from documents.models import Article, Document, Redaction
from ingestion.models import RawSource
from ingestion.services import (
    ReparseYieldedNothing,
    import_manual,
    reparse_redaction,
)


@pytest.mark.django_db
def test_reparse_restores_articles_from_raw():
    doc = Document.objects.create(doc_type="federal_law", title="Тест", official_number="1-ФЗ", slug="1-fz")
    red = import_manual(doc, content="Статья 1. Первая.\nСтатья 2. Вторая.".encode("utf-8"))
    assert red.articles.count() == 2
    red.articles.filter(number="2").delete()       # «потеряли» статью
    assert red.articles.count() == 1
    reparse_redaction(red)                          # переразбор из того же RawSource
    red.refresh_from_db()
    assert red.articles.count() == 2                # восстановлено


@pytest.mark.django_db
def test_reparse_zero_articles_does_not_wipe():
    doc = Document.objects.create(doc_type="federal_law", title="Тест", official_number="2-ФЗ", slug="2-fz")
    raw = RawSource.objects.create(
        target_key="manual:2-fz", content="Текст без статей".encode("utf-8"),
        content_hash="x", content_type="text/plain",
    )
    red = Redaction.objects.create(document=doc, redaction_date="2026-01-01", raw_source=raw)
    Article.objects.create(redaction=red, number="1", text="была статья", order=0)
    with pytest.raises(ReparseYieldedNothing):
        reparse_redaction(red)
    red.refresh_from_db()
    assert red.articles.count() == 1                # не затёрли


@pytest.mark.django_db
def test_reparse_without_raw_raises():
    doc = Document.objects.create(doc_type="federal_law", title="Тест", official_number="3-ФЗ", slug="3-fz")
    red = Redaction.objects.create(document=doc, redaction_date="2026-01-01", raw_source=None)
    with pytest.raises(ValueError):
        reparse_redaction(red)
```

(Текст `b"...без статей"` — кириллица в UTF-8; парсер не найдёт маркеров «Статья N.» → 0 статей.)

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -q -k reparse`
Expected: FAIL — `ImportError: cannot import name 'reparse_redaction'`.

- [ ] **Step 3: Реализовать сервис**

В `ingestion/services.py` добавить (рядом с `PublishedRedactionExists`):

```python
class ReparseYieldedNothing(Exception):
    """Переразбор дал 0 статей там, где они были — черновик не затираем."""


def reparse_redaction(redaction):
    """Переразобрать ЧЕРНОВИК из сохранённого RawSource (без повторного скачивания).
    Защита (#1281): если новый разбор даёт 0 статей, а у черновика статьи есть —
    отменяем, чтобы смена формата источника молча не стёрла данные куратора."""
    raw = redaction.raw_source
    if raw is None:
        raise ValueError("У редакции нет сохранённого RawSource — нечего переразбирать.")
    parsed = parse_document(bytes(raw.content), raw.content_type)
    if not parsed.articles and redaction.articles.exists():
        raise ReparseYieldedNothing(
            "Новый разбор дал 0 статей при наличии прежних — операция отменена."
        )
    return create_draft_from_parsed(
        redaction.document,
        parsed,
        raw_source=raw,
        redaction_date=redaction.redaction_date,
    )
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -q -k reparse`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add ingestion/services.py ingestion/tests/test_services.py
git commit -m "feat(ingestion): reparse_redaction service with zero-article guard (#1281)"
```

---

### Task 3: Действие admin «Переразобрать из RawSource»

**Files:**
- Modify: `documents/admin.py`
- Test: `documents/tests/test_curation_admin.py` (Create)

- [ ] **Step 1: Написать падающий тест**

Создать `documents/tests/test_curation_admin.py`:

```python
import pytest
from django.urls import reverse

from documents.models import Document
from ingestion.services import import_manual


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser("cur", "c@example.test", "pass12345")
    client.force_login(user)
    return client


@pytest.fixture
def draft_with_raw(db):
    doc = Document.objects.create(doc_type="federal_law", title="ТК", official_number="197-ФЗ", slug="197-fz")
    return import_manual(doc, content="Статья 1. Альфа.\nСтатья 2. Бета.".encode("utf-8"))


@pytest.mark.django_db
def test_reparse_action_runs(staff_client, draft_with_raw):
    draft_with_raw.articles.filter(number="2").delete()
    resp = staff_client.post(
        reverse("admin:documents_redaction_changelist"),
        {"action": "reparse_from_raw", "_selected_action": [str(draft_with_raw.pk)]},
    )
    assert resp.status_code == 302
    draft_with_raw.refresh_from_db()
    assert draft_with_raw.articles.count() == 2
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q`
Expected: FAIL — действия `reparse_from_raw` ещё нет (302 не наступит / KeyError действия).

- [ ] **Step 3: Добавить действие**

В `documents/admin.py` поправить шапку импортов и `RedactionAdmin`:

```python
from django.contrib import admin, messages

from documents.models import Article, Document, Link, Redaction
from ingestion.services import (
    PublishedRedactionExists,
    ReparseYieldedNothing,
    reparse_redaction,
)
```

В классе `RedactionAdmin` расширить `actions` и добавить метод:

```python
    actions = ["publish_selected", "reparse_from_raw"]

    @admin.action(description="Переразобрать из RawSource")
    def reparse_from_raw(self, request, queryset):
        done = skipped = 0
        for redaction in queryset:
            if redaction.review_status != Redaction.ReviewStatus.DRAFT:
                skipped += 1
                continue
            try:
                reparse_redaction(redaction)
                done += 1
            except (ReparseYieldedNothing, PublishedRedactionExists, ValueError) as exc:
                self.message_user(request, f"{redaction}: {exc}", level=messages.WARNING)
        self.message_user(
            request, f"Переразобрано: {done}; пропущено (не черновик): {skipped}"
        )
```

- [ ] **Step 4: Запустить тест**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add documents/admin.py documents/tests/test_curation_admin.py
git commit -m "feat(documents): reparse-from-RawSource admin action on RedactionAdmin"
```

---

### Task 4: Чистая логика diff по статьям

**Files:**
- Create: `documents/diffing.py`
- Test: `documents/tests/test_diffing.py` (Create)

- [ ] **Step 1: Написать падающий тест**

Создать `documents/tests/test_diffing.py`:

```python
from types import SimpleNamespace

from documents.diffing import diff_articles


def art(number, text):
    return SimpleNamespace(number=number, text=text)


def test_diff_detects_added_removed_changed_same():
    current = [art("1", "старый текст"), art("2", "без изменений"), art("9", "удалят")]
    draft = [art("1", "новый текст"), art("2", "без изменений"), art("3", "новая")]
    by_num = {d.number: d for d in diff_articles(current, draft)}
    assert by_num["1"].status == "changed"
    assert by_num["2"].status == "same"
    assert by_num["3"].status == "added"
    assert by_num["9"].status == "removed"


def test_changed_article_has_plus_and_minus_lines():
    [d] = diff_articles([art("1", "было")], [art("1", "стало")])
    tags = {tag for tag, _ in d.lines}
    assert "-" in tags and "+" in tags
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_diffing.py -q`
Expected: FAIL — `ModuleNotFoundError: documents.diffing`.

- [ ] **Step 3: Реализовать модуль**

Создать `documents/diffing.py`:

```python
"""Чистая логика текстового diff «черновик ↔ текущая» по статьям.
Без обращения к БД — на вход последовательности объектов с .number и .text."""
import difflib
from dataclasses import dataclass, field


@dataclass
class ArticleDiff:
    number: str
    status: str  # "added" | "removed" | "changed" | "same"
    lines: list = field(default_factory=list)  # list[tuple[str, str]]: (tag, text), tag ∈ {"+","-"," "}


def _line_diff(old_text, new_text):
    old = (old_text or "").splitlines()
    new = (new_text or "").splitlines()
    out = []
    for line in difflib.ndiff(old, new):
        tag = line[:1]
        if tag in ("+", "-", " "):
            out.append((tag, line[2:]))
    return out


def diff_articles(current_articles, draft_articles):
    """Выравнивание по `number`. Порядок результата — статьи черновика, затем удалённые."""
    current_by_num = {a.number: a for a in current_articles}
    draft_nums = {a.number for a in draft_articles}
    result = []
    for a in draft_articles:
        cur = current_by_num.get(a.number)
        if cur is None:
            result.append(ArticleDiff(a.number, "added", _line_diff("", a.text)))
        elif (cur.text or "") == (a.text or ""):
            result.append(ArticleDiff(a.number, "same"))
        else:
            result.append(ArticleDiff(a.number, "changed", _line_diff(cur.text, a.text)))
    for a in current_articles:
        if a.number not in draft_nums:
            result.append(ArticleDiff(a.number, "removed", _line_diff(a.text, "")))
    return result
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_diffing.py -q`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add documents/diffing.py documents/tests/test_diffing.py
git commit -m "feat(documents): pure article-aligned diff helper (diffing.py)"
```

---

### Task 5: Admin-страница diff «черновик ↔ текущая» (GET)

**Files:**
- Create: `documents/admin_views.py`
- Modify: `documents/admin.py` (`RedactionAdmin.get_urls`)
- Create: `templates/admin/documents/redaction/diff.html`
- Test: `documents/tests/test_curation_admin.py` (расширить)

- [ ] **Step 1: Написать падающие тесты**

Добавить в `documents/tests/test_curation_admin.py`:

```python
from documents.models import Article, Redaction


@pytest.mark.django_db
def test_diff_view_first_publication_banner(staff_client, draft_with_raw):
    url = reverse("admin:documents_redaction_diff", args=[draft_with_raw.pk])
    resp = staff_client.get(url)
    assert resp.status_code == 200
    assert "первая публикация" in resp.content.decode().lower()


@pytest.mark.django_db
def test_diff_view_shows_changed_article(staff_client, draft_with_raw):
    doc = draft_with_raw.document
    current = Redaction.objects.create(
        document=doc, redaction_date="2020-01-01", is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    Article.objects.create(redaction=current, number="1", text="старая альфа", order=0)
    resp = staff_client.get(reverse("admin:documents_redaction_diff", args=[draft_with_raw.pk]))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "changed" in body  # CSS-класс статуса статьи №1
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q -k diff`
Expected: FAIL — `NoReverseMatch: documents_redaction_diff`.

- [ ] **Step 3: Создать view**

Создать `documents/admin_views.py`:

```python
"""Кастомные admin-страницы курирования (diff / очередь / импорт).
Регистрируются через RedactionAdmin.get_urls и оборачиваются admin_site.admin_view."""
from django.contrib.admin import site as admin_site
from django.shortcuts import get_object_or_404, redirect, render

from documents.diffing import diff_articles
from documents.models import Redaction


def redaction_diff_view(request, pk):
    draft = get_object_or_404(Redaction, pk=pk)
    current = (
        Redaction.objects.filter(document=draft.document, is_current=True)
        .exclude(pk=draft.pk)
        .first()
    )
    if request.method == "POST":
        return _publish_from_diff(request, draft)  # реализуется в Task 6
    current_articles = list(current.articles.all()) if current else []
    diffs = diff_articles(current_articles, list(draft.articles.all()))
    context = {
        **admin_site.each_context(request),
        "title": f"Diff: {draft}",
        "draft": draft,
        "current": current,
        "diffs": diffs,
        "date_looks_placeholder": bool(
            draft.ingested_at and draft.redaction_date == draft.ingested_at.date()
        ),
    }
    return render(request, "admin/documents/redaction/diff.html", context)
```

В Task 6 будет добавлен `_publish_from_diff`. Чтобы Task 5 был самодостаточным и зелёным, добавить **временную** заглушку в тот же файл (она будет заменена в Task 6):

```python
def _publish_from_diff(request, draft):
    return redirect("admin:documents_redaction_change", draft.pk)
```

- [ ] **Step 4: Подключить URL в RedactionAdmin**

В `documents/admin.py` добавить импорты:

```python
from django.urls import path

from documents.admin_views import redaction_diff_view
```

В класс `RedactionAdmin` добавить метод:

```python
    def get_urls(self):
        custom = [
            path(
                "<int:pk>/diff/",
                self.admin_site.admin_view(redaction_diff_view),
                name="documents_redaction_diff",
            ),
        ]
        return custom + super().get_urls()
```

- [ ] **Step 5: Создать шаблон**

Создать `templates/admin/documents/redaction/diff.html`:

```html
{% extends "admin/base_site.html" %}
{% block content %}
<h1>Diff черновика «{{ draft }}»</h1>

{% if date_looks_placeholder %}
  <p class="errornote">Дата «Действует с» совпадает с датой приёма — проверьте её перед публикацией.</p>
{% endif %}

{% if not current %}
  <p class="help">Текущей опубликованной редакции нет — это будет первая публикация, сравнивать не с чем.</p>
{% else %}
  <p class="help">Сравнение с текущей редакцией от {{ current.redaction_date }}.</p>
{% endif %}

{% for d in diffs %}
  <div class="diff-article diff-{{ d.status }}">
    <h3>Статья {{ d.number }} — <span class="status">{{ d.status }}</span></h3>
    {% if d.lines %}
      <pre>{% for tag, text in d.lines %}<span class="line line-{{ tag }}">{{ tag }} {{ text }}</span>
{% endfor %}</pre>
    {% endif %}
  </div>
{% endfor %}

<form method="post">{% csrf_token %}
  <button type="submit" class="default">Опубликовать эту редакцию</button>
</form>

<style>
  .diff-changed .status { color: #b8860b; }
  .diff-added   .status { color: #2e7d32; }
  .diff-removed .status { color: #c62828; }
  .line-+ { background: #e6ffed; }
  .line-- { background: #ffeef0; }
</style>
{% endblock %}
```

- [ ] **Step 6: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q -k diff`
Expected: PASS (2 теста).

- [ ] **Step 7: Commit**

```bash
git add documents/admin_views.py documents/admin.py templates/admin/documents/redaction/diff.html documents/tests/test_curation_admin.py
git commit -m "feat(documents): admin diff view (draft vs current) via get_urls"
```

---

### Task 6: Публикация со страницы diff (POST) + нудж по дате

**Files:**
- Modify: `documents/admin_views.py` (заменить заглушку `_publish_from_diff`)
- Test: `documents/tests/test_curation_admin.py` (расширить)

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_curation_admin.py`:

```python
@pytest.mark.django_db
def test_publish_from_diff_publishes_and_indexes(staff_client, draft_with_raw):
    resp = staff_client.post(reverse("admin:documents_redaction_diff", args=[draft_with_raw.pk]))
    assert resp.status_code == 302
    draft_with_raw.refresh_from_db()
    assert draft_with_raw.review_status == Redaction.ReviewStatus.PUBLISHED
    assert draft_with_raw.is_current is True
    assert draft_with_raw.search_vector is not None
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q -k publish_from_diff`
Expected: FAIL — заглушка ничего не публикует (`review_status` остаётся `draft`).

- [ ] **Step 3: Реализовать публикацию**

В `documents/admin_views.py` добавить импорт `messages` и заменить заглушку `_publish_from_diff`:

```python
from django.contrib import messages
```

```python
def _publish_from_diff(request, draft):
    if draft.review_status != Redaction.ReviewStatus.DRAFT:
        messages.warning(request, "Редакция уже опубликована.")
    else:
        if draft.ingested_at and draft.redaction_date == draft.ingested_at.date():
            messages.warning(
                request, "Дата «Действует с» совпадает с датой приёма — проверьте её."
            )
        draft.publish()
        messages.success(request, "Опубликовано.")
    return redirect("admin:documents_redaction_change", draft.pk)
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q`
Expected: PASS (все тесты файла, включая diff и reparse).

- [ ] **Step 5: Commit**

```bash
git add documents/admin_views.py documents/tests/test_curation_admin.py
git commit -m "feat(documents): publish from diff page with placeholder-date nudge"
```

---

### Task 7: Очередь ревью + ссылки в тулбаре changelist

**Files:**
- Modify: `documents/admin_views.py` (добавить `review_queue_view`)
- Modify: `documents/admin.py` (URL + `change_list_template`)
- Create: `templates/admin/documents/redaction/review_queue.html`
- Create: `templates/admin/documents/redaction/change_list.html`
- Test: `documents/tests/test_curation_admin.py` (расширить)

- [ ] **Step 1: Написать падающий тест**

Добавить в `documents/tests/test_curation_admin.py`:

```python
from ingestion.models import IngestionJob


@pytest.mark.django_db
def test_review_queue_lists_drafts_and_failures(staff_client, draft_with_raw):
    IngestionJob.objects.create(target_key="tk-fail", status=IngestionJob.Status.FAILED)
    resp = staff_client.get(reverse("admin:documents_redaction_review_queue"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "197-ФЗ" in body          # черновик в очереди
    assert "tk-fail" in body         # сбой приёма (карантин)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q -k review_queue`
Expected: FAIL — `NoReverseMatch: documents_redaction_review_queue`.

- [ ] **Step 3: Добавить view**

В `documents/admin_views.py` добавить импорт и функцию:

```python
from ingestion.models import IngestionJob
```

```python
def review_queue_view(request):
    drafts = (
        Redaction.objects.filter(review_status=Redaction.ReviewStatus.DRAFT)
        .select_related("document")
        .order_by("-ingested_at")
    )
    failed = IngestionJob.objects.filter(
        status=IngestionJob.Status.FAILED
    ).order_by("-started_at")[:50]
    context = {
        **admin_site.each_context(request),
        "title": "Очередь ревью",
        "drafts": drafts,
        "failed_jobs": failed,
        "draft_count": drafts.count(),
        "failed_count": IngestionJob.objects.filter(
            status=IngestionJob.Status.FAILED
        ).count(),
    }
    return render(request, "admin/documents/redaction/review_queue.html", context)
```

- [ ] **Step 4: Подключить URL + тулбар**

В `documents/admin.py` дополнить импорт из `admin_views`:

```python
from documents.admin_views import redaction_diff_view, review_queue_view
```

Обновить `get_urls` в `RedactionAdmin` (добавить маршрут очереди) и задать `change_list_template`:

```python
    change_list_template = "admin/documents/redaction/change_list.html"

    def get_urls(self):
        custom = [
            path(
                "review-queue/",
                self.admin_site.admin_view(review_queue_view),
                name="documents_redaction_review_queue",
            ),
            path(
                "<int:pk>/diff/",
                self.admin_site.admin_view(redaction_diff_view),
                name="documents_redaction_diff",
            ),
        ]
        return custom + super().get_urls()
```

- [ ] **Step 5: Создать шаблоны**

Создать `templates/admin/documents/redaction/review_queue.html`:

```html
{% extends "admin/base_site.html" %}
{% block content %}
<h1>Очередь ревью</h1>

<h2>Черновики на проверку ({{ draft_count }})</h2>
{% if drafts %}
  <ul>
    {% for r in drafts %}
      <li>
        <a href="{% url 'admin:documents_redaction_change' r.pk %}">{{ r.document }}</a>
        — ред. от {{ r.redaction_date }}
        · <a href="{% url 'admin:documents_redaction_diff' r.pk %}">diff</a>
      </li>
    {% endfor %}
  </ul>
{% else %}<p class="help">Черновиков нет.</p>{% endif %}

<h2>Сбои приёма / карантин ({{ failed_count }})</h2>
{% if failed_jobs %}
  <ul>
    {% for j in failed_jobs %}
      <li>{{ j.target_key }} — {{ j.started_at }} — {{ j.error|default:"" }}</li>
    {% endfor %}
  </ul>
{% else %}<p class="help">Сбоев нет.</p>{% endif %}
{% endblock %}
```

Создать `templates/admin/documents/redaction/change_list.html`:

```html
{% extends "admin/change_list.html" %}
{% block object-tools-items %}
  <li><a href="{% url 'admin:documents_redaction_review_queue' %}">Очередь ревью</a></li>
  <li><a href="{% url 'admin:documents_redaction_manual_import' %}">Импортировать вручную</a></li>
  {{ block.super }}
{% endblock %}
```

> Примечание: ссылка `manual_import` появится в Task 8. Чтобы Task 7 был зелёным до Task 8, **в этом шаге** временно убери строку про `manual_import` из шаблона и верни её в Task 8 (либо выполняй 7 и 8 одним заходом). Тест Task 7 не открывает changelist, поэтому достаточно, чтобы шаблон не ссылался на несуществующий URL при ручной проверке.

- [ ] **Step 6: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add documents/admin_views.py documents/admin.py templates/admin/documents/redaction/review_queue.html templates/admin/documents/redaction/change_list.html documents/tests/test_curation_admin.py
git commit -m "feat(documents): review-queue admin page + changelist toolbar links"
```

---

### Task 8: Форма ручного импорта в браузере

**Files:**
- Create: `documents/forms.py`
- Modify: `documents/admin_views.py` (`manual_import_view`)
- Modify: `documents/admin.py` (URL), `templates/.../change_list.html` (вернуть ссылку)
- Create: `templates/admin/documents/redaction/import_form.html`
- Test: `documents/tests/test_curation_admin.py` (расширить)

- [ ] **Step 1: Написать падающие тесты**

Добавить в `documents/tests/test_curation_admin.py`:

```python
from django.core.files.uploadedfile import SimpleUploadedFile


@pytest.mark.django_db
def test_manual_import_get_renders_form(staff_client):
    resp = staff_client.get(reverse("admin:documents_redaction_manual_import"))
    assert resp.status_code == 200
    assert "document" in resp.content.decode()


@pytest.mark.django_db
def test_manual_import_paste_creates_draft(staff_client):
    doc = Document.objects.create(doc_type="federal_law", title="ТК", official_number="197-ФЗ", slug="197-fz")
    resp = staff_client.post(
        reverse("admin:documents_redaction_manual_import"),
        {"document": doc.pk, "paste_text": "Статья 1. Альфа.", "content_type": "text/plain"},
    )
    assert resp.status_code == 302
    assert doc.redactions.count() == 1


@pytest.mark.django_db
def test_manual_import_file_creates_draft(staff_client):
    doc = Document.objects.create(doc_type="federal_law", title="ТК", official_number="59-ФЗ", slug="59-fz")
    upload = SimpleUploadedFile("act.txt", "Статья 1. Бета.".encode("utf-8"), content_type="text/plain")
    resp = staff_client.post(
        reverse("admin:documents_redaction_manual_import"),
        {"document": doc.pk, "upload_file": upload, "content_type": "text/plain"},
    )
    assert resp.status_code == 302
    assert doc.redactions.count() == 1


@pytest.mark.django_db
def test_manual_import_requires_content(staff_client):
    doc = Document.objects.create(doc_type="federal_law", title="ТК", official_number="44-ФЗ", slug="44-fz")
    resp = staff_client.post(
        reverse("admin:documents_redaction_manual_import"),
        {"document": doc.pk, "content_type": "text/plain"},
    )
    assert resp.status_code == 200            # форма с ошибкой, без редиректа
    assert doc.redactions.count() == 0
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q -k manual_import`
Expected: FAIL — `NoReverseMatch: documents_redaction_manual_import`.

- [ ] **Step 3: Создать форму**

Создать `documents/forms.py`:

```python
from django import forms

from documents.models import Document


class ManualImportForm(forms.Form):
    document = forms.ModelChoiceField(queryset=Document.objects.all(), label="Документ")
    paste_text = forms.CharField(
        widget=forms.Textarea, required=False, label="Вставить текст"
    )
    upload_file = forms.FileField(
        required=False, label="Или загрузить файл (.txt/.html)"
    )
    content_type = forms.ChoiceField(
        choices=[("text/plain", "Текст"), ("text/html", "HTML")],
        initial="text/plain",
        label="Тип содержимого",
    )
    source_url = forms.URLField(required=False, label="URL источника")
    redaction_date = forms.DateField(required=False, label="Дата редакции (Действует с)")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("paste_text") and not cleaned.get("upload_file"):
            raise forms.ValidationError("Вставьте текст или загрузите файл.")
        return cleaned
```

- [ ] **Step 4: Создать view**

В `documents/admin_views.py` добавить импорты и функцию:

```python
from documents.forms import ManualImportForm
from ingestion.services import import_manual
```

```python
def manual_import_view(request):
    if request.method == "POST":
        form = ManualImportForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            if cd["upload_file"]:
                content = cd["upload_file"].read()
            else:
                content = cd["paste_text"].encode("utf-8")
            redaction = import_manual(
                cd["document"],
                content=content,
                content_type=cd["content_type"],
                source_url=cd["source_url"],
                redaction_date=cd["redaction_date"] or None,
            )
            messages.success(request, f"Создан черновик редакции #{redaction.pk}.")
            return redirect("admin:documents_redaction_change", redaction.pk)
    else:
        form = ManualImportForm()
    context = {
        **admin_site.each_context(request),
        "title": "Ручной импорт",
        "form": form,
    }
    return render(request, "admin/documents/redaction/import_form.html", context)
```

- [ ] **Step 5: Подключить URL + вернуть ссылку в тулбар**

В `documents/admin.py` дополнить импорт и `get_urls`:

```python
from documents.admin_views import (
    manual_import_view,
    redaction_diff_view,
    review_queue_view,
)
```

Добавить в список `custom` внутри `get_urls`:

```python
            path(
                "import/",
                self.admin_site.admin_view(manual_import_view),
                name="documents_redaction_manual_import",
            ),
```

Если в Task 7 ты убирал строку `manual_import` из `change_list.html` — верни её сейчас (см. шаблон в Task 7, Step 5).

- [ ] **Step 6: Создать шаблон**

Создать `templates/admin/documents/redaction/import_form.html`:

```html
{% extends "admin/base_site.html" %}
{% block content %}
<h1>Ручной импорт документа</h1>
<form method="post" enctype="multipart/form-data">{% csrf_token %}
  {{ form.as_p }}
  <button type="submit" class="default">Импортировать</button>
</form>
{% endblock %}
```

- [ ] **Step 7: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_curation_admin.py -q`
Expected: PASS (все тесты файла).

- [ ] **Step 8: Commit**

```bash
git add documents/forms.py documents/admin_views.py documents/admin.py templates/admin/documents/redaction/import_form.html templates/admin/documents/redaction/change_list.html documents/tests/test_curation_admin.py
git commit -m "feat(documents): in-browser manual import form (reuses import_manual)"
```

---

### Task 9 (хвост a): `Link.to_document` → SET_NULL + сохранение цитаты при удалении

**Files:**
- Modify: `documents/models.py`
- Create: `documents/migrations/0008_alter_link_to_document.py` (через makemigrations)
- Create: `documents/signals.py`
- Modify: `documents/apps.py`
- Test: `documents/tests/test_links_on_delete.py` (Create)

- [ ] **Step 1: Написать падающий тест**

Создать `documents/tests/test_links_on_delete.py`:

```python
import pytest

from documents.models import Document, Link


@pytest.mark.django_db
def test_deleting_target_preserves_incoming_link_as_raw_citation():
    src = Document.objects.create(doc_type="federal_law", title="Источник", official_number="1-ФЗ", slug="1-fz")
    tgt = Document.objects.create(doc_type="federal_law", title="Цель", official_number="197-ФЗ", slug="197-fz")
    link = Link.objects.create(from_document=src, to_document=tgt, raw_citation="")
    tgt.delete()
    link.refresh_from_db()                 # связь НЕ удалена каскадом
    assert link.to_document_id is None     # обнулена
    assert link.raw_citation == "197-ФЗ"   # цитата сохранена сигналом
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_links_on_delete.py -q`
Expected: FAIL — сейчас `on_delete=CASCADE`, `link.refresh_from_db()` бросит `Link.DoesNotExist`.

- [ ] **Step 3: Поменять on_delete**

В `documents/models.py`, поле `Link.to_document`, заменить `on_delete=models.CASCADE` на `on_delete=models.SET_NULL`:

```python
    to_document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        related_name="incoming_links",
        on_delete=models.SET_NULL,
    )
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `.venv\Scripts\python.exe manage.py makemigrations documents`
Expected: создан `documents/migrations/0008_alter_link_to_document.py` с одной операцией `AlterField` (поле `to_document`). SQL-изменений нет — `on_delete` работает на уровне ORM.

- [ ] **Step 5: Создать сигнал**

Создать `documents/signals.py`:

```python
"""Сохранение смысла входящих связей при удалении документа-цели.
До обнуления to_document (SET_NULL) переносим номер цели в raw_citation,
чтобы ссылка деградировала во «вне корпуса», а не теряла информацию."""
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from documents.models import Document, Link


@receiver(pre_delete, sender=Document)
def preserve_incoming_citations(sender, instance, **kwargs):
    Link.objects.filter(to_document=instance, raw_citation="").update(
        raw_citation=instance.official_number or instance.title[:200]
    )
```

- [ ] **Step 6: Подключить сигнал в AppConfig**

В `documents/apps.py` добавить метод `ready`:

```python
class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"

    def ready(self):
        from documents import signals  # noqa: F401  (регистрирует ресиверы)
```

- [ ] **Step 7: Запустить тест**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_links_on_delete.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add documents/models.py documents/migrations/0008_alter_link_to_document.py documents/signals.py documents/apps.py documents/tests/test_links_on_delete.py
git commit -m "fix(documents): Link.to_document SET_NULL + preserve citation on target delete"
```

---

### Task 10 (хвост b): Sanitize сниппетов поиска (защита от XSS)

**Files:**
- Modify: `search/services.py`
- Test: `search/tests/test_search.py` (или существующий тест-файл поиска; добавить тест)

- [ ] **Step 1: Написать падающий тест**

Добавить тест в файл тестов поиска (например `search/tests/test_search.py`; если такого нет — создать его с этим содержимым):

```python
import pytest

from documents.models import Article, Document, Redaction
from search.services import search_documents


@pytest.mark.django_db
def test_search_snippet_escapes_html_keeps_mark():
    doc = Document.objects.create(doc_type="federal_law", title="Док", official_number="1-ФЗ", slug="1-fz")
    red = Redaction.objects.create(
        document=doc, redaction_date="2026-01-01", is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
        full_text="Опасный <script>alert(1)</script> налог тут.",
    )
    red.update_search_index()
    [result] = search_documents("налог")
    snippet = str(result.snippet)
    assert "<script>" not in snippet          # внешний HTML обезврежен
    assert "&lt;script&gt;" in snippet        # и виден как текст
    assert "<mark>" in snippet                # подсветка совпадения сохранена
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest search/tests/ -q -k escapes_html`
Expected: FAIL — сейчас `ts_headline` не экранирует исходный текст, `<script>` попадает в сниппет.

- [ ] **Step 3: Реализовать sanitize**

В `search/services.py` добавить импорты и поменять `_headline`, добавить `_safe_snippet`:

```python
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
```

```python
# Сентинелы-маркеры подсветки: ts_headline вставит их в НЕэкранированный текст,
# мы экранируем всё целиком, затем вернём <mark> только вокруг маркеров.
_HL_START = "@@LAWIOT_HL_START@@"
_HL_STOP = "@@LAWIOT_HL_STOP@@"


def _headline(field, query):
    return SearchHeadline(
        field, query, config="russian", start_sel=_HL_START, stop_sel=_HL_STOP
    )


def _safe_snippet(raw) -> SafeString:
    return mark_safe(
        escape(raw or "").replace(_HL_START, "<mark>").replace(_HL_STOP, "</mark>")
    )
```

Затем в `search_documents` обернуть сниппеты при сборке `SearchResult` — в **двух** местах (редакции и статьи):

```python
            best[r.document_id] = SearchResult(
                document=r.document, rank=r.rank, snippet=_safe_snippet(r.snippet)
            )
```

```python
            best[doc.id] = SearchResult(
                document=doc,
                rank=a.rank,
                snippet=_safe_snippet(a.snippet),
                article_anchor=a.anchor,
                article_label=f"{a.get_kind_display()} {a.number}",
            )
```

(`templates/search/search.html` оставляем с `|safe` — теперь сниппет действительно безопасен.)

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest search/tests/ -q`
Expected: PASS (новый тест + прежние тесты поиска не сломаны — подсветка `<mark>` на месте).

- [ ] **Step 5: Commit**

```bash
git add search/services.py search/tests/
git commit -m "fix(search): sanitize ts_headline snippets to prevent stored XSS"
```

---

### Task 11 (хвост c): `reindex_search` → bulk (2 запроса)

**Files:**
- Modify: `documents/management/commands/reindex_search.py`
- Test: `documents/tests/test_search_index.py` (расширить — там уже есть тесты переиндексации)

- [ ] **Step 1: Написать падающие тесты**

Добавить в `documents/tests/test_search_index.py`:

```python
import pytest
from django.core.management import call_command

from documents.models import Article, Document, Redaction


@pytest.mark.django_db
def test_bulk_reindex_matches_update_search_index():
    doc = Document.objects.create(doc_type="federal_law", title="Налоговый кодекс", official_number="1-ФЗ", slug="1-fz")
    red = Redaction.objects.create(
        document=doc, redaction_date="2026-01-01", is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED, full_text="налог и сбор",
    )
    Article.objects.create(redaction=red, number="1", title="Общие", text="ставка налога", order=0)
    red.update_search_index()                       # эталон (ORM-путь публикации)
    red.refresh_from_db()
    expected_red = red.search_vector
    expected_art = Article.objects.get(redaction=red, number="1").search_vector

    Redaction.objects.filter(pk=red.pk).update(search_vector=None)
    Article.objects.filter(redaction=red).update(search_vector=None)
    call_command("reindex_search")                  # bulk-путь
    red.refresh_from_db()
    assert red.search_vector == expected_red        # паритет: тот же вектор
    assert Article.objects.get(redaction=red, number="1").search_vector == expected_art


@pytest.mark.django_db
def test_bulk_reindex_skips_drafts():
    doc = Document.objects.create(doc_type="federal_law", title="Док", official_number="2-ФЗ", slug="2-fz")
    draft = Redaction.objects.create(
        document=doc, redaction_date="2026-01-01",
        review_status=Redaction.ReviewStatus.DRAFT, full_text="черновик налог",
    )
    call_command("reindex_search")
    draft.refresh_from_db()
    assert draft.search_vector is None              # черновики не индексируем
```

- [ ] **Step 2: Запустить — убедиться, что нужный тест падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_search_index.py -q -k bulk`
Expected: первый тест может проходить и на старом цикле (он тоже даёт паритет), но цель шага — закрепить контракт. Второй тест (`skips_drafts`) проходит и сейчас. Реальная проверка bulk-реализации — в Step 4 (число запросов) и сохранение зелёного статуса.

> Контракт этого таска — **2 SQL-запроса вместо 2N**. Зафиксируем это явным тестом:

Добавить ещё один тест туда же:

```python
from django.test.utils import CaptureQueriesContext
from django.db import connection


@pytest.mark.django_db
def test_bulk_reindex_uses_constant_queries():
    doc = Document.objects.create(doc_type="federal_law", title="Док", official_number="3-ФЗ", slug="3-fz")
    for i in range(5):
        Redaction.objects.create(
            document=doc, redaction_date=f"2020-01-0{i+1}",
            review_status=Redaction.ReviewStatus.PUBLISHED, full_text=f"налог {i}",
        )
    with CaptureQueriesContext(connection) as ctx:
        call_command("reindex_search")
    updates = [q for q in ctx.captured_queries if q["sql"].lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 2          # 5 редакций → всё ещё 2 UPDATE (не 2N)
```

- [ ] **Step 3: Запустить — убедиться, что падает на старом коде**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_search_index.py -q -k constant_queries`
Expected: FAIL — старый цикл делает по 2 UPDATE на редакцию (10 для пяти редакций), не 2.

- [ ] **Step 4: Переписать команду на bulk**

Полностью заменить `documents/management/commands/reindex_search.py`:

```python
from django.core.management.base import BaseCommand
from django.db import connection

# Векторы должны 1-в-1 повторять Redaction.update_search_index():
# заголовок документа — вес A, full_text — вес B; для статьи number/title — A, text — B.
_REDACTION_SQL = """
UPDATE documents_redaction r
SET search_vector =
    setweight(to_tsvector('russian', coalesce(d.title, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(r.full_text, '')), 'B')
FROM documents_document d
WHERE r.document_id = d.id AND r.review_status = 'published';
"""

_ARTICLE_SQL = """
UPDATE documents_article a
SET search_vector =
    setweight(to_tsvector('russian', coalesce(a.number, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(a.title, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(a.text, '')), 'B')
FROM documents_redaction r
WHERE a.redaction_id = r.id AND r.review_status = 'published';
"""


class Command(BaseCommand):
    help = "Пересобирает поисковые векторы опубликованных редакций (bulk, 2 запроса)."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(_REDACTION_SQL)
            redactions = cursor.rowcount
            cursor.execute(_ARTICLE_SQL)
            articles = cursor.rowcount
        self.stdout.write(
            self.style.SUCCESS(
                f"Переиндексировано: редакций {redactions}, статей {articles}"
            )
        )
```

- [ ] **Step 5: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_search_index.py -q`
Expected: PASS (паритет, skip-drafts, constant-queries и прежний `test_reindex_search_backfills_vectors`).

- [ ] **Step 6: Commit**

```bash
git add documents/management/commands/reindex_search.py documents/tests/test_search_index.py
git commit -m "perf(search): bulk reindex_search with two UPDATE...FROM statements"
```

---

### Task 12: Финальная проверка по всему репо

**Files:** —

- [ ] **Step 1: Линт всего репо** (см. [[lawiot-lint-scope]])

Run: `.venv\Scripts\python.exe -m ruff check .`
Expected: `All checks passed!` Исправить любые E402/F401 и пр.

- [ ] **Step 2: Прогнать ВЕСЬ набор тестов** (без фильтра пути; БД-контейнер поднят)

Run: `docker compose up -d db` затем `.venv\Scripts\python.exe -m pytest`
Expected: всё зелено. Базис 87 + новые: Task1 (2), Task2 (3), Task3 (1), Task4 (2), Task5 (2), Task6 (1), Task7 (1), Task8 (4), Task9 (1), Task10 (1), Task11 (3) ≈ **+21 → ~108 тестов**.

- [ ] **Step 3: Проверить отсутствие незакоммиченных миграций**

Run: `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (единственная новая миграция — `0008_alter_link_to_document` из Task 9 — уже закоммичена).

- [ ] **Step 4: Ручная дымовая проверка (опционально, но желательно)**

`docker compose up --wait`, зайти в `/admin/`, открыть «Очередь ревью», импортировать вставкой текста, открыть diff черновика, нажать «Опубликовать», проверить, что акт виден в `/search/`.

- [ ] **Step 5: Финальный коммит (если остались правки линта)**

```bash
git add -A
git commit -m "test(lawiot): plan 3d — full suite green (curation polish)"
```

---

## Self-Review (выполнено при написании плана)

**Покрытие спеки (§7 «Курирование», §16 шаг 9):**
- Очередь на проверку (черновики, сбои) → Task 7. ✓
- Действия публиковать / переразобрать / импорт → Tasks 6, 3, 8. ✓ (подтверждение связей `confirm_selected` уже есть.)
- Diff «черновик ↔ текущая» → Tasks 4–5. ✓
- Публикация атомарно + переиндексация → переиспользуется `Redaction.publish()` (Task 6). ✓
- Read-only аудит admin → Task 1. ✓

**Отложенные находки 3a:** #1283 (read-only + reparse без конфликта прав) → Tasks 1+3; #1281 (0-статей guard) → Task 2; #1282 (эвристика заголовка на реальном HTML) — **сознательно вне 3d**, в шаг 10 (нужны реальные фикстуры; reparse даёт инструмент чинить).

**Хвосты:** Link on_delete → Task 9; sanitize сниппетов → Task 10; bulk reindex → Task 11.

**Placeholder-скан:** конкретных «TODO/TBD» в шагах нет; код приведён полностью.

**Согласованность типов/имён:** `reparse_redaction`, `ReparseYieldedNothing`, `diff_articles`, `ArticleDiff`, `_safe_snippet`, `_HL_START/_HL_STOP`, имена URL `documents_redaction_{diff,review_queue,manual_import}` — единообразны во всех задачах.

**Известный компромисс:** Task 11 дублирует определение tsvector (ORM в `update_search_index` + raw SQL в команде) — прикрыто тестом-паритетом (`test_bulk_reindex_matches_update_search_index`), который падёт при расхождении.

---

## Execution Handoff

План сохранён в `docs/superpowers/plans/2026-06-07-lawiot-plan-3d-curation-polish.md`. Способ исполнения — субагентами по задачам (рекомендуется) или инлайн с чекпойнтами.
