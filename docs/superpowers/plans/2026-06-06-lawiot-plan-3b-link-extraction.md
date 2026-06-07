# Lawiot MVP — План 3b: Извлечение связей (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Автоматически находить цитаты на другие НПА в тексте редакции и создавать **предложенные** связи (`Link`, `origin=auto`, `status=suggested`): внутрикорпусные — с резолвом цели по номеру, внешние — как `raw_citation`. Подключить извлечение к конвейеру приёма (План 3a) и команде переизвлечения; показать куратору предложенные связи в просмотрщике (закрыть §9).

**Architecture:** Извлечение живёт в приложении `ingestion` (спека §11). Чистый поиск цитат (`find_citations`, без БД) отделён от сервиса создания связей (`extract_links_for_redaction`, БД) — оба в `ingestion/links.py`. Извлечение **консервативно**: якорь цитаты — номер акта `NNN-ФЗ`/`N-ФКЗ`; все авто-связи имеют тип `references` и статус `suggested` (куратор подтверждает через уже существующее admin-действие). Идемпотентно: при переизвлечении прежние `auto+suggested` связи документа пересоздаются, а подтверждённые куратором — не трогаются и не дублируются.

**Tech Stack:** Python 3.13 (`.venv`), Django 5.2, PostgreSQL 16 (Docker, host-порт 5433), pytest + pytest-django. Новых зависимостей нет (только `re` из стандартной библиотеки).

**Спецификация:** [docs/superpowers/specs/2026-06-05-lawiot-design.md](../specs/2026-06-05-lawiot-design.md) — §5 (модель Link), §6 шаг 6 (link extraction), §9 (видимость связей: читателю `confirmed`, куратору ещё и `suggested`), §15 (риск ложных/пропущенных связей → всё как `suggested`).

**Место в дорожной карте:** **План 3 из 3, под-план «b» — извлечение связей.** Реализует §16 шаг 7 и §6 шаг 6, закрывает §9 (видимость suggested куратору). Строится поверх Плана 3a (конвейер приёма). Ветка: `feature/lawiot-plan-3b-link-extraction` (создана от ветки 3a; при мёрдже PR #3 — `git rebase` на `main`).

**Уже есть (Планы 1 и 3a), не переделываем:**
- Модель `Link` (from/to document/article, raw_citation, link_type, origin, status, context) — План 1.
- Просмотрщик с панелями связей («Изменяющие/изменённые», «Ссылается на», «На него ссылаются»), читателю — только `confirmed` — План 1.
- `LinkAdmin` с действием «Подтвердить выбранные связи» (`confirm_selected`) — План 1.
- Конвейер приёма `ingest_target` / `import_manual` и `create_draft_from_parsed` — План 3a.

**Сознательно отложено:**
- Распознавание направления **изменяет/изменён** (`amends`/`amended_by`) из текста — юридически критично, оставляем куратору (ручное заведение в admin уже работает). Авто-связи — только `references`.
- **Цитаты по названию** («Трудового кодекса», «ТК РФ») без номера — фаззи-резолв, позже.
- **Точечные (постатейные) связи** (`from_article`/`to_article`) — 3b создаёт связи на уровне документа (`from_article=None`); постатейная точность — позже.
- Расписание (3c), шлифовка курирования и diff (3d).

---

## Окружение исполнения

- Запуск Python — **только** через `.venv\Scripts\python.exe`.
- **Docker поднят**, `lawiot-db` на порту **5433**; тесты pytest-django создают `test_lawiot` на нём.
- ruff: line-length 100, target py313.

---

## Структура файлов (План 3b)

```
ingestion/links.py                                # NEW — find_citations (чистая) + extract_links_for_redaction (БД)
ingestion/services.py                             # MODIFY — вызвать извлечение после создания черновика
ingestion/management/commands/extract_links.py    # NEW — переизвлечение для текущих редакций
ingestion/tests/test_links.py                     # NEW — тесты поиска цитат и сервиса связей
ingestion/tests/test_services.py                  # MODIFY — конвейер создаёт предложенные связи
ingestion/tests/test_commands.py                  # MODIFY — тест команды extract_links
documents/views.py                                # MODIFY — куратору (is_staff) показывать и suggested
templates/documents/document_detail.html          # MODIFY — пометка «(предложена)» у предложенных связей
documents/tests/test_views.py                     # MODIFY — куратор видит suggested, читатель — нет
```

**Ответственность:**
- `ingestion/links.py` — вся логика связей: чистый поиск цитат + создание `Link`. «Меняется вместе — лежит вместе».
- `ingestion/services.py` — только точка вызова извлечения в конвейере (некритичный шаг: сбой извлечения не теряет черновик).
- `documents/views.py` + шаблон — видимость предложенных связей куратору (§9).

---

## Task 1: Поиск цитат (чистая функция)

**Files:**
- Create: `ingestion/links.py` (только `find_citations` + `Citation`)
- Test: `ingestion/tests/test_links.py`

- [ ] **Step 1: Написать падающие тесты**

`ingestion/tests/test_links.py`:
```python
from ingestion.links import find_citations


def test_finds_fz_and_fkz_numbers():
    text = "В соответствии с Федеральным законом от 28.12.2013 № 400-ФЗ и 1-ФКЗ."
    numbers = {c.number for c in find_citations(text)}
    assert numbers == {"400-ФЗ", "1-ФКЗ"}


def test_dedups_repeated_numbers():
    text = "См. 197-ФЗ. Также 197-ФЗ применяется здесь."
    cites = find_citations(text)
    assert [c.number for c in cites] == ["197-ФЗ"]


def test_ignores_plain_numbers_and_dates():
    text = "Пункт 5 от 28.12.2013 года, страница 400."
    assert find_citations(text) == []


def test_captures_context_around_citation():
    text = "Изменения внесены Федеральным законом № 125-ФЗ о страховании."
    (cite,) = find_citations(text)
    assert cite.number == "125-ФЗ"
    assert "125-ФЗ" in cite.context
    assert "страховании" in cite.context
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -v`
Expected: FAIL — модуля `ingestion.links` нет.

- [ ] **Step 3: Реализовать поиск цитат**

`ingestion/links.py`:
```python
import re
from dataclasses import dataclass

# Номер НПА вида «197-ФЗ», «400-ФЗ», «1-ФКЗ» — самый надёжный якорь цитаты.
CITATION_RE = re.compile(r"\b(\d{1,4}-(?:ФКЗ|ФЗ))\b")
CONTEXT_WINDOW = 60


@dataclass(frozen=True)
class Citation:
    number: str   # «197-ФЗ»
    context: str  # очищенный фрагмент текста вокруг цитаты


def find_citations(text):
    """Найти уникальные цитаты-номера НПА. Чистая функция (без БД/сети).
    По одной Citation на уникальный номер — с контекстом первого вхождения."""
    text = text or ""
    seen: dict[str, Citation] = {}
    for match in CITATION_RE.finditer(text):
        number = match.group(1)
        if number in seen:
            continue
        start = max(0, match.start() - CONTEXT_WINDOW)
        end = min(len(text), match.end() + CONTEXT_WINDOW)
        snippet = " ".join(text[start:end].split())
        seen[number] = Citation(number=number, context=snippet)
    return list(seen.values())
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -v`
Expected: все 4 теста passed.

- [ ] **Step 5: Commit**

```bash
git add ingestion/links.py ingestion/tests/test_links.py
git commit -m "feat(ingestion): pure citation finder (NNN-ФЗ / N-ФКЗ tokens)"
```

---

## Task 2: Сервис создания предложенных связей

**Files:**
- Modify: `ingestion/links.py` (добавить `extract_links_for_redaction`)
- Test: `ingestion/tests/test_links.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `ingestion/tests/test_links.py`:
```python
import pytest

from documents.models import Link
from documents.tests.factories import make_article, make_document, make_redaction
from ingestion.links import extract_links_for_redaction


@pytest.mark.django_db
def test_creates_suggested_in_corpus_link():
    src = make_document(slug="src", official_number="197-ФЗ")
    target = make_document(slug="tgt", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Регулируется Федеральным законом № 125-ФЗ.")
    n = extract_links_for_redaction(red)
    assert n == 1
    link = Link.objects.get(from_document=src)
    assert link.to_document == target
    assert link.link_type == Link.LinkType.REFERENCES
    assert link.origin == Link.Origin.AUTO
    assert link.status == Link.Status.SUGGESTED
    assert "125-ФЗ" in link.context


@pytest.mark.django_db
def test_external_citation_becomes_raw():
    src = make_document(slug="src2", official_number="197-ФЗ")
    red = make_redaction(src, full_text="Упоминается 999-ФЗ, которого нет в корпусе.")
    extract_links_for_redaction(red)
    link = Link.objects.get(from_document=src)
    assert link.to_document is None
    assert "999-ФЗ" in link.raw_citation


@pytest.mark.django_db
def test_skips_self_citation():
    src = make_document(slug="self", official_number="197-ФЗ")
    red = make_redaction(src, full_text="Настоящий 197-ФЗ регулирует отношения.")
    assert extract_links_for_redaction(red) == 0
    assert Link.objects.filter(from_document=src).count() == 0


@pytest.mark.django_db
def test_scans_article_text_too():
    src = make_document(slug="arts", official_number="197-ФЗ")
    target = make_document(slug="tgt2", official_number="125-ФЗ")
    red = make_redaction(src, full_text="")
    make_article(red, number="1", title="Сфера", text="См. также 125-ФЗ.")
    extract_links_for_redaction(red)
    assert Link.objects.filter(from_document=src, to_document=target).exists()


@pytest.mark.django_db
def test_reextraction_is_idempotent():
    src = make_document(slug="idem", official_number="197-ФЗ")
    make_document(slug="t3", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Ссылка на 125-ФЗ.")
    extract_links_for_redaction(red)
    extract_links_for_redaction(red)
    assert Link.objects.filter(from_document=src).count() == 1


@pytest.mark.django_db
def test_reextraction_preserves_and_does_not_duplicate_confirmed():
    src = make_document(slug="conf", official_number="197-ФЗ")
    target = make_document(slug="t4", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Ссылка на 125-ФЗ.")
    # куратор уже подтвердил связь
    Link.objects.create(
        from_document=src, to_document=target,
        link_type=Link.LinkType.REFERENCES,
        origin=Link.Origin.AUTO, status=Link.Status.CONFIRMED,
    )
    extract_links_for_redaction(red)
    links = Link.objects.filter(from_document=src, to_document=target)
    assert links.count() == 1                       # дубль не создан
    assert links.first().status == Link.Status.CONFIRMED  # подтверждение сохранено
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -v`
Expected: FAIL — функции `extract_links_for_redaction` нет.

- [ ] **Step 3: Реализовать сервис**

Добавить в начало `ingestion/links.py` (к существующим импортам):
```python
from documents.models import Document, Link
```

Добавить в конец `ingestion/links.py`:
```python
def extract_links_for_redaction(redaction):
    """Извлечь цитаты из текста редакции и создать предложенные (suggested) авто-связи.
    Идемпотентно: прежние auto+suggested связи документа пересоздаются; подтверждённые
    куратором связи не трогаются и не дублируются. Возвращает число созданных связей."""
    document = redaction.document
    parts = [redaction.full_text or ""]
    parts.extend(article.text for article in redaction.articles.all())
    text = "\n".join(parts)

    citations = find_citations(text)

    # сбросить прежние авто-предложения этого документа (подтверждённые не трогаем)
    Link.objects.filter(
        from_document=document,
        origin=Link.Origin.AUTO,
        status=Link.Status.SUGGESTED,
    ).delete()

    created = 0
    for citation in citations:
        target = (
            Document.objects.filter(official_number=citation.number)
            .exclude(pk=document.pk)  # не ссылаемся на самих себя
            .first()
        )
        if target is not None:
            already = Link.objects.filter(
                from_document=document,
                to_document=target,
                link_type=Link.LinkType.REFERENCES,
            ).exists()
            if already:
                continue
            Link.objects.create(
                from_document=document,
                to_document=target,
                link_type=Link.LinkType.REFERENCES,
                origin=Link.Origin.AUTO,
                status=Link.Status.SUGGESTED,
                context=citation.context,
            )
        else:
            if citation.number == document.official_number:
                continue  # самоцитата без внешней цели
            already = Link.objects.filter(
                from_document=document,
                raw_citation__icontains=citation.number,
            ).exists()
            if already:
                continue
            Link.objects.create(
                from_document=document,
                raw_citation=citation.context,
                link_type=Link.LinkType.REFERENCES,
                origin=Link.Origin.AUTO,
                status=Link.Status.SUGGESTED,
                context=citation.context,
            )
        created += 1
    return created
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_links.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add ingestion/links.py ingestion/tests/test_links.py
git commit -m "feat(ingestion): extract suggested Links from redaction text (resolve corpus targets, idempotent)"
```

---

## Task 3: Подключить извлечение к конвейеру приёма

**Files:**
- Modify: `ingestion/services.py` (вызов в `ingest_target` — некритично; в `import_manual`)
- Test: `ingestion/tests/test_services.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `ingestion/tests/test_services.py`:
```python
@pytest.mark.django_db
def test_ingest_target_extracts_suggested_links():
    from documents.models import Link

    src = make_document(slug="ing-src", official_number="197-ФЗ")
    make_document(slug="ing-tgt", official_number="125-ФЗ")
    html = "<p>Регулируется Федеральным законом № 125-ФЗ.</p>".encode("utf-8")
    target = IngestionTarget(document=src, url="https://e.test/x", target_key="ing-src")
    job = ingest_target(target, client=_client_returning(html))
    assert job.status == IngestionJob.Status.SUCCESS
    assert Link.objects.filter(
        from_document=src, status=Link.Status.SUGGESTED, origin=Link.Origin.AUTO
    ).exists()


@pytest.mark.django_db
def test_import_manual_extracts_suggested_links():
    from documents.models import Link

    src = make_document(slug="man-src", official_number="197-ФЗ")
    make_document(slug="man-tgt", official_number="125-ФЗ")
    content = "Статья 1. Сфера\nПрименяется вместе с 125-ФЗ.".encode("utf-8")
    import_manual(src, content=content, content_type="text/plain")
    assert Link.objects.filter(from_document=src, status=Link.Status.SUGGESTED).exists()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -k "extracts_suggested" -v`
Expected: FAIL — конвейер пока не извлекает связи.

- [ ] **Step 3: Подключить извлечение**

В `ingestion/services.py` добавить импорт (рядом с другими импортами `ingestion`):
```python
from ingestion.links import extract_links_for_redaction
```

В `ingest_target`, сразу после строк
```python
        job.status = IngestionJob.Status.SUCCESS
        log_lines.append(f"Создан черновик редакции #{redaction.pk}.")
```
добавить (извлечение связей — некритичный шаг, не должен ронять успешный приём):
```python
        try:
            n_links = extract_links_for_redaction(redaction)
            log_lines.append(f"Предложено связей: {n_links}.")
        except Exception as link_exc:  # noqa: BLE001 — извлечение связей вторично
            log_lines.append(f"Извлечение связей не удалось: {link_exc}")
```

В `import_manual` заменить тело на:
```python
def import_manual(document, *, content, content_type="text/plain", source_url="", redaction_date=None):
    """Запасной путь: куратор подаёт байты/текст напрямую → черновик редакции + предложенные связи."""
    raw = store_raw_source(f"manual:{document.slug}", content, content_type, source_url)
    parsed = parse_document(content, content_type)
    redaction = create_draft_from_parsed(
        document, parsed, raw_source=raw, redaction_date=redaction_date
    )
    extract_links_for_redaction(redaction)
    return redaction
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_services.py -v`
Expected: все тесты passed (старые + два новых).

- [ ] **Step 5: Commit**

```bash
git add ingestion/services.py ingestion/tests/test_services.py
git commit -m "feat(ingestion): extract suggested links during ingest + manual import"
```

---

## Task 4: Команда переизвлечения связей

**Files:**
- Create: `ingestion/management/commands/extract_links.py`
- Test: `ingestion/tests/test_commands.py` (дополнить)

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `ingestion/tests/test_commands.py`:
```python
@pytest.mark.django_db
def test_extract_links_command_processes_current_redactions():
    from documents.models import Link
    from documents.tests.factories import make_redaction

    src = make_document(slug="cmd-src", official_number="197-ФЗ")
    make_document(slug="cmd-tgt", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Связано с 125-ФЗ.")
    red.publish()  # становится текущей
    call_command("extract_links")
    assert Link.objects.filter(from_document=src, status=Link.Status.SUGGESTED).exists()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_commands.py -k extract_links -v`
Expected: FAIL — команды `extract_links` нет.

- [ ] **Step 3: Реализовать команду**

`ingestion/management/commands/extract_links.py`:
```python
from django.core.management.base import BaseCommand

from documents.models import Redaction
from ingestion.links import extract_links_for_redaction


class Command(BaseCommand):
    help = "Переизвлечь предложенные (auto) связи для текущих опубликованных редакций."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="", help="ограничить документом с этим slug")

    def handle(self, *args, **options):
        redactions = Redaction.objects.filter(is_current=True).select_related("document")
        if options["slug"]:
            redactions = redactions.filter(document__slug=options["slug"])
        total_links = 0
        total_red = 0
        for redaction in redactions:
            total_links += extract_links_for_redaction(redaction)
            total_red += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Обработано редакций: {total_red}; предложено связей: {total_links}."
            )
        )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest ingestion/tests/test_commands.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add ingestion/management/commands/extract_links.py ingestion/tests/test_commands.py
git commit -m "feat(ingestion): extract_links management command (re-resolve current redactions)"
```

---

## Task 5: Видимость предложенных связей куратору (§9)

**Files:**
- Modify: `documents/views.py` (`document_detail` — куратору добавить `suggested`)
- Modify: `templates/documents/document_detail.html` (пометка «(предложена)»)
- Test: `documents/tests/test_views.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `documents/tests/test_views.py`:
```python
@pytest.fixture
def curator_client(client, django_user_model):
    user = django_user_model.objects.create_user(
        "curator", password="pass12345", is_staff=True
    )
    client.force_login(user)
    return user, client


@pytest.mark.django_db
def test_curator_sees_suggested_links(curator_client):
    _user, cclient = curator_client
    doc = make_document(slug="csee", official_number="197-ФЗ")
    make_redaction(doc, redaction_date=date(2024, 1, 1)).publish()
    target = make_document(slug="csee-t", official_number="125-ФЗ")
    make_link(
        from_document=doc, to_document=target,
        link_type=Link.LinkType.REFERENCES, status=Link.Status.SUGGESTED,
    )
    response = cclient.get(reverse("document_detail", args=["csee"]))
    content = response.content.decode()
    assert "125-ФЗ" in content
    assert "предложена" in content  # пометка статуса для куратора


@pytest.mark.django_db
def test_reader_does_not_see_suggested_links(auth_client):
    doc = make_document(slug="rsee", official_number="197-ФЗ")
    make_redaction(doc, redaction_date=date(2024, 1, 1)).publish()
    target = make_document(slug="rsee-t", official_number="125-ФЗ")
    make_link(
        from_document=doc, to_document=target,
        link_type=Link.LinkType.REFERENCES, status=Link.Status.SUGGESTED,
    )
    response = auth_client.get(reverse("document_detail", args=["rsee"]))
    content = response.content.decode()
    assert "125-ФЗ" not in content       # предложенная связь скрыта от читателя
    assert "предложена" not in content
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_views.py -k "suggested" -v`
Expected: FAIL — куратор пока не видит suggested (нет пометки «предложена»).

- [ ] **Step 3: Реализовать видимость для куратора**

В `documents/views.py`, в `document_detail`, заменить блок получения связей
```python
    outgoing = document.outgoing_links.filter(
        status=Link.Status.CONFIRMED
    ).select_related("to_document")
    incoming = document.incoming_links.filter(
        status=Link.Status.CONFIRMED
    ).select_related("from_document")
```
на
```python
    visible_statuses = [Link.Status.CONFIRMED]
    if request.user.is_staff:
        visible_statuses.append(Link.Status.SUGGESTED)
    outgoing = document.outgoing_links.filter(
        status__in=visible_statuses
    ).select_related("to_document")
    incoming = document.incoming_links.filter(
        status__in=visible_statuses
    ).select_related("from_document")
```

В том же `render(...)` добавить в контекст флаг куратора:
```python
            "incoming": incoming,
            "is_curator": request.user.is_staff,
            "published_redactions": published_redactions,
```

В `templates/documents/document_detail.html` добавить пометку статуса у предложенных связей. Заменить три `<li>`-элемента в `<aside>` так, чтобы у `suggested` выводилась пометка:

«Изменяющие / изменённые акты» — внутри `{% if link.link_type == "amends" ... %}`, после ссылки/цитаты добавить:
```html
          {% if link.status == "suggested" %} <small>(предложена)</small>{% endif %}
```

«Ссылается на» — после `{% else %}<span>{{ link.raw_citation }} (вне корпуса)</span>{% endif %}` добавить перед закрытием `</li>`:
```html
          {% if link.status == "suggested" %} <small>(предложена)</small>{% endif %}
```

«На него ссылаются» — заменить тело `<li>` на:
```html
      <li><a href="{% url 'document_detail' link.from_document.slug %}">{{ link.from_document.official_number }}</a>{% if link.status == "suggested" %} <small>(предложена)</small>{% endif %}</li>
```

(Флаг `is_curator` уже передан в контекст; пометка завязана на `link.status`, поэтому читателю — у которого `suggested` не попадают в выборку — она не покажется.)

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_views.py -v`
Expected: все тесты passed (старые + два новых; старый `test_detail_shows_requisites_articles_and_confirmed_links` остаётся зелёным — читатель по-прежнему не видит suggested).

- [ ] **Step 5: Commit**

```bash
git add documents/views.py templates/documents/document_detail.html documents/tests/test_views.py
git commit -m "feat(documents): curators see suggested links in viewer (closes spec §9)"
```

---

## Task 6: Сквозная проверка и приёмка

**Files:**
- Test: полный прогон; ручная приёмка.

- [ ] **Step 1: Полный прогон тестов**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: все тесты passed (Планы 1+2+3a + ~14 новых теста 3b).

- [ ] **Step 2: Django system check + линт**

Run: `.venv\Scripts\python.exe manage.py check`
Expected: `System check identified no issues`.

Run: `.venv\Scripts\python.exe -m ruff check ingestion documents`
Expected: `All checks passed!`

- [ ] **Step 3: Ручная приёмка (для человека; субагент не запускает)**

```powershell
.venv\Scripts\python.exe manage.py shell -c "from documents.models import Document; Document.objects.get_or_create(slug='zan-fz', defaults={'doc_type':'federal_law','title':'O zanyatosti','official_number':'125-ФЗ','status':'in_force'})"
.venv\Scripts\python.exe manage.py import_document --slug tk-ingest-demo --file ingestion/fixtures_raw/sample_tk.html
.venv\Scripts\python.exe manage.py extract_links --slug tk-ingest-demo
```
(Демо-документ `tk-ingest-demo` создан в приёмке 3a. Чтобы увидеть резолв, заранее заведите цель `125-ФЗ` и добавьте в фикстуру/текст цитату «125-ФЗ».)

Затем `runserver` → admin → **Documents → Links**: видны предложенные авто-связи (`origin=auto`, `status=suggested`). Выбрать → «Подтвердить выбранные связи». Открыть страницу акта куратором → предложенные связи видны с пометкой «(предложена)»; после подтверждения видны и читателю без пометки.

- [ ] **Step 4: Commit (если остались изменения)**

```bash
git status
git add -A && git commit -m "test(ingestion): full acceptance pass for Plan 3b"
```

---

## Self-Review (выполнено при написании плана)

**1. Покрытие спецификации:**
- §6 шаг 6 «Link extraction: найти цитаты, создать Link со status=suggested; внутрикорпусные — с резолвом, внешние — raw_citation» → Task 1 (`find_citations`) + Task 2 (`extract_links_for_redaction`: резолв по `official_number`, иначе `raw_citation`). ✓
- §6: извлечение — часть конвейера приёма → Task 3 (вызов в `ingest_target`/`import_manual`). ✓
- §5 модель Link (origin=auto, status=suggested, context) → Task 2 заполняет эти поля. ✓
- §9 «куратору видны и suggested» → Task 5. Читателю — только confirmed (сохранено). ✓
- §15 риск ложных связей → всё как `suggested`, тип только `references`, консервативный якорь `NNN-ФЗ` → Task 1–2. ✓
- Идемпотентность переизвлечения, без затирания подтверждённых → Task 2 (delete только auto+suggested; dedup по существующим). ✓

**2. Плейсхолдеры:** не найдено — везде полный код/команды.

**3. Согласованность имён/типов:**
- `find_citations(text) -> list[Citation]`, `Citation(number, context)` — Task 1, используются в Task 2.
- `extract_links_for_redaction(redaction) -> int` — Task 2; вызывается в Task 3 (services) и Task 4 (команда).
- `Link.Origin.AUTO`, `Link.Status.SUGGESTED`, `Link.LinkType.REFERENCES` — существующие из модели (План 1).
- Контекст `is_curator`/`request.user.is_staff` и завязка пометки на `link.status` — Task 5 (view + шаблон + тесты согласованы).

**Известные ограничения (для будущих под-планов, не блокеры):**
- Авто-связи только `references`; `amends`/`amended_by` заводит куратор (юридически критично).
- Связи на уровне документа (`from_article=None`); постатейная точность — позже.
- Резолв только по номеру `NNN-ФЗ`/`N-ФКЗ`; цитаты по названию (ТК РФ, «Трудового кодекса») — позже.
- При первичном приёме целевые акты могут быть ещё не в корпусе → станут `raw_citation`; команда `extract_links` пере-резолвит их позже, когда корпус пополнится.

---

## Execution Handoff

План сохранён в `docs/superpowers/plans/2026-06-06-lawiot-plan-3b-link-extraction.md`. Исполнение — субагентами по задачам или инлайн с чекпойнтами (как в Планах 1–3a).
