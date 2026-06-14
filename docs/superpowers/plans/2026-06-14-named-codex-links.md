# Распознавание ссылок на кодексы по имени — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Авто-экстрактор связей должен резолвить ссылки на кодексы, цитируемые по имени («Трудовой кодекс»), а не только по номеру `NNN-ФЗ` — но только когда кодекс уже есть в корпусе.

**Architecture:** Чистая функция `find_named_citations(text)` находит упоминания кодексов по реестру стем-паттернов (склонения) и возвращает канонические имена. `extract_links_for_redaction` после цикла по `NNN-ФЗ` резолвит каждое имя в документ корпуса по `Document.title` и создаёт `auto+suggested`-связь; если кодекса в корпусе нет — связь не создаётся. Без изменений схемы БД.

**Tech Stack:** Python `re` (Unicode str-режим: `\w`/`\s`/`\b` работают с кириллицей и `\xa0`), Django ORM, pytest.

**Спека:** `docs/superpowers/specs/2026-06-14-named-codex-links-design.md`

---

## Файловая структура

- **Modify:** `ingestion/links.py` — добавить `CODEX_PATTERNS`, `_CODEX_TITLE_FILTERS`, `NamedCitation`, `find_named_citations`; расширить `extract_links_for_redaction`.
- **Modify (test):** `ingestion/tests/test_links.py` — юнит-тесты чистой функции + django_db-тесты резолвинга.
- **Modify (test):** `ingestion/tests/test_real_fixtures.py` — сквозной тест на живой фикстуре 426-ФЗ → ТК РФ.

Все изменения локальны для модуля `links.py` — он остаётся маленьким и сфокусированным.

---

### Task 1: Чистая функция `find_named_citations` + реестр кодексов

**Files:**
- Modify: `ingestion/links.py`
- Test: `ingestion/tests/test_links.py`

- [ ] **Step 1: Написать падающие юнит-тесты**

Добавить в конец `ingestion/tests/test_links.py`. Сначала обновить импорт в начале файла:

```python
from ingestion.links import (
    extract_links_for_redaction,
    find_citations,
    find_named_citations,
)
```

Тесты (в конец файла):

```python
def test_finds_codex_by_name_all_cases():
    text = "регулируется Трудовым кодексом и Трудового кодекса, см. Трудовой кодекс."
    names = {c.name for c in find_named_citations(text)}
    assert names == {"Трудовой кодекс"}


def test_named_citation_is_canonical_not_declined():
    # хранится каноническое имя, а не пойманная падежная форма
    (cite,) = find_named_citations("в соответствии с Трудовым кодексом")
    assert cite.name == "Трудовой кодекс"


def test_named_citation_ignores_non_codex_phrases():
    text = "Заключается трудовой договор, ведётся трудовая книжка."
    assert find_named_citations(text) == []


def test_named_citation_captures_context():
    (cite,) = find_named_citations("Изменения внесены Трудовым кодексом о труде.")
    assert "кодекс" in cite.context.lower()
    assert "труде" in cite.context


def test_finds_multiple_distinct_codices():
    text = "применяются Трудовой кодекс и Гражданский кодекс совместно"
    names = {c.name for c in find_named_citations(text)}
    assert names == {"Трудовой кодекс", "Гражданский кодекс"}


def test_recognizes_koap_noun_first_form():
    text = "ответственность по Кодексу Российской Федерации об административных правонарушениях"
    names = {c.name for c in find_named_citations(text)}
    assert "Кодекс об административных правонарушениях" in names
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -k named -v`
Expected: FAIL — `ImportError: cannot import name 'find_named_citations'`.

- [ ] **Step 3: Реализовать реестр и чистую функцию**

В `ingestion/links.py` после `CONTEXT_WINDOW = 60` (строка 8) добавить:

```python
# Реестр кодексов РФ: (regex по склонениям имени, каноническое имя, фильтр по Document.title).
# Стем-паттерны терпимы к падежам: «Трудов-ой/-ого/-ым кодекс-∅/-а/-ом». Резолв
# «только-в-корпусе» (см. extract_links_for_redaction) делает лишние записи безвредными —
# резолвятся лишь те кодексы, что реально в корпусе. КоАП — особый («кодекс» спереди).
CODEX_PATTERNS = [
    (re.compile(r"\bтрудов\w+\s+кодекс\w*", re.I), "Трудовой кодекс",
     {"title__istartswith": "Трудовой кодекс"}),
    (re.compile(r"\bгражданск\w+\s+кодекс\w*", re.I), "Гражданский кодекс",
     {"title__istartswith": "Гражданский кодекс"}),
    (re.compile(r"\bналогов\w+\s+кодекс\w*", re.I), "Налоговый кодекс",
     {"title__istartswith": "Налоговый кодекс"}),
    (re.compile(r"\bуголовн\w+\s+кодекс\w*", re.I), "Уголовный кодекс",
     {"title__istartswith": "Уголовный кодекс"}),
    (re.compile(r"\bземельн\w+\s+кодекс\w*", re.I), "Земельный кодекс",
     {"title__istartswith": "Земельный кодекс"}),
    (re.compile(r"\bжилищн\w+\s+кодекс\w*", re.I), "Жилищный кодекс",
     {"title__istartswith": "Жилищный кодекс"}),
    (re.compile(r"\bсемейн\w+\s+кодекс\w*", re.I), "Семейный кодекс",
     {"title__istartswith": "Семейный кодекс"}),
    (re.compile(r"\bбюджетн\w+\s+кодекс\w*", re.I), "Бюджетный кодекс",
     {"title__istartswith": "Бюджетный кодекс"}),
    (re.compile(
        r"\bкодекс\w*\s+(?:российской федерации\s+)?об\s+административных\s+правонарушениях",
        re.I,
    ), "Кодекс об административных правонарушениях",
     {"title__icontains": "об административных правонарушениях"}),
]

# Каноническое имя → фильтр резолвинга по Document.title (единый источник — CODEX_PATTERNS).
_CODEX_TITLE_FILTERS = {name: title_filter for _, name, title_filter in CODEX_PATTERNS}


@dataclass(frozen=True)
class NamedCitation:
    name: str  # каноническое имя кодекса, напр. «Трудовой кодекс»
    context: str  # очищенный фрагмент текста вокруг первого вхождения


def find_named_citations(text):
    """Найти упоминания кодексов по имени (во всех падежах). Чистая функция (без БД/сети).
    По одной NamedCitation на уникальное каноническое имя — с контекстом первого вхождения."""
    text = text or ""
    found: list[NamedCitation] = []
    for regex, name, _ in CODEX_PATTERNS:
        match = regex.search(text)
        if match is None:
            continue
        start = max(0, match.start() - CONTEXT_WINDOW)
        end = min(len(text), match.end() + CONTEXT_WINDOW)
        snippet = " ".join(text[start:end].split())
        found.append(NamedCitation(name=name, context=snippet))
    return found
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -k named -v`
Expected: PASS (6 тестов).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/links.py ingestion/tests/test_links.py
git commit -m "feat(links): чистая find_named_citations + реестр кодексов РФ (§9)"
```

---

### Task 2: Резолвинг именных цитат в `extract_links_for_redaction`

**Files:**
- Modify: `ingestion/links.py:extract_links_for_redaction`
- Test: `ingestion/tests/test_links.py`

- [ ] **Step 1: Написать падающие django_db-тесты**

Добавить в конец `ingestion/tests/test_links.py`:

```python
@pytest.mark.django_db
def test_named_codex_resolves_when_in_corpus():
    # tk-rf в корпусе (title = «Трудовой кодекс …»), источник цитирует его по имени
    tk = make_document(slug="tk", title="Трудовой кодекс Российской Федерации",
                       official_number="197-ФЗ")
    src = make_document(slug="src-426", title="О специальной оценке условий труда",
                        official_number="426-ФЗ")
    red = make_redaction(src, full_text="Проводится в соответствии с Трудовым кодексом.")
    n = extract_links_for_redaction(red)
    assert n == 1
    link = Link.objects.get(from_document=src)
    assert link.to_document == tk
    assert link.link_type == Link.LinkType.REFERENCES
    assert link.origin == Link.Origin.AUTO
    assert link.status == Link.Status.SUGGESTED
    assert "кодекс" in link.context.lower()


@pytest.mark.django_db
def test_named_codex_not_created_when_absent_from_corpus():
    # кодекса нет в корпусе → связь НЕ создаётся (только-в-корпусе)
    src = make_document(slug="src-only", title="О специальной оценке условий труда",
                        official_number="426-ФЗ")
    red = make_redaction(src, full_text="Регулируется Гражданским кодексом.")
    assert extract_links_for_redaction(red) == 0
    assert Link.objects.filter(from_document=src).count() == 0


@pytest.mark.django_db
def test_named_and_numeric_citation_dedup_to_one_link():
    # акт цитирует и «197-ФЗ», и «Трудовым кодексом» — оба → tk-rf, но ровно одна связь
    tk = make_document(slug="tk2", title="Трудовой кодекс Российской Федерации",
                       official_number="197-ФЗ")
    src = make_document(slug="src-dup", title="О специальной оценке условий труда",
                        official_number="426-ФЗ")
    red = make_redaction(src, full_text="См. 197-ФЗ и Трудовой кодекс одновременно.")
    extract_links_for_redaction(red)
    links = Link.objects.filter(from_document=src, to_document=tk)
    assert links.count() == 1


@pytest.mark.django_db
def test_named_codex_skips_self_reference():
    # сам ТК РФ упоминает «Трудового кодекса» в преамбуле → не ссылаемся на себя
    tk = make_document(slug="tk-self", title="Трудовой кодекс Российской Федерации",
                       official_number="197-ФЗ")
    red = make_redaction(tk, full_text="Настоящий Трудовой кодекс регулирует отношения.")
    assert extract_links_for_redaction(red) == 0
    assert Link.objects.filter(from_document=tk).count() == 0
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -k "named_codex" -v`
Expected: FAIL — связи не создаются (резолвинг ещё не подключён), напр. `assert n == 1` падает с `0 == 1`.

- [ ] **Step 3: Подключить резолвинг именных цитат**

В `ingestion/links.py`, в функции `extract_links_for_redaction`, перед `return created` (текущая строка 94) вставить цикл:

```python
    # Именные цитаты кодексов: резолвим по Document.title, только если кодекс в корпусе.
    for citation in find_named_citations(text):
        target = (
            Document.objects.filter(**_CODEX_TITLE_FILTERS[citation.name])
            .exclude(pk=document.pk)  # не ссылаемся на самих себя
            .first()
        )
        if target is None:
            continue  # кодекса нет в корпусе → связь не создаём
        already = Link.objects.filter(
            from_document=document,
            to_document=target,
            link_type=Link.LinkType.REFERENCES,
        ).exists()
        if already:
            continue  # дедуп: номерная цитата уже создала связь к этой цели
        Link.objects.create(
            from_document=document,
            to_document=target,
            link_type=Link.LinkType.REFERENCES,
            origin=Link.Origin.AUTO,
            status=Link.Status.SUGGESTED,
            context=citation.context,
        )
        created += 1
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -v`
Expected: PASS (все тесты файла — новые именные + старые номерные, идемпотентность/confirmed не сломаны).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/links.py ingestion/tests/test_links.py
git commit -m "feat(links): резолв именных ссылок на кодексы (только-в-корпусе, §9)"
```

---

### Task 3: Сквозной тест на живой фикстуре 426-ФЗ → ТК РФ

**Files:**
- Test: `ingestion/tests/test_real_fixtures.py`

- [ ] **Step 1: Написать тест (проверяет интеграцию в конвейер ingest_target)**

Добавить в конец `ingestion/tests/test_real_fixtures.py`:

```python
@pytest.mark.django_db
@pytest.mark.skipif(
    not (FIXTURES / "sout_426fz_real.html").exists(),
    reason="реальная фикстура 426-ФЗ не захвачена",
)
def test_real_sout426_links_to_tk_rf_by_name():
    """Закрывает пробой §9: 426-ФЗ упоминает «Трудовой кодекс» по имени (а не «197-ФЗ»).
    Когда tk-rf уже в корпусе, сквозной ingest_target должен создать резолвленную
    suggested-связь 426-ФЗ → ТК РФ через find_named_citations."""
    from documents.models import Link

    tk = make_document(slug="tk-rf", title="Трудовой кодекс Российской Федерации",
                       official_number="197-ФЗ")
    content = (FIXTURES / "sout_426fz_real.html").read_bytes()
    doc = make_document(slug="sout-426-fz", doc_type="federal_law",
                        title="О специальной оценке условий труда",
                        official_number="426-ФЗ", auto_publish=False)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)

    ingest_target(target, client=_client_returning(content))

    link = Link.objects.get(from_document=doc, to_document=tk)
    assert link.link_type == Link.LinkType.REFERENCES
    assert link.origin == Link.Origin.AUTO
    assert link.status == Link.Status.SUGGESTED
    assert "кодекс" in link.context.lower()
```

- [ ] **Step 2: Запустить тест**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_real_fixtures.py -k sout426_links -v`
Expected: PASS (если фикстура `sout_426fz_real.html` присутствует; иначе тест скипается — это нормально в окружениях без фикстуры).

- [ ] **Step 3: Прогнать весь набор связей и приёмки**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py ingestion/tests/test_real_fixtures.py -v`
Expected: PASS (все).
Примечание: django_db-тесты требуют Postgres. На хосте — контейнер `lawiot-db` (порт 5433); если Docker недоступен — фолбэк через WSL Ubuntu Postgres (см. memory `wsl-postgres-test-fallback`). Запуск с `--create-db`, если схема тестовой БД устарела.

- [ ] **Step 4: Ruff + полный прогон (верификация перед PR)**

Run: `.venv\Scripts\python.exe -m ruff check .`
Expected: чисто.

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: все тесты зелёные (база + новые).

- [ ] **Step 5: Коммит**

```bash
git add ingestion/tests/test_real_fixtures.py
git commit -m "test(links): сквозная связь 426-ФЗ → ТК РФ по имени на живой фикстуре (§9)"
```

---

## Замечания по верификации

- **Кириллица в regex:** `\w`, `\b`, `\s` в Python работают с кириллицей и `\xa0` (неразрывный пробел ИПС) в str-режиме по умолчанию — отдельные флаги не нужны. `re.I` нужен, т.к. в тексте встречаются и «Трудовым», и потенциально иные регистры.
- **Дедуп с номерами:** проверка `already` (from+to+type) видит связь, созданную циклом `NNN-ФЗ` в том же вызове (Django ORM `.exists()` отражает сохранённые в транзакции объекты).
- **Идемпотентность/confirmed:** именные связи — `auto+suggested`, попадают в существующий сброс в начале функции; `confirmed`-связи куратора сохраняются (покрыто старыми тестами `test_reextraction_*`).

## Self-review (выполнено при написании плана)

- **Покрытие спеки:** реестр+склонения (Task 1), резолв только-в-корпусе (Task 2: resolves/absent), дедуп с номерами (Task 2), self-link (Task 2), живая фикстура 426→ТК (Task 3), КоАП-форма (Task 1). Все разделы спеки покрыты.
- **Плейсхолдеры:** нет — весь код приведён дословно.
- **Согласованность типов:** `NamedCitation(name, context)`, `find_named_citations`, `_CODEX_TITLE_FILTERS`, `CODEX_PATTERNS` используются одинаково в коде и тестах.
