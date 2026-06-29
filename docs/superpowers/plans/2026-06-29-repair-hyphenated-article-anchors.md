# План: починка якорей дефисных статей + UNIQUE(redaction, anchor)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Починить уже засеянный корпус (дефисные статьи получают правильный `number`/`title`/`anchor`) и навесить частичное `UNIQUE(redaction, anchor) WHERE anchor != ''`, чтобы регрессия была невозможна.

**Architecture:** Хирургическая перенумерация на месте: переразобрать `Redaction.full_text` исправленным парсером, выровнять 1:1 с существующими `Article` по `order` (правка парсера инвариантна по числу узлов), переписать только `number`/`title`/`anchor` у изменившихся строк. `embedding`/`Link`/`parent`/`order` не трогаем (строки обновляются на месте). Логика — в чистой инъектируемой функции `documents/repair.py`, которой пользуются и management-команда, и самоисцеляющаяся миграция.

**Tech Stack:** Django 5.2, PostgreSQL 16 + pgvector, pytest-django, ruff. Парсер — `ingestion/parsing.py`. Спека: `docs/superpowers/specs/2026-06-29-repair-hyphenated-article-anchors-design.md`.

---

## Предусловия

- БД поднята: `docker compose up -d db` (контейнер `lawiot-db`, порт 5433).
- Python проекта: `.venv\Scripts\python.exe` (Windows PowerShell).
- Ветка: `fix/deferred-audit-items` (уже текущая).

---

## Файловая структура

- **Изменить** `documents/models.py` — вынести `compute_anchor()` и `_ANCHOR_PREFIX` на уровень модуля; добавить `UniqueConstraint` в `Article.Meta` (в Задаче 5).
- **Создать** `documents/repair.py` — `RepairReport` + чистая `repair_redaction_anchors(...)`.
- **Создать** `documents/management/commands/repair_article_anchors.py` — команда-обёртка (`--dry-run`).
- **Создать** `documents/migrations/0018_repair_and_uniq_anchor.py` — `RunPython(repair_all)` + `AddConstraint`.
- **Создать** `documents/tests/test_repair.py` — тесты функции, ограничения и команды.

---

## Задача 1: Вынести `compute_anchor` на уровень модуля (рефактор без смены поведения)

**Files:**
- Modify: `documents/models.py` (класс `Article`: `_ANCHOR_PREFIX` строки ~217-223, `save()` строки ~247-253)
- Test: `documents/tests/test_repair.py`

- [ ] **Шаг 1: Написать падающий тест**

Создать `documents/tests/test_repair.py`:

```python
import pytest

from documents.models import Article, compute_anchor
from documents.tests.factories import make_article


def test_compute_anchor_is_module_level_pure():
    assert compute_anchor("article", "123.20-1") == "st-123-20-1"
    assert compute_anchor("article", "341.1-1") == "st-341-1-1"
    assert compute_anchor("point", "1.1") == "p-1-1"
    assert compute_anchor("section", "I") == "razdel-i"


def test_compute_anchor_unknown_kind_raises():
    with pytest.raises(KeyError):
        compute_anchor("unknown", "1")


@pytest.mark.django_db
def test_save_still_derives_anchor_via_compute_anchor():
    art = make_article(number="123.20-1", title="Личный фонд", order=1)
    art.refresh_from_db()
    assert art.anchor == "st-123-20-1"
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py -v`
Expected: FAIL с `ImportError: cannot import name 'compute_anchor' from 'documents.models'`.

- [ ] **Шаг 3: Внести правку в `documents/models.py`**

Удалить атрибут класса `Article._ANCHOR_PREFIX` (строки ~217-223) и добавить на уровень модуля (например, сразу после `EMBEDDING_DIM = 384`):

```python
_ANCHOR_PREFIX = {
    "section": "razdel",
    "chapter": "glava",
    "article": "st",
    "point": "p",
    "appendix": "pril",
}


def compute_anchor(kind: str, number: str) -> str:
    """Якорь узла: «<префикс вида>-<номер с дефисами вместо точек>».

    Прямой доступ по kind: новый вид без префикса упадёт KeyError явно, а не
    получит молча якорь пункта (раньше дефолт был "p").
    """
    prefix = _ANCHOR_PREFIX[kind]
    return f"{prefix}-{slugify(number.replace('.', '-'))}"
```

Заменить тело `Article.save()`:

```python
    def save(self, *args, **kwargs):
        if not self.anchor and self.number:
            self.anchor = compute_anchor(self.kind, self.number)
        super().save(*args, **kwargs)
```

(`slugify` уже импортирован: `from django.utils.text import slugify`.)

- [ ] **Шаг 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py -v`
Expected: PASS (3 теста).

- [ ] **Шаг 5: Прогнать смежные тесты модели и якорей (регрессия)**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_models.py documents/tests/test_subordinate_kinds.py -q`
Expected: PASS (поведение якорей не изменилось).

- [ ] **Шаг 6: Коммит**

```bash
git add documents/models.py documents/tests/test_repair.py
git commit -m "refactor: вынести compute_anchor на уровень модуля (DRY перед починкой)"
```

---

## Задача 2: Чистая функция `repair_redaction_anchors`

**Files:**
- Create: `documents/repair.py`
- Test: `documents/tests/test_repair.py`

- [ ] **Шаг 1: Написать падающие тесты**

Дописать в `documents/tests/test_repair.py` (импорты — вверх файла):

```python
from documents.models import Redaction
from documents.repair import repair_redaction_anchors
from documents.tests.factories import make_document, make_link, make_redaction
from ingestion.parsing import parse_text

# full_text с КОРРЕКТНЫМИ заголовками (как в источнике). Исправленный парсер
# разберёт его в 3 article-узла: 123.20, 123.20-1, 123.20-2.
_FULL_TEXT = (
    "Статья 123.20. Управление наследственным фондом\n"
    "Орган управления фондом.\n"
    "Статья 123.20-1. Личный фонд\n"
    "Личным фондом признаётся учреждённое.\n"
    "Статья 123.20-2. Условия управления\n"
    "Учредитель личного фонда.\n"
)


def _make_buggy_redaction(**red_kwargs):
    """Редакция в «дореформенном» состоянии: суффикс «-N» утёк в title, number
    схлопнут на базовый. Якоря задаём РАЗЛИЧНЫМИ плейсхолдерами явно — иначе
    save() вычислил бы одинаковый «st-123-20» и нарушил будущий UNIQUE при
    вставке фикстуры. Это не влияет на вход починки: она читает number/title/
    kind/order и пересчитывает anchor сама."""
    red = make_redaction(full_text=_FULL_TEXT, **red_kwargs)
    a1 = make_article(
        red, number="123.20", title="Управление наследственным фондом",
        text="Орган управления фондом.", order=1, anchor="st-123-20",
    )
    a2 = make_article(
        red, number="123.20", title="-1. Личный фонд",
        text="Личным фондом признаётся учреждённое.", order=2, anchor="st-123-20-tmp2",
    )
    a3 = make_article(
        red, number="123.20", title="-2. Условия управления",
        text="Учредитель личного фонда.", order=3, anchor="st-123-20-tmp3",
    )
    return red, a1, a2, a3


def _kw():
    return dict(Article=Article, parse_text=parse_text, compute_anchor=compute_anchor)


@pytest.mark.django_db
def test_repair_renumbers_in_place():
    red, a1, a2, a3 = _make_buggy_redaction()
    report = repair_redaction_anchors(red, **_kw())

    assert report.changed and report.changed_articles == 2 and not report.failed
    a1.refresh_from_db(); a2.refresh_from_db(); a3.refresh_from_db()
    assert (a1.number, a1.title, a1.anchor) == ("123.20", "Управление наследственным фондом", "st-123-20")
    assert (a2.number, a2.title, a2.anchor) == ("123.20-1", "Личный фонд", "st-123-20-1")
    assert (a3.number, a3.title, a3.anchor) == ("123.20-2", "Условия управления", "st-123-20-2")


@pytest.mark.django_db
def test_repair_leaves_zero_anchor_dups():
    from django.db.models import Count
    red, *_ = _make_buggy_redaction()
    repair_redaction_anchors(red, **_kw())
    dups = (
        Article.objects.filter(redaction=red).exclude(anchor="")
        .values("anchor").annotate(n=Count("id")).filter(n__gt=1).count()
    )
    assert dups == 0


@pytest.mark.django_db
def test_repair_preserves_text_embedding_and_link():
    red, a1, a2, a3 = _make_buggy_redaction()
    a2.embedding = [0.25] * 384
    a2.save(update_fields=["embedding"])
    a2.refresh_from_db()
    emb_before = list(a2.embedding)
    link = make_link(from_document=red.document, from_article=a2, to_document=red.document)

    repair_redaction_anchors(red, **_kw())

    a2.refresh_from_db(); link.refresh_from_db()
    assert a2.text == "Личным фондом признаётся учреждённое."  # тело не тронуто
    assert list(a2.embedding) == emb_before                    # вектор сохранён
    assert link.from_article_id == a2.pk                       # FK сохранён (тот же PK)


@pytest.mark.django_db
def test_repair_is_idempotent():
    red, *_ = _make_buggy_redaction()
    first = repair_redaction_anchors(red, **_kw())
    second = repair_redaction_anchors(red, **_kw())
    assert first.changed and not second.changed and second.changed_articles == 0


@pytest.mark.django_db
def test_repair_dry_run_writes_nothing():
    red, a1, a2, a3 = _make_buggy_redaction()
    report = repair_redaction_anchors(red, dry_run=True, **_kw())
    assert report.changed and report.changed_articles == 2  # отчёт считает
    a2.refresh_from_db()
    assert a2.number == "123.20"  # откат: строка осталась дореформенной


@pytest.mark.django_db
def test_repair_skips_on_misalignment():
    # full_text даёт 1 узел, а строк 2 → выравнивание невозможно, не трогаем.
    red = make_redaction(full_text="Статья 1. Первая\nтекст.\n")
    make_article(red, number="1", title="Первая", text="текст.", order=1, anchor="st-1")
    make_article(red, number="2", title="Лишняя", text="x", order=2, anchor="st-2")
    report = repair_redaction_anchors(red, **_kw())
    assert report.skipped and not report.changed
    assert Article.objects.get(number="2").title == "Лишняя"  # не тронуто


@pytest.mark.django_db
def test_repair_fails_loud_on_real_duplicate_heading():
    # Источник реально дублирует «Статья 5.» дважды → после починки обе дают
    # «st-5». В тест-БД ограничение уже есть → bulk_update даст IntegrityError;
    # функция ловит его (вложенный savepoint) и возвращает failed=True с откатом.
    red = make_redaction(full_text="Статья 5. Первая\nA.\nСтатья 5. Вторая\nB.\n")
    make_article(red, number="5", title="Первая", text="A.", order=1, anchor="st-5")
    a2 = make_article(red, number="5", title="X", text="B.", order=2, anchor="st-5-tmp")
    report = repair_redaction_anchors(red, **_kw())
    assert report.failed and not report.changed
    a2.refresh_from_db()
    assert a2.anchor == "st-5-tmp"  # откат: строка не тронута


@pytest.mark.django_db
def test_repair_refreshes_search_vector_only_for_published():
    # Опубликованная: изменённой строке обновляем search_vector (был None → стал не None).
    pub, _a1, a2, _a3 = _make_buggy_redaction(
        review_status=Redaction.ReviewStatus.PUBLISHED, is_current=True
    )
    Article.objects.filter(pk=a2.pk).update(search_vector=None)
    repair_redaction_anchors(pub, **_kw())
    assert Article.objects.get(pk=a2.pk).search_vector is not None

    # Черновик: индекс не трогаем (остаётся None).
    draft, _b1, b2, _b3 = _make_buggy_redaction(
        document=make_document(slug="gk-rf", official_number="51-ФЗ"),
        review_status=Redaction.ReviewStatus.DRAFT,
    )
    Article.objects.filter(pk=b2.pk).update(search_vector=None)
    repair_redaction_anchors(draft, **_kw())
    assert Article.objects.get(pk=b2.pk).search_vector is None
```

Также добавить `compute_anchor` в существующий импорт из `documents.models` вверху файла:
`from documents.models import Article, Redaction, compute_anchor`.

- [ ] **Шаг 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'documents.repair'`.

- [ ] **Шаг 3: Реализовать `documents/repair.py`**

```python
"""Починка номеров/якорей дефисных статей в УЖЕ засеянном корпусе.

Парсер до c99c9a7 терял дефисный суффикс номера статьи («Статья 123.20-1»
разбиралась как number="123.20", title="-1. …»), из-за чего реальные дефисные
статьи схлопывались на базовый номер → совпадающие anchor внутри редакции.

Корень исправлен в парсере; здесь — разовая починка хранимых строк. Подход:
переразобрать Redaction.full_text исправленным парсером и выровнять результат
1:1 с существующими Article по order. Правка парсера инвариантна по числу узлов
(тот же order/kind/parent), поэтому переписать нужно только number/title/anchor
у изменившихся строк. embedding (считается из text, а text идентичен), FK Link и
parent сохраняются — строки обновляются на месте, без delete/recreate.
search_vector (индексирует number/title) обновляется у изменённых строк
опубликованных редакций.

Функция чистая и инъектируемая: parse_text и compute_anchor передаются
параметрами, модели — тоже (конкретные из команды, исторические из миграции),
поэтому модуль безопасно импортировать из RunPython-миграции.
"""

from dataclasses import dataclass

from django.contrib.postgres.search import SearchVector
from django.db import IntegrityError, transaction
from django.db.models import Count


@dataclass
class RepairReport:
    redaction_id: int
    changed_articles: int = 0
    changed: bool = False
    skipped: bool = False
    failed: bool = False
    reason: str = ""


class _AnchorCollision(Exception):
    """Внутренний сигнал: после починки в редакции остались дубль-якоря."""


def _article_search_vector():
    # 1-в-1 с Redaction.update_search_index(): number/title — вес A, text — B.
    return (
        SearchVector("number", weight="A", config="russian")
        + SearchVector("title", weight="A", config="russian")
        + SearchVector("text", weight="B", config="russian")
    )


def repair_redaction_anchors(redaction, *, Article, parse_text, compute_anchor, dry_run=False):
    """Починить одну редакцию на месте. Возвращает RepairReport.

    Каждая редакция чинится в своей транзакции: пропуск/ошибка одной не рушит
    остальные. dry_run=True откатывает запись (set_rollback), но отчёт считает.
    """
    with transaction.atomic():
        existing = list(Article.objects.filter(redaction=redaction).order_by("order", "pk"))
        nodes = parse_text(redaction.full_text or "", redaction.document.doc_type).articles

        # Защита: переразбор обязан выровняться 1:1 (число и виды узлов). Иначе
        # редакцию засеял другой парсер — не трогаем, сообщаем.
        if len(existing) != len(nodes) or any(
            row.kind != node.kind for row, node in zip(existing, nodes)
        ):
            return RepairReport(
                redaction.pk,
                skipped=True,
                reason=f"переразбор не выровнялся: строк {len(existing)}, узлов {len(nodes)}",
            )

        changed = []
        for row, node in zip(existing, nodes):
            if row.number != node.number or row.title != node.title:
                row.number = node.number
                row.title = node.title
                row.anchor = compute_anchor(node.kind, node.number)
                changed.append(row)

        if not changed:
            return RepairReport(redaction.pk, changed_articles=0, changed=False)

        # Запись — во вложенном savepoint. Дубль якоря всплывёт двояко:
        #  - в миграции (ограничения ещё нет) — через пост-проверку ниже;
        #  - в тест-/прод-БД (ограничение уже есть) — как IntegrityError на
        #    bulk_update. Ловим оба единообразно: savepoint откатан, failed=True.
        try:
            with transaction.atomic():
                Article.objects.bulk_update(changed, ["number", "title", "anchor"])

                # search_vector индексирует number/title — обновляем изменённые
                # строки, но только в опубликованных редакциях (черновики не
                # индексируются).
                if (redaction.review_status or "") == "published":
                    Article.objects.filter(pk__in=[a.pk for a in changed]).update(
                        search_vector=_article_search_vector()
                    )

                dup = (
                    Article.objects.filter(redaction=redaction)
                    .exclude(anchor="")
                    .values("anchor")
                    .annotate(n=Count("id"))
                    .filter(n__gt=1)
                    .count()
                )
                if dup:
                    raise _AnchorCollision(dup)
        except (IntegrityError, _AnchorCollision) as exc:
            return RepairReport(
                redaction.pk,
                failed=True,
                reason=f"конфликт уникальности якоря (дубль заголовка в источнике?): {exc}",
            )

        if dry_run:
            transaction.set_rollback(True)
        return RepairReport(redaction.pk, changed_articles=len(changed), changed=True)
```

> Транзакционная модель: внешний `atomic` — изоляция редакции; внутренний savepoint
> оборачивает запись, чтобы `IntegrityError` от `bulk_update` откатился чисто, не
> «отравив» внешнюю транзакцию. При `dry_run` запись успешно уходит в savepoint,
> освобождается во внешнюю транзакцию, а `set_rollback(True)` откатывает её на выходе.

- [ ] **Шаг 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py -v`
Expected: PASS (все тесты Задач 1-2).

- [ ] **Шаг 5: Коммит**

```bash
git add documents/repair.py documents/tests/test_repair.py
git commit -m "feat: чистая repair_redaction_anchors — починка дефисных номеров на месте"
```

---

## Задача 3: Management-команда `repair_article_anchors`

**Files:**
- Create: `documents/management/commands/repair_article_anchors.py`
- Test: `documents/tests/test_repair.py`

- [ ] **Шаг 1: Написать падающий тест**

Дописать в `documents/tests/test_repair.py`:

```python
from io import StringIO

from django.core.management import call_command


@pytest.mark.django_db
def test_command_dry_run_then_apply():
    red, _a1, a2, _a3 = _make_buggy_redaction()

    out = StringIO()
    call_command("repair_article_anchors", "--dry-run", stdout=out)
    a2.refresh_from_db()
    assert a2.number == "123.20"                 # dry-run ничего не записал
    assert "dry-run" in out.getvalue().lower()

    out = StringIO()
    call_command("repair_article_anchors", stdout=out)
    a2.refresh_from_db()
    assert a2.number == "123.20-1"               # реальный запуск починил
    assert "дубль-групп" in out.getvalue()
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py::test_command_dry_run_then_apply -v`
Expected: FAIL с `CommandError: Unknown command: 'repair_article_anchors'`.

- [ ] **Шаг 3: Реализовать команду**

`documents/management/commands/repair_article_anchors.py`:

```python
"""Разовая починка номеров/якорей дефисных статей в существующем корпусе.

Переразбирает Redaction.full_text исправленным парсером и переписывает
number/title/anchor на месте (см. documents/repair.py). Идемпотентна.
`--dry-run` — показать объём правок без записи.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from documents.models import Article, Redaction, compute_anchor
from documents.repair import repair_redaction_anchors
from ingestion.parsing import parse_text


class Command(BaseCommand):
    help = "Чинит дефисные номера/якоря статей (переразбор full_text). Идемпотентна."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что изменится, и откатить — ничего не записывать.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        changed_red = skipped = failed = changed_articles = 0

        qs = Redaction.objects.select_related("document").order_by("pk")
        for redaction in qs.iterator():
            report = repair_redaction_anchors(
                redaction,
                Article=Article,
                parse_text=parse_text,
                compute_anchor=compute_anchor,
                dry_run=dry,
            )
            if report.failed:
                failed += 1
                self.stderr.write(f"  ! редакция #{report.redaction_id}: {report.reason}")
            elif report.skipped:
                skipped += 1
                self.stdout.write(f"  ~ редакция #{report.redaction_id} пропущена: {report.reason}")
            elif report.changed:
                changed_red += 1
                changed_articles += report.changed_articles

        dups = (
            Article.objects.exclude(anchor="")
            .values("redaction", "anchor")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .count()
        )
        prefix = "[dry-run] " if dry else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Изменено редакций: {changed_red} (статей: {changed_articles}); "
                f"пропущено: {skipped}; с ошибкой: {failed}; "
                f"дубль-групп (redaction, anchor) сейчас: {dups}."
            )
        )
```

> Примечание: в `--dry-run` записи откатываются, поэтому «дубль-групп сейчас» показывает ТЕКУЩЕЕ (дореформенное) число — это объём предстоящей работы. После реального запуска должно стать 0.

- [ ] **Шаг 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py -v`
Expected: PASS (включая тест команды).

- [ ] **Шаг 5: Коммит**

```bash
git add documents/management/commands/repair_article_anchors.py documents/tests/test_repair.py
git commit -m "feat: команда repair_article_anchors (--dry-run, идемпотентна)"
```

---

## Задача 4: Прогон на dev-корпусе и проверка дублей = 0

**Files:** нет (операционный шаг на реальной БД).

- [ ] **Шаг 1: Поднять БД**

Run: `docker compose up -d db`
Expected: контейнер `lawiot-db` запущен (healthy).

- [ ] **Шаг 2: Зафиксировать текущее число дубль-групп**

Run:
```bash
.venv\Scripts\python.exe manage.py shell -c "from django.db.models import Count; from documents.models import Article; print('dups:', Article.objects.exclude(anchor='').values('redaction','anchor').annotate(n=Count('id')).filter(n__gt=1).count())"
```
Expected: `dups: 33` (или близко — ненулевое число дореформенных групп).

- [ ] **Шаг 3: Dry-run и инспекция пропусков/ошибок**

Run: `.venv\Scripts\python.exe manage.py repair_article_anchors --dry-run`
Expected: строка-итог вида `[dry-run] Изменено редакций: N (статей: M); пропущено: 0; с ошибкой: 0; дубль-групп ... сейчас: 33.`
**Стоп-условие:** если `с ошибкой` > 0 или `пропущено` > 0 — не применять; разобрать перечисленные `#id` (реальные дубли заголовков в источнике или редакция от другого парсера) и решить точечно. По спеке ожидается 0/0.

- [ ] **Шаг 4: Применить починку**

Run: `.venv\Scripts\python.exe manage.py repair_article_anchors`
Expected: `Изменено редакций: N (статей: M); пропущено: 0; с ошибкой: 0; дубль-групп (redaction, anchor) сейчас: 0.`

- [ ] **Шаг 5: Подтвердить дубли = 0 независимым запросом**

Run:
```bash
.venv\Scripts\python.exe manage.py shell -c "from django.db.models import Count; from documents.models import Article; print('dups:', Article.objects.exclude(anchor='').values('redaction','anchor').annotate(n=Count('id')).filter(n__gt=1).count())"
```
Expected: `dups: 0`.

- [ ] **Шаг 6: Точечная проверка известных дефисных статей**

Run:
```bash
.venv\Scripts\python.exe manage.py shell -c "from documents.models import Article; print(sorted(set(Article.objects.filter(number__startswith='123.20-').values_list('number', flat=True)))); print(sorted(set(Article.objects.filter(number__startswith='341.1-').values_list('number', flat=True))))"
```
Expected: видны корректные дефисные номера (например, `['123.20-1', ..., '123.20-8']`, `['341.1-1', ...]`), а в `title` больше нет ведущих «-1.»/«-2.».

(Коммита нет — это правка данных, не кода.)

---

## Задача 5: Ограничение `UNIQUE(redaction, anchor)` + самоисцеляющаяся миграция

**Files:**
- Modify: `documents/models.py` (`Article.Meta.constraints`, строки ~237-245)
- Create: `documents/migrations/0018_repair_and_uniq_anchor.py`
- Test: `documents/tests/test_repair.py`

- [ ] **Шаг 1: Написать падающие тесты ограничения**

Дописать в `documents/tests/test_repair.py` (импорты — вверх файла):

```python
from django.db import transaction
from django.db.utils import IntegrityError


@pytest.mark.django_db
def test_unique_constraint_rejects_duplicate_anchor():
    red = make_redaction()
    make_article(red, number="5", title="Первая", text="a", order=1)  # anchor st-5
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Article.objects.create(
                redaction=red, kind=Article.Kind.ARTICLE,
                number="5", title="Дубль", text="b", order=2,  # снова st-5
            )


@pytest.mark.django_db
def test_unique_constraint_allows_multiple_blank_anchors():
    red = make_redaction()
    Article.objects.create(
        redaction=red, kind=Article.Kind.ARTICLE, number="", title="x", text="a", order=1, anchor=""
    )
    Article.objects.create(
        redaction=red, kind=Article.Kind.ARTICLE, number="", title="y", text="b", order=2, anchor=""
    )
    assert Article.objects.filter(redaction=red, anchor="").count() == 2
```

- [ ] **Шаг 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py::test_unique_constraint_rejects_duplicate_anchor -v`
Expected: FAIL — `DID NOT RAISE IntegrityError` (ограничения ещё нет).

- [ ] **Шаг 3: Добавить ограничение в `Article.Meta`**

В `documents/models.py`, `Article.Meta.constraints`, добавить второй элемент после `CheckConstraint`:

```python
        constraints = [
            models.CheckConstraint(
                condition=~Q(parent=F("id")),
                name="article_not_self_parent",
            ),
            # Дубли (redaction, anchor) ломали страницу разъяснения (500,
            # MultipleObjectsReturned). Частичное: пустой anchor не уникален
            # (узлы без номера легитимно его не имеют).
            models.UniqueConstraint(
                fields=["redaction", "anchor"],
                condition=~Q(anchor=""),
                name="uniq_article_redaction_anchor",
            ),
        ]
```

(`Q` и `F` уже импортированы: `from django.db.models import F, Q, Value`.)

- [ ] **Шаг 4: Сгенерировать миграцию автоматически**

Run: `.venv\Scripts\python.exe manage.py makemigrations documents --name repair_and_uniq_anchor`
Expected: создан `documents/migrations/0018_repair_and_uniq_anchor.py` с единственной операцией `AddConstraint`.

- [ ] **Шаг 5: Вставить самоисцеляющую `RunPython` ПЕРЕД `AddConstraint`**

Отредактировать `documents/migrations/0018_repair_and_uniq_anchor.py` к виду (сохранив сгенерённую `dependencies` и сам `AddConstraint`):

```python
from django.db import migrations, models
from django.db.models import Q


def repair_all(apps, schema_editor):
    """Самоисцеление перед установкой ограничения: чиним дефисные номера/якоря.
    No-op на пустой БД (CI/тесты) — редакций нет, цикл не выполняется."""
    from documents.models import compute_anchor
    from documents.repair import repair_redaction_anchors
    from ingestion.parsing import parse_text

    Redaction = apps.get_model("documents", "Redaction")
    Article = apps.get_model("documents", "Article")
    for redaction in Redaction.objects.select_related("document").iterator():
        repair_redaction_anchors(
            redaction, Article=Article, parse_text=parse_text, compute_anchor=compute_anchor
        )


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0017_article_embedding_article_article_embedding_hnsw"),
    ]

    operations = [
        # Сначала чистим данные, ПОТОМ ставим ограничение — порядок гарантирован
        # одним файлом. Обратная RunPython — noop (починку не откатываем).
        migrations.RunPython(repair_all, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.UniqueConstraint(
                fields=["redaction", "anchor"],
                condition=~Q(anchor=""),
                name="uniq_article_redaction_anchor",
            ),
        ),
    ]
```

- [ ] **Шаг 6: Применить миграцию к dev-БД**

Run: `.venv\Scripts\python.exe manage.py migrate documents`
Expected: `Applying documents.0018_repair_and_uniq_anchor... OK` (репарация уже была выполнена в Задаче 4 → RunPython проходит no-op'ом по сути, AddConstraint успешен).

- [ ] **Шаг 7: Запустить тесты ограничения — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_repair.py -v`
Expected: PASS (включая оба теста ограничения).

- [ ] **Шаг 8: `makemigrations --check` — миграции в синхроне**

Run: `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
Expected: «No changes detected» (модель и миграции согласованы).

- [ ] **Шаг 9: Коммит**

```bash
git add documents/models.py documents/migrations/0018_repair_and_uniq_anchor.py documents/tests/test_repair.py
git commit -m "feat: UNIQUE(redaction, anchor) + самоисцеляющая миграция 0018"
```

---

## Задача 6: Полная проверка (критерии готовности)

**Files:** нет.

- [ ] **Шаг 1: Весь набор тестов**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: все зелёные (≥494 + новые из `test_repair.py`), без падений.

- [ ] **Шаг 2: Линтер**

Run: `.venv\Scripts\python.exe -m ruff check`
Expected: «All checks passed!». (При замечаниях — поправить, держать строки ≤100.)

- [ ] **Шаг 3: Согласованность миграций**

Run: `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
Expected: «No changes detected».

- [ ] **Шаг 4: Финальная проверка дублей**

Run:
```bash
.venv\Scripts\python.exe manage.py shell -c "from django.db.models import Count; from documents.models import Article; print('dups:', Article.objects.exclude(anchor='').values('redaction','anchor').annotate(n=Count('id')).filter(n__gt=1).count())"
```
Expected: `dups: 0`.

- [ ] **Шаг 5: Финальный коммит (если что-то правилось линтером)**

```bash
git add -A
git commit -m "chore: финальная проверка — pytest/ruff/makemigrations чисто, дублей 0"
```

---

## Замечания по охвату (из спеки)

- Починка идёт по **всем** редакциям (включая черновики): ограничение per-redaction, иначе `AddConstraint` упал бы на «грязном» черновике.
- `Note.article_number` (свободный текст) и оборонительный обход «первая по order» в `documents/views.py::article_explain` оставляем как есть — вне охвата, оба остаются корректными.
- `embedding` НЕ перегенерируется: он считается из `article.text`, а тело статьи при переразборе байт-в-байт идентично (суффикс уходит из `title` в `number`).
