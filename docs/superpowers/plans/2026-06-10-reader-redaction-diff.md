# Сравнение редакций для читателя (reader diff) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Читатель сравнивает прошлую опубликованную редакцию акта с текущей: постатейный inline-diff (`+`/`−`), вход — из списка «Другие редакции» на странице акта.

**Architecture:** Один новый read-only view `redaction_diff` поверх существующей чистой функции `documents/diffing.py:diff_articles` (не модифицируется). Новый шаблон + 2 ссылочные строки в `document_detail.html`. Ноль новых моделей/зависимостей/записей в БД. Спека: `docs/superpowers/specs/2026-06-10-reader-redaction-diff-design.md`.

**Tech Stack:** Django 5.2 (views/templates), Pico CSS, pytest + pytest-django (фабрики `documents/tests/factories.py`).

**РАБОЧЕЕ ОКРУЖЕНИЕ (критично):**
- Работать в worktree `D:\Кодинг\Lawiot.worktrees\reader-diff`, ветка `feature/lawiot-reader-redaction-diff` (НЕ в основном чекауте — там параллельная сессия, см. memory `parallel-sessions-coordination`).
- Python — абсолютным путём: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe` (bare `python` зависает — Store stub).
- Тестам нужен Postgres-контейнер `lawiot-db` (port 5433, `.env` уже скопирован в worktree). Если параллельная сессия гоняет тесты одновременно и упрётесь в «test database already exists» — повторить прогон.
- Все команды: `cd /d "D:\Кодинг\Lawiot.worktrees\reader-diff"` (или PowerShell `Set-Location`).

---

## Структура файлов

| Файл | Ответственность | Действие |
|---|---|---|
| `documents/views.py` | + view `redaction_diff` (read-only, login_required) | Modify |
| `config/urls.py` | + маршрут `doc/<slug>/diff/<int:from_pk>/` name=`redaction_diff` | Modify |
| `templates/documents/redaction_diff.html` | Страница diff (extends base.html) | Create |
| `templates/documents/document_detail.html:14-23` | Ссылки на diff в `<details>` «Другие редакции» | Modify |
| `documents/tests/test_views.py` | View-тесты diff + точки входа | Modify |

`documents/diffing.py` НЕ трогать (чистая функция уже используется admin-diff'ом).

---

### Task 1: View + маршрут — happy path (изменённая статья)

**Files:**
- Modify: `documents/views.py`
- Modify: `config/urls.py`
- Test: `documents/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест**

В конец `documents/tests/test_views.py` добавить:

```python
@pytest.mark.django_db
def test_diff_shows_changed_article_lines(auth_client):
    doc = make_document(slug="diff-doc", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    make_article(old, number="1", title="Цели", text="Старый текст статьи.")
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    make_article(new, number="1", title="Цели", text="Новый текст статьи.")
    new.publish()  # становится текущей, old.is_current снимается

    response = auth_client.get(
        reverse("redaction_diff", args=["diff-doc", old.pk])
    )
    content = response.content.decode()
    assert response.status_code == 200
    # направление: старая → текущая
    assert "2023" in content and "2024" in content
    assert "Новый текст статьи." in content   # строка со знаком +
    assert "Старый текст статьи." in content  # строка со знаком −
    assert "изменена" in content
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_views.py::test_diff_shows_changed_article_lines -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'redaction_diff' not found`.

- [ ] **Step 3: Добавить маршрут**

В `config/urls.py` после строки `path("doc/<slug:slug>/", ...)`:

```python
    path(
        "doc/<slug:slug>/diff/<int:from_pk>/",
        views.redaction_diff,
        name="redaction_diff",
    ),
```

- [ ] **Step 4: Реализовать view**

В `documents/views.py`: к импортам добавить `from documents.diffing import diff_articles`, в конец файла:

```python
@login_required
def redaction_diff(request, slug, from_pk):
    """Изменения «прошлая редакция → текущая» для читателя. Read-only."""
    document = get_object_or_404(Document, slug=slug)
    current = document.redactions.filter(
        is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
    ).first()
    if current is None:
        raise Http404("Нет опубликованной редакции")
    older = get_object_or_404(
        Redaction,
        pk=from_pk,
        document=document,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    if older.pk == current.pk:
        raise Http404("Редакция уже текущая — сравнивать не с чем")
    diffs = [
        d
        for d in diff_articles(list(older.articles.all()), list(current.articles.all()))
        if d.status != "same"
    ]
    return render(
        request,
        "documents/redaction_diff.html",
        {"document": document, "older": older, "current": current, "diffs": diffs},
    )
```

- [ ] **Step 5: Создать шаблон** `templates/documents/redaction_diff.html`:

```html
{% extends "base.html" %}
{% block title %}Изменения — {{ document.title|truncatechars:60 }} — Lawiot{% endblock %}
{% block content %}

<nav aria-label="breadcrumb">
  <a href="{% url 'document_detail' document.slug %}">← {{ document.title|truncatechars:80 }}</a>
</nav>

<h1>Изменения: редакция от {{ older.redaction_date }} → текущая от {{ current.redaction_date }}</h1>

{% if not diffs %}
<p>Текстовых изменений между этими редакциями нет.</p>
{% endif %}

{% for d in diffs %}
<section class="diff-article diff-{{ d.status }}">
  <h3>Статья {{ d.number }} —
    {% if d.status == "changed" %}изменена{% elif d.status == "added" %}добавлена{% elif d.status == "removed" %}удалена{% endif %}
  </h3>
  {% if d.lines %}
  <pre>{% for tag, text in d.lines %}<span class="line {% if tag == '+' %}line-add{% elif tag == '-' %}line-del{% endif %}">{{ tag }} {{ text }}</span>
{% endfor %}</pre>
  {% endif %}
</section>
{% endfor %}

<style>
  .diff-changed h3 { color: #b8860b; }
  .diff-added   h3 { color: #2e7d32; }
  .diff-removed h3 { color: #c62828; }
  pre .line { display: block; }
  .line-add { background: #e6ffed; }
  .line-del { background: #ffeef0; }
</style>
{% endblock %}
```

- [ ] **Step 6: Запустить — убедиться, что проходит**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_views.py::test_diff_shows_changed_article_lines -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add documents/views.py config/urls.py templates/documents/redaction_diff.html documents/tests/test_views.py
git commit -m "feat(documents): reader-facing redaction diff view (older → current)"
```

### Task 2: Добавленные / удалённые / неизменённые статьи

**Files:**
- Test: `documents/tests/test_views.py`
- Modify: `documents/views.py` / шаблон — только если тесты вскроют баг (логика уже в `diff_articles`)

- [ ] **Step 1: Написать тесты**

```python
@pytest.mark.django_db
def test_diff_added_removed_and_same_articles(auth_client):
    doc = make_document(slug="diff-ars", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    make_article(old, number="1", title="Без изменений", text="Стабильный текст.", order=1)
    make_article(old, number="2", title="Будет удалена", text="Текст удаляемой.", order=2)
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    make_article(new, number="1", title="Без изменений", text="Стабильный текст.", order=1)
    make_article(new, number="3", title="Новая статья", text="Текст новой.", order=2)
    new.publish()

    response = auth_client.get(reverse("redaction_diff", args=["diff-ars", old.pk]))
    content = response.content.decode()
    assert "Статья 3" in content and "добавлена" in content
    assert "Статья 2" in content and "удалена" in content
    # неизменённая статья не показывается
    assert "Статья 1" not in content
    assert "Стабильный текст." not in content


@pytest.mark.django_db
def test_diff_no_changes_message(auth_client):
    doc = make_document(slug="diff-same", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    make_article(old, number="1", title="Цели", text="Тот же текст.")
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    make_article(new, number="1", title="Цели", text="Тот же текст.")
    new.publish()

    response = auth_client.get(reverse("redaction_diff", args=["diff-same", old.pk]))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Текстовых изменений между этими редакциями нет." in content
```

- [ ] **Step 2: Запустить**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_views.py -k diff -v`
Expected: PASS (логика Task 1 это покрывает). Если FAIL — минимально починить view/шаблон, не трогая `diffing.py`.

- [ ] **Step 3: Commit**

```bash
git add documents/tests/test_views.py
git commit -m "test(documents): reader diff covers added/removed/unchanged articles"
```

### Task 3: Доступ и 404

**Files:**
- Test: `documents/tests/test_views.py`
- Modify: `documents/views.py` — только если тест вскроет баг

- [ ] **Step 1: Написать тесты**

```python
@pytest.mark.django_db
def test_diff_requires_login(client):
    doc = make_document(slug="diff-anon", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    old.publish()
    response = client.get(reverse("redaction_diff", args=["diff-anon", old.pk]))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_diff_404_for_draft_or_foreign_or_current(auth_client):
    doc = make_document(slug="diff-404", official_number="197-ФЗ")
    current = make_redaction(doc, redaction_date=date(2024, 1, 1))
    current.publish()
    draft = make_redaction(doc, redaction_date=date(2025, 1, 1))  # черновик

    other_doc = make_document(slug="diff-404-other", official_number="125-ФЗ")
    foreign = make_redaction(other_doc, redaction_date=date(2023, 1, 1))
    foreign.publish()

    # черновик недоступен читателю даже подбором pk
    assert auth_client.get(
        reverse("redaction_diff", args=["diff-404", draft.pk])
    ).status_code == 404
    # редакция чужого документа
    assert auth_client.get(
        reverse("redaction_diff", args=["diff-404", foreign.pk])
    ).status_code == 404
    # сравнение текущей с самой собой
    assert auth_client.get(
        reverse("redaction_diff", args=["diff-404", current.pk])
    ).status_code == 404
    # несуществующий pk
    assert auth_client.get(
        reverse("redaction_diff", args=["diff-404", 999999])
    ).status_code == 404
```

- [ ] **Step 2: Запустить**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_views.py -k diff -v`
Expected: PASS (view из Task 1 уже фильтрует по document + PUBLISHED и отбрасывает self-pk). Если FAIL — починить view минимально.

- [ ] **Step 3: Commit**

```bash
git add documents/tests/test_views.py
git commit -m "test(documents): reader diff access control and 404 paths"
```

### Task 4: Точка входа на странице акта

**Files:**
- Modify: `templates/documents/document_detail.html:14-23`
- Test: `documents/tests/test_views.py`

- [ ] **Step 1: Написать падающий тест**

```python
@pytest.mark.django_db
def test_detail_links_to_diff_for_past_redactions(auth_client):
    doc = make_document(slug="diff-entry", official_number="197-ФЗ")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    new.publish()

    response = auth_client.get(reverse("document_detail", args=["diff-entry"]))
    content = response.content.decode()
    # у прошлой редакции есть ссылка на diff, у текущей — нет
    assert reverse("redaction_diff", args=["diff-entry", old.pk]) in content
    assert reverse("redaction_diff", args=["diff-entry", new.pk]) not in content
    assert "что изменилось" in content


@pytest.mark.django_db
def test_detail_no_diff_links_with_single_redaction(auth_client):
    doc = make_document(slug="diff-single", official_number="197-ФЗ")
    make_redaction(doc, redaction_date=date(2024, 1, 1)).publish()
    response = auth_client.get(reverse("document_detail", args=["diff-single"]))
    assert "что изменилось" not in response.content.decode()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_views.py -k entry -v`
Expected: FAIL — в шаблоне нет ссылок на diff.

- [ ] **Step 3: Обновить шаблон**

В `templates/documents/document_detail.html` заменить блок `<li>` внутри `<details>` «Другие редакции»:

```html
        {% for r in published_redactions %}
        <li>Редакция от {{ r.redaction_date }}{% if r.is_current %} — текущая{% else %}
          — <a href="{% url 'redaction_diff' document.slug r.pk %}">что изменилось к текущей</a>{% endif %}</li>
        {% endfor %}
```

(Остальное в `<details>` не трогать. ВНИМАНИЕ: параллельная ветка `feature/frontend-search-pagination-polish` правит `<aside>` этого же шаблона — при последующем merge конфликт маловероятен, но если возникнет, обе правки независимы: наша — блок `<details>` в `<header>`, их — `<aside>`.)

- [ ] **Step 4: Запустить**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_views.py -k "entry or single" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/documents/document_detail.html documents/tests/test_views.py
git commit -m "feat(documents): link past redactions to reader diff on act page"
```

### Task 5: Финальная проверка всего репозитория

- [ ] **Step 1: Полный прогон** (без путей — весь репозиторий, см. memory `lawiot-lint-scope`):

```
D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check .
D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest
```
Expected: ruff чисто; **121 базовых + 6 новых = 127 тестов** зелёные. (При коллизии тестовой БД с параллельной сессией — повторить.)

- [ ] **Step 2: Ручная проверка глазами** (опционально, dev-сервер основного чекаута смотрит на ту же БД, но другую ветку кода — для просмотра поднять сервер из worktree на другом порту: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001`).

- [ ] **Step 3: Push + PR** (base `main`; merge — только пользователь):

```bash
git push -u origin feature/lawiot-reader-redaction-diff
gh pr create --base main --title "feat: reader-facing redaction diff (§17)" --body "..."
```

- [ ] **Step 4:** Обновить память (`lawiot-overview`: фича реализована, PR №; `lawiot-lint-scope`: новое число тестов).

---

## Self-Review (сверка со спекой)

- §2 компоненты: маршрут (T1.3), view (T1.4), шаблон (T1.5), точка входа (T4), тесты (T1–T4). ✅
- §3 поведение view: п.1–2 (T1.4), п.3 все 404-ветки (T3), п.4 направление старая→текущая (T1 тест «2023→2024»), п.5 скрытие same + сообщение «нет изменений» (T2). ✅
- §5: read-only, login_required (T3 тест анонима), только published (T3), autoescape — шаблон Django по умолчанию. ✅
- §6 тесты 1–6 спеки → T1 (изменённая), T2 (добавл./удал./same), T3 (аноним, 404×4), T4 (точка входа ×2). ✅
- §7 YAGNI: произвольных пар нет, intra-line нет, diff реквизитов нет, перенумерация не учитывается. ✅
- Типы/сигнатуры согласованы: `diff_articles(list, list)` → `ArticleDiff(number, status, lines:[(tag,text)])` — поля используются в шаблоне ровно так (`d.status`, `d.number`, `d.lines`). `Http404` импортирован в `documents/views.py` уже сейчас (используется в `document_detail`). ✅
