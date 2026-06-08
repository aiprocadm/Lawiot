# Шаг 10: Реальный сид-корпус трудового права + закалка парсера — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Завести реальный стартовый корпус трудового права (ТК РФ + 5–15 ключевых актов) из `pravo.gov.ru`, закалить парсер под реальные форматы (иерархия раздел→глава→статья, эвристика заголовка/реквизитов, PDF), и провести сквозную приёмочную проверку «поиск → просмотр → связи».

**Architecture:** Шаг 10 — финал MVP по §16 спецификации. Делится на два пласта: **(1) закалка парсера** — чистый код, разрабатывается TDD на *синтетическом* тексте (детерминированно, как в существующем `ingestion/tests/test_parsing.py`); **(2) наполнение и курирование данных** — операционная работа через Django admin, проверяется характеризационными тестами на реальных фикстурах + ручной приёмкой. Реальные артефакты `pravo.gov.ru` сохраняются в `ingestion/fixtures_raw/` как тестовые фикстуры (детерминизм, без живой сети в тестах — §12 спеки). Существующий конвейер `ingest_target`/`import_manual`/`reparse_redaction` не переписывается — иерархия добавляется в чистый слой `parsing.py` и протягивается через `create_draft_from_parsed`.

**Tech Stack:** Django + PostgreSQL, `httpx` (fetch), `beautifulsoup4`/`html.parser` (HTML), `pdfminer.six` (PDF — новая зависимость), pytest + pytest-django, ruff.

**Порядок фаз (важно):**
- **Фаза 0** (спайк) — захватить реальные фикстуры и описать их. Выполняется ПЕРВОЙ, разблокирует приёмочные проверки.
- **Фазы 1–3** (парсер) — TDD на синтетическом тексте, НЕ зависят от Фазы 0, могут идти параллельно после неё.
- **Фаза 4** (корпус) — сид-команда + реальные `Document`.
- **Фаза 5** (приёмка) — характеризация на реальных фикстурах + ручной runbook куратора.

**Проверка после каждой фазы (см. [[lawiot-lint-scope]]):**
```
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pytest
```
Базовая линия до начала: **109 тестов зелёные**. Использовать venv-python — bare `python` на Windows зависает (см. [[windows-python-env]]).

---

## Структура файлов

| Файл | Что делает | Действие |
|---|---|---|
| `ingestion/management/commands/capture_fixture.py` | Скачать URL и сохранить байты в `fixtures_raw/` (инструмент спайка) | Create |
| `docs/superpowers/notes/2026-06-08-real-fixtures-characterization.md` | Описание реальной структуры захваченных актов | Create |
| `ingestion/fixtures_raw/tk_rf_real.html` (и др.) | Реальные артефакты pravo.gov.ru как фикстуры | Create (захват) |
| `ingestion/parsing.py` | Иерархия раздел→глава→статья; эвристика заголовка; диспетч PDF/HTML | Modify |
| `ingestion/services.py:51-88` (`create_draft_from_parsed`) | Создавать Article с `kind` и `parent` из иерархии | Modify |
| `ingestion/tests/test_parsing.py` | Юнит-тесты иерархии/заголовка/PDF на синтетике | Modify |
| `ingestion/tests/test_real_fixtures.py` | Характеризация реальных фикстур (инварианты ТК РФ) | Create |
| `pyproject.toml` | Добавить `pdfminer.six` | Modify |
| `documents/seed/labor_law.py` | Декларативный список сид-актов (реквизиты + source_url) | Create |
| `documents/management/commands/seed_corpus.py` | Идемпотентно завести `Document` из списка | Create |
| `documents/tests/test_seed_corpus.py` | Тест идемпотентности и корректности сид-команды | Create |
| `docs/superpowers/runbooks/2026-06-08-curator-acceptance.md` | Чек-лист куратора: приём→ревью→публикация→приёмка | Create |

---

## Фаза 0: Спайк — захватить и описать реальные данные

> Цель фазы: получить настоящие артефакты `pravo.gov.ru`, чтобы Фаза 5 опиралась на реальность, а не на догадки. Парсерные фазы 1–3 от неё не зависят (тестируются на синтетике).

### Task 0.1: Команда захвата фикстуры

**Files:**
- Create: `ingestion/management/commands/capture_fixture.py`
- Test: `ingestion/tests/test_commands.py` (добавить тест)

- [ ] **Step 1: Написать падающий тест**

В `ingestion/tests/test_commands.py` добавить (паттерн MockTransport — как в существующих тестах команд):

```python
def test_capture_fixture_writes_file(tmp_path):
    import httpx
    from django.core.management import call_command

    def handler(request):
        return httpx.Response(200, content=b"<html>hi</html>",
                              headers={"content-type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = tmp_path / "sample.html"
    call_command("capture_fixture", "https://example.test/act", str(out), client=client)
    assert out.read_bytes() == b"<html>hi</html>"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_commands.py::test_capture_fixture_writes_file -v`
Expected: FAIL — `Unknown command: 'capture_fixture'`.

- [ ] **Step 3: Реализовать команду**

`ingestion/management/commands/capture_fixture.py`:

```python
from pathlib import Path

from django.core.management.base import BaseCommand

from ingestion.fetching import fetch


class Command(BaseCommand):
    help = "Скачать URL и сохранить сырьё в файл-фикстуру (инструмент разработки)."

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("out_path")

    def handle(self, *args, url, out_path, client=None, **options):
        result = fetch(url, client=client)
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.content)
        self.stdout.write(
            self.style.SUCCESS(
                f"Сохранено {len(result.content)} байт ({result.content_type}) → {path}"
            )
        )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_commands.py::test_capture_fixture_writes_file -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/management/commands/capture_fixture.py ingestion/tests/test_commands.py
git commit -m "feat(ingestion): capture_fixture command for saving real source artifacts"
```

### Task 0.2: Захватить реальные фикстуры и описать их

> Это РУЧНОЙ исследовательский шаг (живая сеть, вне тестов). Результат — закоммиченные фикстуры + заметка-характеризация, которая даст точные значения для приёмочных тестов Фазы 5.

- [ ] **Step 1: Найти рабочие URL актуальных редакций.** Открыть `pravo.gov.ru` / `publication.pravo.gov.ru`, найти ТК РФ (197-ФЗ) и 2–3 подзаконных акта трудового права. Зафиксировать прямые URL текста (HTML) и, если попадётся, PDF-акт.

- [ ] **Step 2: Захватить фикстуры** (запускать с активным `.venv`, нужна сеть):

```
.venv\Scripts\python.exe manage.py capture_fixture "<URL ТК РФ>" ingestion/fixtures_raw/tk_rf_real.html
.venv\Scripts\python.exe manage.py capture_fixture "<URL подзаконного акта>" ingestion/fixtures_raw/<slug>.html
.venv\Scripts\python.exe manage.py capture_fixture "<URL PDF-акта>" ingestion/fixtures_raw/<slug>.pdf
```

- [ ] **Step 3: Осмотреть захваченное.** Для каждой фикстуры запустить в `.venv\Scripts\python.exe manage.py shell` существующий `html_to_text` и глазами проверить: как выглядят строки «Раздел …», «Глава …», «Статья …»; есть ли мусорные блоки (навигация, футер); как подаётся заголовок и реквизиты; для PDF — извлекается ли текст.

- [ ] **Step 4: Записать характеризацию.** Создать `docs/superpowers/notes/2026-06-08-real-fixtures-characterization.md` с разделами на каждый акт: точные образцы строк разделов/глав/статей (скопировать 2–3 реальные строки каждого уровня), наблюдаемое число статей, как выглядит заголовок, какой мусор отрезать, content-type PDF. **Эти значения — вход для тестов Фазы 5.**

- [ ] **Step 5: Commit**

```bash
git add ingestion/fixtures_raw/ docs/superpowers/notes/2026-06-08-real-fixtures-characterization.md
git commit -m "test(ingestion): capture real pravo.gov.ru fixtures + characterization notes"
```

---

## Фаза 1: Иерархия раздел → глава → статья (TDD на синтетике)

> Парсер начинает распознавать «Раздел N»/«Глава N» и строить дерево `parent`. Тесты — на синтетическом тексте: точные, детерминированные, реальная фикстура не нужна.

### Task 1.1: Распознавание заголовков разделов и глав

**Files:**
- Modify: `ingestion/parsing.py:9` (регэкспы), `:12-24` (датакласс `ParsedArticle`)
- Test: `ingestion/tests/test_parsing.py`

- [ ] **Step 1: Написать падающий тест**

В `ingestion/tests/test_parsing.py`:

```python
from ingestion.parsing import parse_structure  # новое имя иерархического парсера


SYNTHETIC = """Трудовой кодекс Российской Федерации
Раздел I. Общие положения
Глава 1. Основные начала трудового законодательства
Статья 1. Цели и задачи трудового законодательства
Целями трудового законодательства являются...
Статья 2. Основные принципы
Текст статьи два.
Раздел II. Социальное партнёрство
Глава 2. Общие понятия
Статья 23. Понятие социального партнёрства
Текст статьи 23."""


def test_parse_structure_detects_sections_and_chapters():
    nodes = parse_structure(SYNTHETIC)
    kinds = [(n.kind, n.number) for n in nodes]
    assert ("section", "I") in kinds
    assert ("section", "II") in kinds
    assert ("chapter", "1") in kinds
    assert ("chapter", "2") in kinds
    assert ("article", "1") in kinds
    assert ("article", "23") in kinds
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_parse_structure_detects_sections_and_chapters -v`
Expected: FAIL — `cannot import name 'parse_structure'`.

- [ ] **Step 3: Реализовать распознавание + датакласс**

В `ingestion/parsing.py` добавить регэкспы и поля `kind`/`parent_order` в `ParsedArticle`, затем `parse_structure`:

```python
# Раздел римской цифрой: «Раздел I. Общие положения»
SECTION_RE = re.compile(r"^Раздел\s+([IVXLCDM]+)\.?\s*(.*)$")
# Глава арабской цифрой: «Глава 1. Основные начала» / «Глава 12.1. …»
CHAPTER_RE = re.compile(r"^Глава\s+(\d+(?:\.\d+)?)\.?\s*(.*)$")
```

Расширить датакласс:

```python
@dataclass
class ParsedArticle:
    number: str
    title: str
    text: str
    order: int
    kind: str = "article"          # "section" | "chapter" | "article"
    parent_order: int | None = None  # order ближайшего родителя выше по дереву
```

Реализовать `parse_structure` (единый проход; раздел сбрасывает текущую главу/статью, глава — текущую статью; текст копится только под статьёй):

```python
def parse_structure(text: str) -> list[ParsedArticle]:
    """Иерархический разбор: разделы/главы/статьи в порядке следования.
    parent_order указывает на order ближайшего раздела (для главы) или главы/раздела (для статьи)."""
    nodes: list[ParsedArticle] = []
    order = 0
    current_section: int | None = None
    current_chapter: int | None = None
    current_article: ParsedArticle | None = None
    body: list[str] = []

    def flush_article():
        nonlocal current_article
        if current_article is not None:
            current_article.text = "\n".join(body).strip()
            current_article = None

    for line in text.splitlines():
        sec = SECTION_RE.match(line)
        chap = CHAPTER_RE.match(line)
        art = ARTICLE_RE.match(line)
        if sec:
            flush_article()
            order += 1
            nodes.append(ParsedArticle(sec.group(1), sec.group(2).strip(), "", order, "section", None))
            current_section, current_chapter = order, None
        elif chap:
            flush_article()
            order += 1
            nodes.append(ParsedArticle(chap.group(1), chap.group(2).strip(), "", order, "chapter", current_section))
            current_chapter = order
        elif art:
            flush_article()
            order += 1
            parent = current_chapter if current_chapter is not None else current_section
            current_article = ParsedArticle(art.group(1), art.group(2).strip(), "", order, "article", parent)
            nodes.append(current_article)
            body = []
        elif current_article is not None:
            body.append(line)
    flush_article()
    return nodes
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_parse_structure_detects_sections_and_chapters -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/parsing.py ingestion/tests/test_parsing.py
git commit -m "feat(parsing): parse_structure recognizes sections and chapters"
```

### Task 1.2: Корректное дерево parent и текст под статьёй

**Files:**
- Test: `ingestion/tests/test_parsing.py`
- Modify: `ingestion/parsing.py` (только если тест выявит баг)

- [ ] **Step 1: Написать падающий тест на дерево и текст**

```python
def test_parse_structure_parent_links_and_text():
    nodes = parse_structure(SYNTHETIC)
    by_order = {n.order: n for n in nodes}
    chapter1 = next(n for n in nodes if n.kind == "chapter" and n.number == "1")
    section1 = next(n for n in nodes if n.kind == "section" and n.number == "I")
    article1 = next(n for n in nodes if n.kind == "article" and n.number == "1")
    # глава 1 принадлежит разделу I
    assert by_order[chapter1.parent_order] is section1
    # статья 1 принадлежит главе 1
    assert by_order[article1.parent_order] is chapter1
    # текст статьи 1 захвачен, заголовки в текст не попали
    assert "Целями трудового законодательства" in article1.text
    assert "Статья 2" not in article1.text
```

- [ ] **Step 2: Запустить**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_parse_structure_parent_links_and_text -v`
Expected: PASS (логика из 1.1 это уже покрывает) — если FAIL, починить `parse_structure` минимально.

- [ ] **Step 3: Тест регресса плоских актов** (акт без разделов/глав, только статьи — иерархия не должна ломать старое поведение):

```python
def test_parse_structure_flat_act_only_articles():
    flat = "Преамбула акта\nСтатья 1. Первая\nТекст.\nСтатья 2. Вторая\nЕщё текст."
    nodes = parse_structure(flat)
    assert [n.kind for n in nodes] == ["article", "article"]
    assert all(n.parent_order is None for n in nodes)
```

- [ ] **Step 4: Запустить весь файл тестов парсера**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -v`
Expected: PASS (включая старые `parse_articles`-тесты).

- [ ] **Step 5: Commit**

```bash
git add ingestion/tests/test_parsing.py ingestion/parsing.py
git commit -m "test(parsing): parent tree + text capture + flat-act regression"
```

### Task 1.3: Протянуть иерархию через parse_document и create_draft_from_parsed

**Files:**
- Modify: `ingestion/parsing.py` (`parse_document` → возвращать иерархию), `ingestion/services.py:79-87` (создание Article с kind/parent)
- Test: `ingestion/tests/test_services.py`

- [ ] **Step 1: Написать падающий тест уровня сервиса**

В `ingestion/tests/test_services.py` (использует БД, фабрики из `documents/tests/factories.py`):

```python
@pytest.mark.django_db
def test_create_draft_persists_hierarchy():
    from documents.models import Article, Document
    from ingestion.parsing import parse_document
    from ingestion.services import create_draft_from_parsed

    html = (
        b"<html><body>"
        b"Закon о труде\nРаздел I. Общие положения\nГлава 1. Начала\n"
        b"Статья 1. Цели\nТекст статьи 1.\n"
        b"</body></html>"
    )
    doc = Document.objects.create(slug="hier-test", doc_type=Document.DocType.OTHER, title="t")
    parsed = parse_document(html, "text/html")
    redaction = create_draft_from_parsed(doc, parsed)
    section = redaction.articles.get(kind=Article.Kind.SECTION, number="I")
    chapter = redaction.articles.get(kind=Article.Kind.CHAPTER, number="1")
    article = redaction.articles.get(kind=Article.Kind.ARTICLE, number="1")
    assert chapter.parent_id == section.id
    assert article.parent_id == chapter.id
    assert article.anchor == "st-1"  # якорь генерируется в Article.save()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py::test_create_draft_persists_hierarchy -v`
Expected: FAIL — `parse_document` ещё возвращает плоские статьи без `kind`/`parent_order`, у Article нет parent.

- [ ] **Step 3: Обновить `parse_document`** — использовать `parse_structure` вместо `parse_articles`:

```python
def parse_document(content: bytes, content_type: str = "text/html") -> ParsedDocument:
    """Полный разбор: текст + иерархия (разделы/главы/статьи) + заголовок-эвристика."""
    text = content_to_text(content, content_type)  # см. Фазу 3 (пока = html_to_text)
    articles = parse_structure(text)
    title = detect_title(text)  # см. Фазу 2 (пока = первая нестатейная строка)
    return ParsedDocument(full_text=text, title=title, articles=articles)
```

> На этом шаге `content_to_text`/`detect_title` ещё не существуют — временно оставить вызовы `html_to_text(content, content_type)` и старую эвристику заголовка; Фазы 2–3 заменят их. Чтобы не плодить переименования, можно сразу ввести тонкие алиасы: `content_to_text = html_to_text` и локальную `detect_title`. Выбрать один вариант и держаться его.

- [ ] **Step 4: Обновить `create_draft_from_parsed`** в `ingestion/services.py` — создавать Article с `kind` и `parent`, резолвя `parent_order` в уже созданные объекты:

```python
        order_to_article = {}
        for parsed_article in parsed.articles:
            parent = (
                order_to_article.get(parsed_article.parent_order)
                if parsed_article.parent_order is not None
                else None
            )
            obj = Article.objects.create(
                redaction=redaction,
                kind=parsed_article.kind,
                number=parsed_article.number,
                title=parsed_article.title,
                text=parsed_article.text,
                order=parsed_article.order,
                parent=parent,
            )
            order_to_article[parsed_article.order] = obj
```

> Порядок `parsed.articles` уже топологический (родитель идёт раньше ребёнка по `order`), поэтому одного прохода достаточно — родитель всегда создан раньше.

- [ ] **Step 5: Запустить тест и весь модуль**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ingestion/parsing.py ingestion/services.py ingestion/tests/test_services.py
git commit -m "feat(ingestion): persist section/chapter/article hierarchy in drafts"
```

---

## Фаза 2: Эвристика заголовка и реквизитов (#1282, на синтетике)

> Текущий заголовок = первая нестатейная строка ([parsing.py:71-74](ingestion/parsing.py)) — на реальных страницах это часто навигация/мусор. Делаем устойчивее. Реквизиты (номер, дата) — best-effort подсказка куратору, НЕ автозаполнение Document.

### Task 2.1: Устойчивая эвристика заголовка

**Files:**
- Modify: `ingestion/parsing.py`
- Test: `ingestion/tests/test_parsing.py`

- [ ] **Step 1: Написать падающий тест**

```python
from ingestion.parsing import detect_title


def test_detect_title_prefers_act_keyword_line():
    text = (
        "Главная\nПоиск\nОфициальный интернет-портал\n"
        "Трудовой кодекс Российской Федерации\n"
        "Раздел I. Общие положения\nСтатья 1. Цели"
    )
    assert detect_title(text) == "Трудовой кодекс Российской Федерации"


def test_detect_title_falls_back_to_first_meaningful_line():
    text = "Некий акт без ключевых слов\nСтатья 1. Что-то"
    assert detect_title(text) == "Некий акт без ключевых слов"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -k detect_title -v`
Expected: FAIL — `cannot import name 'detect_title'`.

- [ ] **Step 3: Реализовать `detect_title`**

```python
# Ключевые слова в наименовании НПА — приоритетные кандидаты в заголовок.
TITLE_KEYWORDS = ("кодекс", "федеральный закон", "постановление", "приказ", "закон")
_TITLE_SKIP = {"главная", "поиск", "официальный интернет-портал"}


def detect_title(text: str) -> str:
    """Заголовок акта: первая строка с ключевым словом НПА; иначе — первая
    осмысленная нестатейная строка (не навигация, длиннее 10 символов)."""
    candidates = [
        line for line in text.splitlines()
        if line and not ARTICLE_RE.match(line)
        and not SECTION_RE.match(line) and not CHAPTER_RE.match(line)
    ]
    for line in candidates:
        low = line.lower()
        if any(k in low for k in TITLE_KEYWORDS):
            return line
    for line in candidates:
        if len(line) > 10 and line.lower() not in _TITLE_SKIP:
            return line
    return candidates[0] if candidates else ""
```

- [ ] **Step 4: Запустить**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -k detect_title -v`
Expected: PASS.

- [ ] **Step 5: Подключить в `parse_document`** — заменить inline-цикл заголовка вызовом `detect_title(text)` (если ещё не сделано в Task 1.3).

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ingestion/parsing.py ingestion/tests/test_parsing.py
git commit -m "feat(parsing): robust title heuristic (#1282)"
```

### Task 2.2: Подсказка реквизитов (номер ФЗ / дата) для куратора

**Files:**
- Modify: `ingestion/parsing.py` (поля `detected_number`, `detected_date` в `ParsedDocument`)
- Test: `ingestion/tests/test_parsing.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_parse_document_extracts_requisite_hints():
    html = "Федеральный закон от 30.12.2001 N 197-ФЗ\nСтатья 1. Цели".encode()
    parsed = parse_document(html, "text/html")
    assert parsed.detected_number == "197-ФЗ"
    assert parsed.detected_date == "30.12.2001"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_parse_document_extracts_requisite_hints -v`
Expected: FAIL — у `ParsedDocument` нет полей `detected_number`/`detected_date`.

- [ ] **Step 3: Реализовать**

Расширить `ParsedDocument` и добавить извлечение (переиспользуя токен из `links.py` для номеров ФЗ):

```python
NUMBER_HINT_RE = re.compile(r"\b(\d{1,4}-(?:ФЗ|ФКЗ))\b")
DATE_HINT_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
```

```python
@dataclass
class ParsedDocument:
    full_text: str
    title: str = ""
    articles: list[ParsedArticle] = field(default_factory=list)
    detected_number: str = ""
    detected_date: str = ""
```

В `parse_document` после вычисления `text`:

```python
    num = NUMBER_HINT_RE.search(text)
    dt = DATE_HINT_RE.search(text)
    return ParsedDocument(
        full_text=text, title=title, articles=articles,
        detected_number=num.group(1) if num else "",
        detected_date=dt.group(1) if dt else "",
    )
```

- [ ] **Step 4: Запустить**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_parse_document_extracts_requisite_hints -v`
Expected: PASS.

> Подсказки реквизитов в этом плане только извлекаются и доступны в `ParsedDocument`/логе приёма; автозаполнение полей `Document` остаётся за куратором (юридическая корректность — §2 спеки). Отображение подсказок в admin — опционально, вне scope.

- [ ] **Step 5: Commit**

```bash
git add ingestion/parsing.py ingestion/tests/test_parsing.py
git commit -m "feat(parsing): extract requisite hints (FZ number, date) for curator"
```

---

## Фаза 3: Поддержка PDF (`pdfminer.six`)

> Часть подзаконных актов на портале — PDF. Сейчас `html_to_text` для не-HTML декодирует байты как UTF-8 → мусор. Добавляем ветку PDF.

### Task 3.1: Добавить зависимость pdfminer.six

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Добавить зависимость** в секцию dependencies `pyproject.toml`:

```
"pdfminer.six",
```

- [ ] **Step 2: Установить**

Run: `.venv\Scripts\python.exe -m pip install pdfminer.six`
Expected: успешная установка.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pdfminer.six for PDF ingestion"
```

### Task 3.2: Диспетчер контента + извлечение PDF

**Files:**
- Modify: `ingestion/parsing.py`
- Test: `ingestion/tests/test_parsing.py`
- Использовать фикстуру `ingestion/fixtures_raw/<slug>.pdf` из Task 0.2

- [ ] **Step 1: Написать падающий тест на реальном PDF-фикстуре**

```python
from pathlib import Path

from ingestion.parsing import content_to_text

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures_raw"


def test_content_to_text_extracts_pdf():
    pdf_bytes = (FIXTURES / "<slug>.pdf").read_bytes()  # имя из Task 0.2
    text = content_to_text(pdf_bytes, "application/pdf")
    # ЗАПОЛНИТЬ из характеризации (Task 0.2): фраза, заведомо присутствующая в этом акте
    assert "<известная фраза из PDF>" in text
```

> `<slug>` и `<известная фраза>` берутся из заметки-характеризации Task 0.2 — это данные захваченного артефакта, не дизайн. Если PDF-акт в Фазе 0 не нашёлся, Task 3.2 откладывается до появления реального PDF-акта в корпусе (зафиксировать в runbook).

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_content_to_text_extracts_pdf -v`
Expected: FAIL — `cannot import name 'content_to_text'` (или мусор вместо текста).

- [ ] **Step 3: Реализовать диспетчер + PDF-ветку**

В `ingestion/parsing.py`:

```python
from io import BytesIO

from pdfminer.high_level import extract_text as pdf_extract_text


def pdf_to_text(content: bytes) -> str:
    raw = pdf_extract_text(BytesIO(content))
    lines = [line.strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def content_to_text(content: bytes, content_type: str = "text/html") -> str:
    """Единая точка входа: PDF → pdfminer; HTML → bs4; иначе → UTF-8."""
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return pdf_to_text(content)
    return html_to_text(content, content_type)
```

Убедиться, что `parse_document` вызывает `content_to_text` (а не напрямую `html_to_text`).

- [ ] **Step 4: Запустить**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_parsing.py::test_content_to_text_extracts_pdf -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/parsing.py ingestion/tests/test_parsing.py ingestion/fixtures_raw/
git commit -m "feat(parsing): PDF text extraction via pdfminer.six"
```

---

## Фаза 4: Декларация и заведение реального сид-корпуса

> Реальные `Document` заводятся идемпотентной командой из декларативного списка. Реквизиты — из официальных источников (вносит куратор/автор плана), `source_url` — рабочие URL из Фазы 0.

### Task 4.1: Декларативный список сид-актов

**Files:**
- Create: `documents/seed/__init__.py`, `documents/seed/labor_law.py`

- [ ] **Step 1: Создать пакет и список**

`documents/seed/__init__.py` — пустой.
`documents/seed/labor_law.py`:

```python
"""Стартовый корпус трудового права. source_url заполняются рабочими ссылками
из Фазы 0 (спайк). auto_ingest=True только для актов с проверенным парсером."""

SEED_ACTS = [
    {
        "slug": "tk-rf",
        "doc_type": "code",
        "title": "Трудовой кодекс Российской Федерации",
        "official_number": "197-ФЗ",
        "issuing_body": "Федеральное Собрание Российской Федерации",
        "status": "in_force",
        "source_url": "",      # ЗАПОЛНИТЬ из Task 0.2
        "auto_ingest": False,  # включить после успешной приёмки (Фаза 5)
    },
    # Кандидаты подзаконки трудового права (реквизиты/URL уточнить по официальному источнику):
    # «О специальной оценке условий труда» 426-ФЗ;
    # «О профессиональных союзах, их правах и гарантиях деятельности» 10-ФЗ;
    # «О минимальном размере оплаты труда» 82-ФЗ;
    # «О занятости населения в Российской Федерации» 565-ФЗ;
    # ключевые постановления Правительства/приказы Минтруда.
    # Добавлять по одному после прохождения приёмки на ТК РФ.
]
```

> Реквизиты сверять с официальным источником, не с коммерческими СПС (§2 спеки — нельзя копировать продукты КонсультантПлюс/Гарант).

- [ ] **Step 2: Commit**

```bash
git add documents/seed/
git commit -m "feat(documents): declarative labor-law seed corpus list"
```

### Task 4.2: Идемпотентная команда seed_corpus

**Files:**
- Create: `documents/management/commands/seed_corpus.py`
- Test: `documents/tests/test_seed_corpus.py`

- [ ] **Step 1: Написать падающий тест**

`documents/tests/test_seed_corpus.py`:

```python
import pytest
from django.core.management import call_command

from documents.models import Document


@pytest.mark.django_db
def test_seed_corpus_is_idempotent():
    call_command("seed_corpus")
    first = Document.objects.count()
    assert Document.objects.filter(slug="tk-rf").exists()
    call_command("seed_corpus")  # повтор не плодит дубликаты и не падает
    assert Document.objects.count() == first


@pytest.mark.django_db
def test_seed_corpus_does_not_publish_anything():
    # сид заводит только метаданные Document; текст/редакции — через приём + куратора
    call_command("seed_corpus")
    doc = Document.objects.get(slug="tk-rf")
    assert not doc.redactions.exists()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_seed_corpus.py -v`
Expected: FAIL — `Unknown command: 'seed_corpus'`.

- [ ] **Step 3: Реализовать команду**

`documents/management/commands/seed_corpus.py`:

```python
from django.core.management.base import BaseCommand

from documents.models import Document
from documents.seed.labor_law import SEED_ACTS


class Command(BaseCommand):
    help = "Идемпотентно заводит метаданные актов стартового корпуса (без текста/редакций)."

    def handle(self, *args, **options):
        created = updated = 0
        for act in SEED_ACTS:
            defaults = {k: v for k, v in act.items() if k != "slug"}
            _, was_created = Document.objects.update_or_create(
                slug=act["slug"], defaults=defaults
            )
            created += was_created
            updated += not was_created
        self.stdout.write(
            self.style.SUCCESS(f"Сид-корпус: создано {created}, обновлено {updated}.")
        )
```

- [ ] **Step 4: Запустить**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_seed_corpus.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add documents/management/commands/seed_corpus.py documents/tests/test_seed_corpus.py
git commit -m "feat(documents): idempotent seed_corpus command (metadata only)"
```

---

## Фаза 5: Приёмка — характеризация реальных данных + runbook куратора

> Проверяем, что закалённый парсер реально вытягивает структуру ТК РФ из захваченной фикстуры, и фиксируем операционный сценарий куратора end-to-end.

### Task 5.1: Характеризационный тест на реальной фикстуре ТК РФ

**Files:**
- Create: `ingestion/tests/test_real_fixtures.py`
- Использует `ingestion/fixtures_raw/tk_rf_real.html` (Task 0.2)

- [ ] **Step 1: Написать тест на инвариантах ТК РФ**

> Утверждаем устойчивые свойства, не точные строки байт. Числовые пороги — из характеризации Task 0.2 (наблюдаемое число статей); поставить консервативную нижнюю границу.

```python
from pathlib import Path

import pytest

from ingestion.parsing import parse_document

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures_raw"


@pytest.mark.skipif(
    not (FIXTURES / "tk_rf_real.html").exists(),
    reason="реальная фикстура ТК РФ не захвачена (Task 0.2)",
)
def test_tk_rf_real_fixture_structure():
    content = (FIXTURES / "tk_rf_real.html").read_bytes()
    parsed = parse_document(content, "text/html")
    articles = [n for n in parsed.articles if n.kind == "article"]
    sections = [n for n in parsed.articles if n.kind == "section"]
    chapters = [n for n in parsed.articles if n.kind == "chapter"]
    # ТК РФ — крупный кодекс: десятки глав, сотни статей. Нижние границы консервативны.
    assert len(sections) >= 6        # уточнить по характеризации
    assert len(chapters) >= 10
    assert len(articles) >= 100
    # все статьи имеют валидный номер
    assert all(a.number for a in articles)
    # заголовок распознан как наименование кодекса
    assert "кодекс" in parsed.title.lower()
```

- [ ] **Step 2: Запустить**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_real_fixtures.py -v`
Expected: PASS (если фикстура есть). Если падает — это РЕАЛЬНЫЙ сигнал, что парсер не покрыл формат: завести характеризацию, починить регэкспы в Фазе 1, повторить (цикл закалки парсера — главная ценность шага 10).

- [ ] **Step 3: Commit**

```bash
git add ingestion/tests/test_real_fixtures.py
git commit -m "test(ingestion): characterize TK RF real fixture structure"
```

### Task 5.2: Runbook куратора и сквозная приёмка

**Files:**
- Create: `docs/superpowers/runbooks/2026-06-08-curator-acceptance.md`

- [ ] **Step 1: Написать runbook** со следующим сценарием (это операционный документ, не код):

```markdown
# Runbook куратора: приёмка сид-корпуса

## Развёртывание
1. `docker compose up --wait` — web + postgres + qcluster подняты и healthy.
2. `docker compose exec web python manage.py migrate`
3. `docker compose exec web python manage.py seed_corpus` — завести метаданные актов.
4. Создать суперпользователя/куратора, войти в `/admin/`.

## Приём ТК РФ
5. В admin у Document «ТК РФ» проверить source_url; либо запустить
   `python manage.py ingest_url tk-rf` (приём по slug → черновик), либо
   при сбое парсера — форма ручного импорта в admin (вставить текст/файл).
6. Открыть созданный черновик редакции: проверить оглавление (разделы→главы→статьи),
   число статей, заголовок, предложенные связи (suggested).

## Ревью и публикация
7. При кривом разборе — admin-действие «переразобрать из RawSource» (reparse),
   либо поправить статьи руками. Подсказки реквизитов — в логе IngestionJob.
8. Сверить диф «черновик ↔ текущая» (если редакция не первая).
9. Опубликовать редакцию (становится is_current, обновляется поисковый индекс).
10. Подтвердить корректные suggested-связи (confirmed), отклонить ложные.

## Приёмочный чек-лист (end-to-end)
- [ ] `/search/?q=увольнение` находит ТК РФ, сниппет с подсветкой, deep-link в статью.
- [ ] Страница акта: реквизиты, оглавление с якорями, текст, панели связей.
- [ ] Внутрикорпусная ссылка кликабельна и ведёт к нужной статье.
- [ ] Читателю видны только confirmed-связи; куратору — и suggested.
- [ ] Утратившая силу редакция доступна в истории, текущая помечена.

## Включение авто-приёма
11. После успешной приёмки ТК РФ: выставить auto_ingest=True у акта (в SEED_ACTS и в БД),
    `python manage.py ensure_sweep_schedule` — ежедневный sweep создаёт черновики на изменения.
12. Повторить приём (шаги 5–10) для следующего акта корпуса — по одному.
```

- [ ] **Step 2: Выполнить runbook на ТК РФ** вживую (через docker compose), отметить галочки приёмочного чек-листа. Любой сбой парсера → вернуться в Фазу 1/2/3, добавить тест на синтетике, починить, повторить.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/runbooks/2026-06-08-curator-acceptance.md
git commit -m "docs: curator acceptance runbook for seed corpus"
```

### Task 5.3: Финальная проверка всего репозитория

- [ ] **Step 1: Полный прогон** (см. [[lawiot-lint-scope]] — без путей, весь репозиторий):

```
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pytest
```
Expected: ruff чисто; все тесты зелёные (109 базовых + новые из этого плана).

- [ ] **Step 2: Контейнеры** — `docker compose up --wait` поднимается healthy; `seed_corpus` + приём ТК РФ отрабатывают в контейнере.

- [ ] **Step 3:** Обновить память (`lawiot-overview`, `lawiot-lint-scope` с новым числом тестов) и закрыть шаг 10 как выполненный.

---

## Self-Review (сверка с §16 спеки)

- **§16.10 «Наполнение реального сид-корпуса + приёмочная проверка»** → Фазы 4–5. ✅
- **§6 PDF (`pdfminer.six`)** — был отложен → Фаза 3. ✅
- **Иерархия раздел→глава→статья** (модель умела, парсер нет) → Фаза 1. ✅
- **#1282 эвристика заголовка на реальном HTML** → Фаза 2.1 + реальная фикстура 5.1. ✅
- **§12 тесты на сохранённых фикстурах RawSource** → Фаза 0 захват + Фаза 5.1 характеризация. ✅
- **§7 курирование (reparse, диф, публикация, ручной импорт)** — уже реализовано (План 3d), переиспользуется в runbook 5.2; новый код не нужен. ✅
- **§13 «никогда не публиковать автоматически»** — сид заводит только метаданные, приём создаёт черновик, публикует куратор (тест 4.2 `test_seed_corpus_does_not_publish_anything`). ✅

**Зависимости фаз:** Фаза 0 → (5.1, 3.2 нужны фикстуры). Фазы 1–2 независимы от 0 (синтетика). Фаза 4 независима от парсера. Фаза 5 требует 0+1+4. Безопасный порядок: 0 → 1 → 2 → 3 → 4 → 5.

**Риск:** реальный HTML `pravo.gov.ru` может содержать неожиданные варианты заголовков («Раздел первый» прописью, «Статья 3511» без точки, вложенные `<табличные>` блоки). Это вскроется в Task 5.1 и лечится добавлением регэкспов/тестов в Фазу 1–2 — цикл закалки и есть суть шага 10.
