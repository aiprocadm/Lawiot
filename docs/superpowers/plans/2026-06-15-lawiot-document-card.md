# Карточка акта + статусы — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить плоский заголовок документа в структурный «паспорт акта» с полными реквизитами (из сида), цветным бейджем статуса и обзором структуры.

**Architecture:** Реквизиты-идентичность (`sign_date`/`official_pub_date`) заполняются из `SEED_ACTS` (поля модели уже есть, миграций нет). Вьюха `document_detail` добавляет в контекст счётчики структуры одним агрегатным запросом. Шаблон рендерит `<dl>`-паспорт с бейджем статуса; CSS бейджа — в `base.html`.

**Tech Stack:** Django 5.2, PostgreSQL, Pico CSS, pytest + pytest-django.

---

## Файловая структура

- **Modify** `documents/seed/labor_law.py` — добавить `sign_date`/`official_pub_date` в два словаря `SEED_ACTS`.
- **Modify** `documents/views.py` — `document_detail`: добавить счётчики структуры в контекст.
- **Modify** `templates/documents/document_detail.html` — заменить плоский `<p>` на `<dl>`-паспорт с бейджем.
- **Modify** `templates/base.html` — минимальный CSS для `.status-badge`.
- **Create** `documents/tests/test_document_card.py` — тесты вьюхи/шаблона/сида (не трогаем hotspot `test_views.py`).

## Команды (окружение)

Python: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe` (общий venv по абсолютному пути).
Запуск тестов из корня worktree. Postgres-контейнер `lawiot-db` на порту 5433
(в этой сессии Docker живой). Если параллельная сессия гоняет тесты —
изолировать test-БД через уникальное имя в `DATABASE_URL` (см.
`parallel-sessions-coordination`), иначе достаточно `--create-db`.

Шаблон команды pytest:
`D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest <путь> -v`

---

### Task 1: Реквизиты в сиде

**Files:**
- Modify: `documents/seed/labor_law.py`
- Test: `documents/tests/test_document_card.py`

- [ ] **Step 1: Написать падающий тест сида**

Создать `documents/tests/test_document_card.py`:

```python
import datetime

import pytest

from documents.models import Document
from documents.seed.labor_law import SEED_ACTS


@pytest.mark.django_db
def test_seed_corpus_stamps_requisites_on_existing_document():
    """Повторный seed_corpus проставляет sign_date/official_pub_date
    на уже существующий документ (через update_or_create)."""
    from django.core.management import call_command

    # документ уже существует без дат (как в проде до фичи)
    Document.objects.create(
        slug="tk-rf",
        doc_type="code",
        title="Трудовой кодекс Российской Федерации",
        official_number="197-ФЗ",
    )
    call_command("seed_corpus")
    doc = Document.objects.get(slug="tk-rf")
    assert doc.sign_date == datetime.date(2001, 12, 30)
    assert doc.official_pub_date == datetime.date(2001, 12, 31)


def test_seed_acts_have_requisite_dates():
    """Оба сид-акта несут sign_date и official_pub_date (pure, без БД)."""
    by_slug = {a["slug"]: a for a in SEED_ACTS}
    assert by_slug["tk-rf"]["sign_date"] == datetime.date(2001, 12, 30)
    assert by_slug["tk-rf"]["official_pub_date"] == datetime.date(2001, 12, 31)
    assert by_slug["sout-426-fz"]["sign_date"] == datetime.date(2013, 12, 28)
    assert by_slug["sout-426-fz"]["official_pub_date"] == datetime.date(2013, 12, 30)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_document_card.py -v`
Expected: FAIL — `KeyError: 'sign_date'` (ключей ещё нет в SEED_ACTS).

- [ ] **Step 3: Добавить даты в SEED_ACTS**

В `documents/seed/labor_law.py` добавить `import datetime` сверху и проставить
даты в оба словаря. Для `tk-rf` (после `"status": "in_force",`):

```python
        "sign_date": datetime.date(2001, 12, 30),  # подписан Президентом 30.12.2001
        "official_pub_date": datetime.date(2001, 12, 31),  # «Российская газета» №256
```

Для `sout-426-fz` (после `"status": "in_force",`):

```python
        "sign_date": datetime.date(2013, 12, 28),  # подписан 28.12.2013
        "official_pub_date": datetime.date(2013, 12, 30),  # «Российская газета» №295
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_document_card.py -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Коммит**

```bash
git add documents/seed/labor_law.py documents/tests/test_document_card.py
git commit -m "feat(documents): реквизиты sign_date/official_pub_date в сиде

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Счётчики структуры во вьюхе

**Files:**
- Modify: `documents/views.py` (функция `document_detail`)
- Test: `documents/tests/test_document_card.py`

Контекст: `document_detail` уже загружает текущую опубликованную `redaction`
и строит `article_tree`. Добавляем счётчики по `redaction.articles` (модель
`Article` с полем `kind`: значения `section`/`chapter`/`article`).

- [ ] **Step 1: Написать падающий тест вьюхи**

Добавить в `documents/tests/test_document_card.py`. Хелпер создаёт документ
с опубликованной редакцией и несколькими узлами разных видов:

```python
from django.test import Client
from django.utils import timezone

from documents.models import Article, Redaction


def _published_doc_with_structure():
    doc = Document.objects.create(
        slug="demo-act",
        doc_type="federal_law",
        title="Демонстрационный акт",
        official_number="1-ФЗ",
        sign_date=datetime.date(2020, 1, 1),
        official_pub_date=datetime.date(2020, 1, 2),
        status="in_force",
    )
    red = Redaction.objects.create(
        document=doc,
        redaction_date=datetime.date(2020, 1, 2),
        review_status="published",
        is_current=True,
        published_at=timezone.now(),
    )
    sec = Article.objects.create(redaction=red, kind="section", number="I", order=1)
    ch = Article.objects.create(
        redaction=red, kind="chapter", number="1", order=2, parent=sec
    )
    Article.objects.create(
        redaction=red, kind="article", number="1", title="Ст 1", text="t", order=3, parent=ch
    )
    Article.objects.create(
        redaction=red, kind="article", number="2", title="Ст 2", text="t", order=4, parent=ch
    )
    return doc


@pytest.mark.django_db
def test_detail_context_has_structure_counts(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="x")
    client.force_login(user)
    _published_doc_with_structure()
    resp = client.get("/doc/demo-act/")
    assert resp.status_code == 200
    assert resp.context["section_count"] == 1
    assert resp.context["chapter_count"] == 1
    assert resp.context["article_count"] == 2
```

Примечание: весь просмотрщик за `@login_required` (§10) — тест логинит
пользователя. URL `/doc/<slug>/` — имя маршрута `document_detail`.

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_document_card.py::test_detail_context_has_structure_counts -v`
Expected: FAIL — `KeyError: 'section_count'` в контексте.

- [ ] **Step 3: Добавить счётчики в контекст**

В `documents/views.py` в начале файла убедиться, что импортирован `Count`:
`from django.db.models import Count` (если ещё нет — добавить к существующему
импорту из `django.db.models`).

В функции `document_detail`, после вычисления `article_tree` и до сборки
словаря контекста, добавить:

```python
    counts = {
        row["kind"]: row["n"]
        for row in redaction.articles.values("kind").annotate(n=Count("id"))
    }
```

И в словарь, передаваемый в `render(...)`, добавить ключи:

```python
            "section_count": counts.get(Article.Kind.SECTION, 0),
            "chapter_count": counts.get(Article.Kind.CHAPTER, 0),
            "article_count": counts.get(Article.Kind.ARTICLE, 0),
```

Если `Article` ещё не импортирован во вьюхе — добавить к существующему
импорту из `documents.models`.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_document_card.py::test_detail_context_has_structure_counts -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add documents/views.py documents/tests/test_document_card.py
git commit -m "feat(documents): счётчики структуры (разделы/главы/статьи) в карточке

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Паспорт-блок в шаблоне + CSS бейджа

**Files:**
- Modify: `templates/documents/document_detail.html` (header-блок, строки 6–25)
- Modify: `templates/base.html` (CSS `.status-badge`)
- Test: `documents/tests/test_document_card.py`

- [ ] **Step 1: Написать падающие тесты шаблона**

Добавить в `documents/tests/test_document_card.py`:

```python
@pytest.mark.django_db
def test_detail_renders_passport_fields(client, django_user_model):
    user = django_user_model.objects.create_user("reader2", password="x")
    client.force_login(user)
    _published_doc_with_structure()
    html = client.get("/doc/demo-act/").content.decode()
    # реквизиты-даты выведены
    assert "Дата подписания" in html
    assert "01.01.2020" in html or "1 янв" in html or "2020" in html
    assert "Дата опубликования" in html
    # цветной бейдж статуса с классом по значению
    assert "status-badge" in html
    assert "status-in_force" in html
    # обзор структуры
    assert "статей" in html


@pytest.mark.django_db
def test_detail_empty_requisites_show_dash(client, django_user_model):
    user = django_user_model.objects.create_user("reader3", password="x")
    client.force_login(user)
    doc = Document.objects.create(
        slug="bare-act",
        doc_type="order",
        title="Акт без реквизитов",
        official_number="",
        status="repealed",
    )
    Redaction.objects.create(
        document=doc,
        redaction_date=datetime.date(2021, 5, 5),
        review_status="published",
        is_current=True,
        published_at=timezone.now(),
        full_text="текст",
    )
    html = client.get("/doc/bare-act/").content.decode()
    assert "—" in html  # пустые sign_date/official_pub_date → прочерк
    assert "status-repealed" in html
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_document_card.py -k "passport or dash" -v`
Expected: FAIL — нет `status-badge`/«Дата подписания» в текущем шаблоне.

- [ ] **Step 3: Переписать header-блок шаблона**

В `templates/documents/document_detail.html` заменить блок `<header>…</header>`
(текущие строки 6–25) на паспорт-карточку. Сохранить `<h1>` и блок
«Другие редакции» как есть:

```html
  <header>
    <h1>{{ document.title }}</h1>
    <dl class="passport">
      <dt>Вид документа</dt><dd>{{ document.get_doc_type_display }}</dd>
      <dt>Номер</dt><dd>{{ document.official_number|default:"—" }}</dd>
      <dt>Принявший орган</dt><dd>{{ document.issuing_body|default:"—" }}</dd>
      <dt>Дата подписания</dt><dd>{{ document.sign_date|date:"d.m.Y"|default:"—" }}</dd>
      <dt>Дата опубликования</dt><dd>{{ document.official_pub_date|date:"d.m.Y"|default:"—" }}</dd>
      <dt>Статус</dt>
      <dd><span class="status-badge status-{{ document.status }}">{{ document.get_status_display }}</span></dd>
      <dt>Действующая редакция</dt><dd>{{ redaction.redaction_date|date:"d.m.Y" }}</dd>
      <dt>Структура</dt>
      <dd>
        {% if section_count %}{{ section_count }} раздел(ов) · {% endif %}
        {% if chapter_count %}{{ chapter_count }} глав(ы) · {% endif %}
        {{ article_count }} статей
      </dd>
    </dl>
    {% if published_redactions.count > 1 %}
    <details>
      <summary>Другие редакции ({{ published_redactions.count }})</summary>
      <ul>
        {% for r in published_redactions %}
        <li>Редакция от {{ r.redaction_date }}{% if r.is_current %} — текущая{% else %}
          — <a href="{% url 'redaction_diff' document.slug r.pk %}">что изменилось к текущей</a>{% endif %}</li>
        {% endfor %}
      </ul>
    </details>
    {% endif %}
  </header>
```

Примечание по фильтрам Django: `|date:"d.m.Y"` на `None` возвращает пустую
строку, поэтому `|default:"—"` после него корректно даёт прочерк (Django
применяет фильтры слева направо; пустая строка — falsy для `default`).

- [ ] **Step 4: Добавить CSS бейджа в base.html**

В `templates/base.html` **нет** существующего `<style>` — есть только Pico
CDN-ссылка (строка 7) и `{% block extra_head %}{% endblock %}` (строка 9)
перед `</head>` (строка 10). Вставить новый блок `<style>` сразу перед
`</head>`:

```html
  <style>
  .status-badge {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    border-radius: 0.4rem;
    font-size: 0.85em;
    color: #fff;
  }
  .status-in_force { background: #2e7d32; }     /* зелёный — действует */
  .status-repealed { background: #c62828; }     /* красный — утратил силу */
  .status-not_in_force { background: #757575; } /* серый — не вступил */
  .passport dt { font-weight: 600; }
  </style>
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest documents/tests/test_document_card.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 6: Коммит**

```bash
git add templates/documents/document_detail.html templates/base.html documents/tests/test_document_card.py
git commit -m "feat(documents): паспорт-карточка акта с бейджем статуса и обзором структуры

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Полный прогон + ruff

**Files:** (нет изменений кода — проверка)

- [ ] **Step 1: Полный набор тестов**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m pytest -q`
Expected: все зелёные (234 базовых + новые из этого плана). При коллизии
test-БД с параллельной сессией — изолировать имя test-БД (см. команды выше)
и добавить `--create-db`.

- [ ] **Step 2: ruff**

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff check .`
Expected: чисто.

Run: `D:\Кодинг\Lawiot\.venv\Scripts\python.exe -m ruff format --check .`
Expected: чисто (если форматтер ругается на новый файл — `ruff format .` и
доммитить).

- [ ] **Step 3: Финальный коммит (если ruff format что-то поправил)**

```bash
git add -A
git commit -m "style: ruff format новых файлов карточки

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §1 Данные (сид) → Task 1 ✓
- §2 Вьюха (счётчики) → Task 2 ✓
- §3 Шаблон (паспорт + бейдж + CSS) → Task 3 ✓
- §4 Тесты (view/template/fallback/seed) → распределены по Task 1–3 ✓
- Полная верификация → Task 4 ✓

**Placeholder scan:** плейсхолдеров нет — весь код приведён дословно.

**Type consistency:** `Article.Kind.SECTION/CHAPTER/ARTICLE` — значения
`section`/`chapter`/`article` (см. `documents/models.py`); классы бейджа
`status-{in_force,repealed,not_in_force}` совпадают с `Document.Status`
choices; `seed_corpus` использует `update_or_create(defaults=...)` —
добавление ключей в `SEED_ACTS` проставляет их на существующие документы.

## После реализации

- Прогнать `seed_corpus` на dev-БД, чтобы проставить даты на уже
  опубликованные ТК РФ / 426-ФЗ (обычная команда, не миграция).
- PR в `main` (база — `main`); Claude не мержит сам.
