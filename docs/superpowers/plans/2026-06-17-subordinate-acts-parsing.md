# Разбор подзаконных актов (постановления/приказы) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Научить систему разбирать подзаконные акты (постановления Правительства, приказы министерств) в структуру «пункты/приложения», не ломая кодексовый разбор.

**Architecture:** Отдельный парсер `parse_points` для типов `decree`/`order`; выбор разборщика по `doc_type` пробрасывается через `parse_text`/`parse_document`. Дерево строится тем же self-FK `Article.parent`, что и кодексы (через `parent_order`). Два новых вида элемента — `POINT`/`APPENDIX`. Гейты «ноль статей» смягчаются, чтобы законно-короткая подзаконка не считалась браком. Калибровка — на живой фикстуре.

**Tech Stack:** Python 3, Django, pytest (django_db на Postgres — Docker `lawiot-db`:5433 или WSL-фолбэк), bs4. Windows: запуск через `.venv\Scripts\python.exe` (bare `python` — зависающая Store-заглушка).

**Спека:** `docs/superpowers/specs/2026-06-17-subordinate-acts-parsing-design.md`

---

## Файловая структура

- **Изменить** `documents/models.py` — `Article.Kind` +`POINT`/`APPENDIX`; `_ANCHOR_PREFIX` +`point`/`appendix`.
- **Создать** `documents/migrations/0014_alter_article_kind.py` — авто-миграция (`AlterField`).
- **Изменить** `ingestion/parsing.py` — регэкспы `APPENDIX_RE`/`POINT_RE`, функция `parse_points`, параметр `doc_type` у `parse_text`/`parse_document`.
- **Изменить** `ingestion/services.py` — проводка `doc_type` в `ingest_target`/`reparse_redaction`/`import_manual`; `_article_count` считает и пункты; лог-строка узлов.
- **Изменить** `documents/views.py` — `point_count`/`appendix_count` в контекст.
- **Изменить** `templates/documents/document_detail.html` — счётчики структуры; `templates/documents/_article_node.html` + `_toc_node.html` — точка после номера только при наличии номера.
- **Создать тесты:** `ingestion/tests/test_parse_points.py`, `ingestion/tests/test_parse_dispatch.py`, `ingestion/tests/test_publish_gate_points.py`, `documents/tests/test_subordinate_kinds.py`, `documents/tests/test_card_points.py`.
- **Задача 6 (калибровка):** `ingestion/fixtures_raw/*.html` (живые), `docs/superpowers/notes/2026-06-17-subordinate-acts-characterization.md`, `ingestion/tests/test_real_subordinate_fixtures.py`.

---

### Task 1: Виды элемента «Пункт»/«Приложение» + якоря

**Files:**
- Modify: `documents/models.py:133-155` (класс `Article`, `Kind`, `_ANCHOR_PREFIX`)
- Create: `documents/migrations/0014_alter_article_kind.py` (генерируется)
- Test: `documents/tests/test_subordinate_kinds.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `documents/tests/test_subordinate_kinds.py`:

```python
from datetime import date

import pytest

from documents.models import Article, Document, Redaction


def test_kind_has_point_and_appendix_labels():
    assert Article.Kind.POINT.label == "Пункт"
    assert Article.Kind.APPENDIX.label == "Приложение"


@pytest.mark.django_db
def test_point_and_appendix_anchors_generated():
    doc = Document.objects.create(
        doc_type=Document.DocType.DECREE, title="Пост.", slug="anchor-doc"
    )
    red = Redaction.objects.create(document=doc, redaction_date=date(2020, 1, 1))
    point = Article.objects.create(
        redaction=red, kind=Article.Kind.POINT, number="1.1", order=1
    )
    appendix = Article.objects.create(
        redaction=red, kind=Article.Kind.APPENDIX, number="2", order=2
    )
    assert point.anchor == "p-1-1"
    assert appendix.anchor == "pril-2"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_subordinate_kinds.py -v`
Expected: FAIL — `AttributeError: POINT` (значения ещё нет).

- [ ] **Step 3: Добавить виды и префиксы якорей**

В `documents/models.py`, класс `Article.Kind` (сейчас строки 134-137):

```python
    class Kind(models.TextChoices):
        SECTION = "section", "Раздел"
        CHAPTER = "chapter", "Глава"
        ARTICLE = "article", "Статья"
        POINT = "point", "Пункт"
        APPENDIX = "appendix", "Приложение"
```

И `_ANCHOR_PREFIX` (сейчас строка 155):

```python
    _ANCHOR_PREFIX = {
        "section": "razdel",
        "chapter": "glava",
        "article": "st",
        "point": "p",
        "appendix": "pril",
    }
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `.venv\Scripts\python.exe manage.py makemigrations documents`
Expected: создан `documents/migrations/0014_alter_article_kind.py` (AlterField для `kind`).

- [ ] **Step 5: Запустить тесты — должны пройти**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_subordinate_kinds.py -v`
Expected: PASS (оба теста).

- [ ] **Step 6: Коммит**

```bash
git add documents/models.py documents/migrations/0014_alter_article_kind.py documents/tests/test_subordinate_kinds.py
git commit -m "feat(documents): виды элемента «Пункт»/«Приложение» + якоря"
```

---

### Task 2: Парсер подзаконных актов `parse_points`

**Files:**
- Modify: `ingestion/parsing.py` (после `parse_structure`, +регэкспы рядом с `CHAPTER_RE`)
- Test: `ingestion/tests/test_parse_points.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `ingestion/tests/test_parse_points.py`:

```python
from ingestion.parsing import parse_points


def test_top_level_points():
    nodes = parse_points("1. Первый пункт.\n2. Второй пункт.")
    assert [(n.kind, n.number) for n in nodes] == [("point", "1"), ("point", "2")]
    assert nodes[0].text == "Первый пункт."


def test_subpoint_nests_under_parent_point():
    nodes = parse_points("1. Общие положения.\n1.1. Первый подпункт.")
    parent, child = nodes[0], nodes[1]
    assert child.kind == "point" and child.number == "1.1"
    assert child.parent_order == parent.order


def test_appendix_is_container_for_following_points():
    nodes = parse_points("Приложение 1\nк постановлению\n1. Пункт приложения.")
    assert nodes[0].kind == "appendix" and nodes[0].number == "1"
    point = next(n for n in nodes if n.kind == "point")
    assert point.parent_order == nodes[0].order


def test_section_inside_appendix_reuses_codex_rules():
    nodes = parse_points("Приложение 1\nРаздел I. Общие положения\n1. Пункт.")
    assert [n.kind for n in nodes] == ["appendix", "section", "point"]
    appendix, section, point = nodes
    assert section.parent_order == appendix.order
    assert point.parent_order == section.order


def test_flat_act_without_points_yields_nothing():
    assert parse_points("Краткий приказ без нумерации, просто текст.") == []


def test_decimal_in_prose_is_not_a_point():
    assert parse_points("Срок 1 год.\nОплата 2.5 ставки месяца.") == []


def test_utverzhdeno_marks_appendix():
    nodes = parse_points("УТВЕРЖДЕНО\nпостановлением Правительства\n1. Пункт.")
    assert nodes[0].kind == "appendix"
    assert next(n for n in nodes if n.kind == "point").parent_order == nodes[0].order
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parse_points.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_points'`.

- [ ] **Step 3: Добавить регэкспы и функцию**

В `ingestion/parsing.py`, рядом с `CHAPTER_RE` (после строки 15) добавить:

```python
# Подзаконные акты разбираются по doc_type (см. parse_text).
POINT_DOC_TYPES = ("decree", "order")
# Заголовок приложения: «Приложение N …» / «УТВЕРЖДЕНО постановлением…».
# group(1) — номер (может отсутствовать), group(2) — остаток строки (для заголовка).
APPENDIX_RE = re.compile(
    r"^(?:Приложени\w*|УТВЕРЖД\w*)\b\s*(?:(?:N|№)\s*)?(\d+)?[.:]?\s*(.*)$",
    re.IGNORECASE,
)
# Пункт подзаконного акта: дроблёный номер В НАЧАЛЕ строки + текст: «1.», «1.1.», «12.3.».
# Требуем пробел и непустой текст после точки — чтобы «2.5 ставки» в прозе не считалось пунктом.
POINT_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")
```

В конец `ingestion/parsing.py` добавить функцию:

```python
def parse_points(text: str) -> list[ParsedArticle]:
    """Иерархический разбор подзаконного акта (постановление/приказ):
    приложения, разделы/главы (переиспользуя кодексовые SECTION_RE/CHAPTER_RE)
    и пункты «N.N.N». Вложенность пунктов — по дроблёному номеру (1.1 — потомок 1);
    верхнеуровневые пункты крепятся к ближайшему контейнеру (глава/раздел/приложение)."""
    nodes: list[ParsedArticle] = []
    order = 0
    current_appendix: int | None = None
    current_section: int | None = None
    current_chapter: int | None = None
    current_point: ParsedArticle | None = None
    point_by_number: dict[str, ParsedArticle] = {}
    body: list[str] = []

    def flush_point() -> None:
        nonlocal current_point
        if current_point is not None:
            current_point.text = "\n".join(body).strip()
            current_point = None

    def container() -> int | None:
        # Ближайший открытый контейнер для верхнеуровневого пункта.
        return current_chapter or current_section or current_appendix

    for line in text.splitlines():
        app = APPENDIX_RE.match(line)
        sec = SECTION_RE.match(line)
        chap = CHAPTER_RE.match(line)
        pt = POINT_RE.match(line)
        if app:
            flush_point()
            order += 1
            nodes.append(
                ParsedArticle(app.group(1) or "", app.group(2).strip(), "", order, "appendix", None)
            )
            current_appendix, current_section, current_chapter = order, None, None
            point_by_number = {}  # нумерация пунктов независима в каждом приложении
        elif sec:
            flush_point()
            order += 1
            nodes.append(
                ParsedArticle(sec.group(1), sec.group(2).strip(), "", order, "section", current_appendix)
            )
            current_section, current_chapter = order, None
        elif chap:
            flush_point()
            order += 1
            nodes.append(
                ParsedArticle(
                    chap.group(1), chap.group(2).strip(), "", order, "chapter",
                    current_section or current_appendix,
                )
            )
            current_chapter = order
        elif pt:
            flush_point()
            order += 1
            number, inline = pt.group(1), pt.group(2).strip()
            if "." in number:
                parent_node = point_by_number.get(number.rsplit(".", 1)[0])
                parent_order = parent_node.order if parent_node else container()
            else:
                parent_order = container()
            current_point = ParsedArticle(number, "", inline, order, "point", parent_order)
            nodes.append(current_point)
            point_by_number[number] = current_point
            body = [inline]
        elif current_point is not None:
            body.append(line)
    flush_point()
    return nodes
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parse_points.py -v`
Expected: PASS (все 7 тестов).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/parsing.py ingestion/tests/test_parse_points.py
git commit -m "feat(ingestion): парсер подзаконных актов parse_points (пункты/приложения)"
```

---

### Task 3: Выбор разборщика по типу документа

**Files:**
- Modify: `ingestion/parsing.py:135-154` (`parse_text`, `parse_document`)
- Modify: `ingestion/services.py:168` (`ingest_target`), `:223` (`import_manual`), `:244` (`reparse_redaction`)
- Test: `ingestion/tests/test_parse_dispatch.py`

- [ ] **Step 1: Написать падающий тест**

Создать `ingestion/tests/test_parse_dispatch.py`:

```python
from ingestion.parsing import parse_text


def test_decree_dispatches_to_points():
    doc = parse_text("1. Пункт первый.", doc_type="decree")
    assert [n.kind for n in doc.articles] == ["point"]


def test_order_dispatches_to_points():
    doc = parse_text("1. Пункт.", doc_type="order")
    assert doc.articles[0].kind == "point"


def test_default_dispatches_to_codex_structure():
    doc = parse_text("Статья 1. Сфера действия.", doc_type=None)
    assert doc.articles[0].kind == "article"


def test_federal_law_dispatches_to_codex_structure():
    doc = parse_text("Статья 1. Сфера действия.", doc_type="federal_law")
    assert doc.articles[0].kind == "article"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parse_dispatch.py -v`
Expected: FAIL — `TypeError: parse_text() got an unexpected keyword argument 'doc_type'`.

- [ ] **Step 3: Добавить параметр `doc_type` и развилку**

В `ingestion/parsing.py` заменить `parse_text` (строки 135-149) и `parse_document` (152-154):

```python
def parse_text(text: str, doc_type: str | None = None) -> ParsedDocument:
    """Разбор УЖЕ нормализованного текста (результат html_to_text):
    структура + заголовок-эвристика + реквизиты. Для подзаконных типов
    (decree/order) — разбор по пунктам/приложениям, иначе — кодексовый."""
    if doc_type in POINT_DOC_TYPES:
        articles = parse_points(text)
    else:
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


def parse_document(
    content: bytes, content_type: str = "text/html", doc_type: str | None = None
) -> ParsedDocument:
    """Полный разбор: нормализовать содержимое и разобрать (тонкая обёртка над parse_text)."""
    return parse_text(html_to_text(content, content_type), doc_type)
```

- [ ] **Step 4: Прокинуть `doc_type` из вызывающих в services.py**

В `ingestion/services.py`:

`ingest_target` — строка 168, заменить:
```python
        parsed = parse_text(text, target.document.doc_type)
```

`import_manual` — строка 223, заменить:
```python
    parsed = parse_document(content, content_type, document.doc_type)
```

`reparse_redaction` — строка 244, заменить:
```python
    parsed = parse_text(text, redaction.document.doc_type)
```

- [ ] **Step 5: Запустить тесты — должны пройти**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parse_dispatch.py -v`
Expected: PASS (4 теста).

- [ ] **Step 6: Регрессия — кодексовый разбор и приём не сломаны**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/ -q`
Expected: PASS (включая существующие тесты приёма/реального ТК РФ).

- [ ] **Step 7: Коммит**

```bash
git add ingestion/parsing.py ingestion/services.py ingestion/tests/test_parse_dispatch.py
git commit -m "feat(ingestion): выбор разборщика по doc_type (decree/order → пункты)"
```

---

### Task 4: Смягчить гейт «ноль статей» для подзаконки

**Files:**
- Modify: `ingestion/services.py:119-120` (`_article_count`), `:169-172` (лог-строка в `ingest_target`)
- Test: `ingestion/tests/test_publish_gate_points.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `ingestion/tests/test_publish_gate_points.py`:

```python
from datetime import date

import pytest

from documents.models import Article, Document, Redaction
from ingestion.services import _article_count, _is_safe_to_publish


@pytest.mark.django_db
def test_article_count_includes_points():
    doc = Document.objects.create(doc_type=Document.DocType.DECREE, title="П", slug="gate-1")
    red = Redaction.objects.create(document=doc, redaction_date=date(2020, 1, 1))
    Article.objects.create(redaction=red, kind=Article.Kind.POINT, number="1", order=1)
    Article.objects.create(redaction=red, kind=Article.Kind.POINT, number="2", order=2)
    assert _article_count(red) == 2


@pytest.mark.django_db
def test_decree_with_points_passes_publish_gate():
    doc = Document.objects.create(doc_type=Document.DocType.DECREE, title="П", slug="gate-2")
    red = Redaction.objects.create(
        document=doc, redaction_date=date(2020, 1, 1), full_text="текст"
    )
    Article.objects.create(redaction=red, kind=Article.Kind.POINT, number="1", order=1)
    assert _is_safe_to_publish(red, None) is True
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_publish_gate_points.py -v`
Expected: FAIL — `_article_count` вернёт 0 (считает только `ARTICLE`), `test_article_count_includes_points` упадёт.

- [ ] **Step 3: Считать пункты как содержательные единицы**

В `ingestion/services.py` заменить `_article_count` (строки 119-120):

```python
def _article_count(redaction):
    # Содержательные единицы: статьи (кодексы/ФЗ) И пункты (подзаконка).
    return redaction.articles.filter(
        kind__in=[Article.Kind.ARTICLE, Article.Kind.POINT]
    ).count()
```

И уточнить лог-строку в `ingest_target` (строки 169-172):

```python
        n_units = sum(1 for a in parsed.articles if a.kind in ("article", "point"))
        log_lines.append(
            f"Разобрано узлов структуры: {len(parsed.articles)} (статей/пунктов: {n_units})."
        )
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_publish_gate_points.py -v`
Expected: PASS (оба теста).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/services.py ingestion/tests/test_publish_gate_points.py
git commit -m "feat(ingestion): учитывать пункты в гейте авто-публикации подзаконки"
```

---

### Task 5: Показ пунктов/приложений в карточке

**Files:**
- Modify: `documents/views.py:81-83` (контекст `document_detail`)
- Modify: `templates/documents/document_detail.html:17-23` (паспорт «Структура»)
- Modify: `templates/documents/_article_node.html:3`, `templates/documents/_toc_node.html:2` (точка после номера только при номере)
- Test: `documents/tests/test_card_points.py`

- [ ] **Step 1: Написать падающий тест**

Создать `documents/tests/test_card_points.py`:

```python
from datetime import date

import pytest

from documents.models import Article, Document, Redaction


@pytest.mark.django_db
def test_passport_shows_point_and_appendix_counts(client, django_user_model):
    user = django_user_model.objects.create_user("reader", "r@e.ru", "pw")
    client.force_login(user)
    doc = Document.objects.create(
        doc_type=Document.DocType.DECREE,
        title="Постановление",
        slug="card-decree",
        status=Document.Status.IN_FORCE,
    )
    red = Redaction.objects.create(
        document=doc,
        redaction_date=date(2020, 1, 1),
        review_status=Redaction.ReviewStatus.PUBLISHED,
        is_current=True,
        full_text="текст",
    )
    appendix = Article.objects.create(
        redaction=red, kind=Article.Kind.APPENDIX, number="1", order=1
    )
    Article.objects.create(
        redaction=red, kind=Article.Kind.POINT, number="1", order=2, parent=appendix
    )
    resp = client.get(f"/doc/{doc.slug}/", SERVER_NAME="localhost")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "приложени" in html.lower()
    assert "пункт" in html.lower()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_card_points.py -v`
Expected: FAIL — слова «пункт»/«приложени» отсутствуют (счётчиков нет; узел рисуется, но «Структура» их не показывает) — уточнить по фактическому выводу.

- [ ] **Step 3: Добавить счётчики в контекст**

В `documents/views.py`, словарь контекста (строки 81-83) — добавить две строки после `article_count`:

```python
            "section_count": kind_counts.get(Article.Kind.SECTION, 0),
            "chapter_count": kind_counts.get(Article.Kind.CHAPTER, 0),
            "article_count": kind_counts.get(Article.Kind.ARTICLE, 0),
            "point_count": kind_counts.get(Article.Kind.POINT, 0),
            "appendix_count": kind_counts.get(Article.Kind.APPENDIX, 0),
```

- [ ] **Step 4: Показать счётчики в паспорте**

В `templates/documents/document_detail.html` заменить блок «Структура» (строки 17-23):

```html
      <dt>Структура</dt>
      <dd>
        {% if section_count %}{{ section_count }} раздел(ов) · {% endif %}
        {% if chapter_count %}{{ chapter_count }} глав(ы) · {% endif %}
        {% if appendix_count %}{{ appendix_count }} приложени(й) · {% endif %}
        {% if point_count %}{{ point_count }} пункт(ов) · {% endif %}
        {% if article_count %}{{ article_count }} статей{% endif %}
        {% if not section_count and not chapter_count and not article_count and not point_count and not appendix_count %}—{% endif %}
      </dd>
```

- [ ] **Step 5: Точка после номера только при наличии номера (для «УТВЕРЖДЕНО» без номера)**

В `templates/documents/_article_node.html` строка 3 — заменить:

```html
  <h{{ level }}>{{ node.get_kind_display }}{% if node.number %} {{ node.number }}.{% endif %}{% if node.title %} {{ node.title }}{% endif %}</h{{ level }}>
```

В `templates/documents/_toc_node.html` строка 2 — заменить:

```html
  <a href="#{{ node.anchor }}">{{ node.get_kind_display }}{% if node.number %} {{ node.number }}.{% endif %}{% if node.title %} {{ node.title }}{% endif %}</a>
```

- [ ] **Step 6: Запустить тест — должен пройти**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_card_points.py -v`
Expected: PASS.

- [ ] **Step 7: Регрессия карточки ТК РФ (статьи рендерятся как прежде)**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_document_card.py documents/tests/test_views.py -q`
Expected: PASS (вид статей «Статья 81. …» не изменился — у статей номер всегда есть).

- [ ] **Step 8: Коммит**

```bash
git add documents/views.py templates/documents/document_detail.html templates/documents/_article_node.html templates/documents/_toc_node.html documents/tests/test_card_points.py
git commit -m "feat(documents): показ пунктов/приложений в карточке акта"
```

---

### Task 6: Калибровка на живой фикстуре + приёмочный тест ⚠️ ТРЕБУЕТ `nd=`-АДРЕСОВ ОТ ПОЛЬЗОВАТЕЛЯ

**Зависимость:** для этой задачи нужны URL одного **постановления** и одного **приказа** с pravo.gov.ru ИПС в формате `http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=<ID>&print=1` (headless-поиск по сайту у агента не работает — ID даёт пользователь из браузера). Без них задача не выполняется; Задачи 1-5 от неё не зависят.

**Files:**
- Create: `ingestion/fixtures_raw/decree_real.html`, `ingestion/fixtures_raw/order_real.html`
- Create: `docs/superpowers/notes/2026-06-17-subordinate-acts-characterization.md`
- Create: `ingestion/tests/test_real_subordinate_fixtures.py`

- [ ] **Step 1: Захватить живые фикстуры**

Run (подставить ID от пользователя):
```bash
.venv\Scripts\python.exe manage.py capture_fixture "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=<DECREE_ID>&print=1" ingestion/fixtures_raw/decree_real.html
.venv\Scripts\python.exe manage.py capture_fixture "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=<ORDER_ID>&print=1" ingestion/fixtures_raw/order_real.html
```
Expected: «Сохранено N байт … → …» для обоих.

- [ ] **Step 2: Снять реальную структуру (характеризация)**

Run (Django shell — посчитать, что разобралось):
```bash
.venv\Scripts\python.exe manage.py shell -c "from pathlib import Path; from ingestion.parsing import parse_text, html_to_text; from collections import Counter; t=html_to_text(Path('ingestion/fixtures_raw/decree_real.html').read_bytes(),'text/html'); a=parse_text(t,'decree').articles; print('decree', Counter(n.kind for n in a), 'orphans', sum(1 for n in a if n.parent_order is None and n.kind=='point'))"
```
Записать результат (число пунктов, приложений, есть ли «сироты»-пункты без контейнера) в `docs/superpowers/notes/2026-06-17-subordinate-acts-characterization.md` вместе с замеченными особенностями нумерации. Повторить для `order_real.html`.

- [ ] **Step 3: При необходимости — подстроить регэкспы**

Если характеризация показала пропуски (приложения не распознались, пункты «слиплись», ложные пункты из прозы) — поправить `APPENDIX_RE`/`POINT_RE` в `ingestion/parsing.py`, повторно прогнать `ingestion/tests/test_parse_points.py` (синтетические инварианты не должны сломаться) и пересчитать характеризацию. Это и есть «настройка по реальному образцу».

- [ ] **Step 4: Написать приёмочный тест с полами из характеризации**

Создать `ingestion/tests/test_real_subordinate_fixtures.py` (пороги `>=` взять из заметки Шага 2, на ~10% ниже фактических, по образцу `ingestion/tests/test_real_fixtures.py`):

```python
from collections import Counter
from pathlib import Path

from ingestion.parsing import html_to_text, parse_text

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures_raw"


def _counts(name, doc_type):
    text = html_to_text((FIXTURES / name).read_bytes(), "text/html")
    nodes = parse_text(text, doc_type).articles
    return nodes, Counter(n.kind for n in nodes)


def test_real_decree_parses_into_points():
    nodes, kinds = _counts("decree_real.html", "decree")
    assert kinds["point"] >= POINT_FLOOR_DECREE  # из характеризации
    # 0 «сирот»: каждый узел с parent_order ссылается на существующий order
    orders = {n.order for n in nodes}
    assert all(n.parent_order in orders for n in nodes if n.parent_order is not None)


def test_real_order_parses_into_points():
    nodes, kinds = _counts("order_real.html", "order")
    assert kinds["point"] >= POINT_FLOOR_ORDER  # из характеризации
    orders = {n.order for n in nodes}
    assert all(n.parent_order in orders for n in nodes if n.parent_order is not None)
```
Заменить `POINT_FLOOR_DECREE`/`POINT_FLOOR_ORDER` на конкретные числа из Шага 2 (определить как модульные константы вверху файла).

- [ ] **Step 5: Запустить приёмочный тест**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_real_subordinate_fixtures.py -v`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add ingestion/fixtures_raw/decree_real.html ingestion/fixtures_raw/order_real.html docs/superpowers/notes/2026-06-17-subordinate-acts-characterization.md ingestion/tests/test_real_subordinate_fixtures.py ingestion/parsing.py
git commit -m "test(ingestion): приёмка разбора подзаконки на живых фикстурах + калибровка"
```

---

## Финальная проверка

- [ ] **Весь набор тестов зелёный**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (все прежние + новые; кодексовый разбор ТК РФ не регрессировал).

- [ ] **Линтер чист**

Run: `.venv\Scripts\python.exe -m ruff check .`
Expected: без ошибок.

---

## Самопроверка плана (для автора)

- **Покрытие спеки:** модель (Task 1) ✓; parse_points с пунктами/приложениями/разделами (Task 2) ✓; выбор по doc_type (Task 3) ✓; смягчение гейтов (Task 4) ✓; показ + счётчики (Task 5) ✓; живые фикстуры/приёмка/де-риск (Task 6) ✓. Вне scope (письма, под-подпункты, таблицы, источники, связи) — не включены, верно.
- **Зависимость на `nd=`-адреса** изолирована в Task 6; Tasks 1-5 самодостаточны и дают рабочий, тестируемый код без участия пользователя.
- **Типы/имена:** `parse_points(text) -> list[ParsedArticle]`, `parse_text(text, doc_type=None)`, `parse_document(content, content_type, doc_type=None)`, `Article.Kind.POINT/APPENDIX`, `_article_count` — согласованы между задачами.
