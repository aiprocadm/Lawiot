# «Вы искали…» (исправление опечаток) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При нулевом результате поиска предлагать ближайшее по написанию слово корпуса как кликабельную ссылку «Возможно, вы искали: …».

**Architecture:** Словарь словоформ корпуса (`SearchVocab`) наполняется management-командой из текста статей; триггерится `pg_trgm` GIN-индекс. Логика подсказки (`search/suggest.py`) ищет ближайшее слово по триграммному сходству только для незнакомых корпусу токенов; view показывает подсказку лишь когда исправленный запрос реально даёт результаты.

**Tech Stack:** Django 5.2, PostgreSQL + `pg_trgm` (`TrigramSimilarity`, GIN trigram index), pytest-django. Спека: `docs/superpowers/specs/2026-06-30-search-did-you-mean-design.md`.

---

## Предусловия для запуска тестов

- Контейнер БД поднят: `docker start lawiot-db` (Postgres на `localhost:5433`; без него pytest зависает).
- Python из venv: `D:\Кодинг\2. Lawiot\Lawiot\.venv\Scripts\python.exe` (далее — `python`).
- Тестовая БД применяет миграции (включая `TrigramExtension`/`VectorExtension`) автоматически; права на `CREATE EXTENSION` подтверждены прецедентом pgvector (`0017`).

## Структура файлов

| Файл | Действие | Ответственность |
|---|---|---|
| `documents/models.py` | Modify | модель `SearchVocab` |
| `documents/migrations/0019_searchvocab.py` | Create | `TrigramExtension` + `SearchVocab` + GIN-триграммный индекс |
| `search/suggest.py` | Create | `tokenize()` (Task 2) + `suggest_query()` (Task 3) |
| `documents/management/commands/build_search_vocab.py` | Create | сборка словаря из корпуса |
| `search/views.py` | Modify | интеграция в `search_view` |
| `templates/search/_results.html` | Modify | рендер подсказки в `{% empty %}` |
| `search/tests/test_suggest.py` | Create | тесты всех уровней |

---

### Task 1: Модель `SearchVocab` + миграция (расширение + индекс)

**Files:**
- Modify: `documents/models.py`
- Create: `documents/migrations/0019_searchvocab.py`
- Test: `search/tests/test_suggest.py`

- [ ] **Step 1: Написать падающий тест**

Создать `search/tests/test_suggest.py`:

```python
import pytest
from django.contrib.postgres.search import TrigramSimilarity

from documents.models import SearchVocab


@pytest.mark.django_db
def test_searchvocab_trigram_similarity_query_works():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    SearchVocab.objects.create(word="отпуск", frequency=5)
    nearest = (
        SearchVocab.objects.annotate(sim=TrigramSimilarity("word", "уволнение"))
        .order_by("-sim")
        .first()
    )
    assert nearest.word == "увольнение"
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python -m pytest search/tests/test_suggest.py -v`
Expected: FAIL — `ImportError: cannot import name 'SearchVocab' from 'documents.models'`.

- [ ] **Step 3: Добавить модель в `documents/models.py`**

`GinIndex` уже импортирован в начале файла (строка 1). Добавить модель в конец файла:

```python
class SearchVocab(models.Model):
    """Словарь словоформ корпуса для исправления опечаток (did-you-mean).

    Наполняется командой build_search_vocab из текста статей. Триграммный
    GIN-индекс (pg_trgm) делает поиск ближайшего по написанию слова дешёвым.
    Хранятся реальные словоформы (не основы search_vector) — чтобы подсказывать
    «увольнение», а не основу «увольнен».
    """

    word = models.CharField(max_length=64, unique=True)
    frequency = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [
            GinIndex(
                fields=["word"],
                name="searchvocab_word_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.word} ({self.frequency})"
```

- [ ] **Step 4: Сгенерировать миграцию и дописать расширение**

Run: `python manage.py makemigrations documents --name searchvocab`

`makemigrations` создаст модель и индекс, но НЕ добавит расширение `pg_trgm`. Открыть
сгенерированный `documents/migrations/0019_searchvocab.py` и привести к виду (добавить импорт
`TrigramExtension` и поставить `TrigramExtension()` первой операцией — до `CreateModel`/`AddIndex`):

```python
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0018_article_uniq_redaction_anchor"),
    ]

    operations = [
        # CREATE EXTENSION IF NOT EXISTS pg_trgm — до индекса с gin_trgm_ops.
        TrigramExtension(),
        migrations.CreateModel(
            name="SearchVocab",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("word", models.CharField(max_length=64, unique=True)),
                ("frequency", models.PositiveIntegerField(default=1)),
            ],
        ),
        migrations.AddIndex(
            model_name="searchvocab",
            index=GinIndex(fields=["word"], name="searchvocab_word_trgm", opclasses=["gin_trgm_ops"]),
        ),
    ]
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `python -m pytest search/tests/test_suggest.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Проверить, что нет незакоммиченных изменений схемы**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 7: Коммит**

```bash
git add documents/models.py documents/migrations/0019_searchvocab.py search/tests/test_suggest.py
git commit -m "feat(search): модель SearchVocab + pg_trgm для did-you-mean"
```

---

### Task 2: Токенизация + команда `build_search_vocab`

**Files:**
- Create: `search/suggest.py`
- Create: `documents/management/commands/build_search_vocab.py`
- Test: `search/tests/test_suggest.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Дописать в `search/tests/test_suggest.py` (импорты — в начало файла):

```python
from django.core.management import call_command

from documents.tests.factories import make_article, make_document, make_redaction
from search.suggest import tokenize


def test_tokenize_normalizes_and_splits():
    assert tokenize("Увольнение по СОБСТВЕННОМУ; ёлка") == [
        "увольнение",
        "по",
        "собственному",
        "елка",
    ]


@pytest.mark.django_db
def test_build_search_vocab_counts_filters_and_normalizes():
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(
        red,
        number="81",
        title="Расторжение",
        text="увольнение работника. увольнение по статье. ёлка ёлка",
    )
    red.publish()

    call_command("build_search_vocab", "--min-len", "4", "--min-freq", "2")

    words = {v.word: v.frequency for v in SearchVocab.objects.all()}
    assert words.get("увольнение") == 2  # частотное слово сохранено
    assert words.get("елка") == 2  # ё→е нормализовано, посчитано как одно слово
    assert "по" not in words  # короче min-len=4
    assert "работника" not in words  # частота 1 < min-freq=2
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `python -m pytest search/tests/test_suggest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'search.suggest'`.

- [ ] **Step 3: Создать `search/suggest.py` с токенизатором**

```python
"""Подсказка «Вы искали…» (исправление опечаток) на pg_trgm.

Словарь словоформ корпуса (documents.SearchVocab) наполняется командой
build_search_vocab. При нулевом результате поиска suggest_query() ищет
ближайшее по написанию слово только для незнакомых корпусу токенов.
"""

import re

# Нормализация совпадает с поисковой (search.lemmas._normalize): lowercase + ё→е.
_TOKEN_RE = re.compile(r"[а-яёa-z]+")


def tokenize(text: str) -> list[str]:
    """Слова текста: lowercase, ё→е, в порядке появления."""
    return [m.replace("ё", "е") for m in _TOKEN_RE.findall((text or "").lower())]
```

- [ ] **Step 4: Создать команду `documents/management/commands/build_search_vocab.py`**

```python
"""Сборка словаря словоформ корпуса для исправления опечаток (did-you-mean).

Вне request-пути. Идемпотентна: полностью пересобирает SearchVocab из текста
статей текущих опубликованных редакций. По образцу embed_articles.
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from documents.models import Article, Redaction, SearchVocab
from search.suggest import tokenize

_BATCH = 1000


class Command(BaseCommand):
    help = "Строит словарь словоформ корпуса для исправления опечаток (did-you-mean)."

    def add_arguments(self, parser):
        parser.add_argument("--min-len", type=int, default=4, help="Минимальная длина слова.")
        parser.add_argument(
            "--min-freq", type=int, default=2, help="Минимальная частота слова в корпусе."
        )

    def handle(self, *args, **options):
        min_len = options["min_len"]
        min_freq = options["min_freq"]

        counter: Counter[str] = Counter()
        texts = (
            Article.objects.filter(
                redaction__is_current=True,
                redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
            )
            .values_list("text", flat=True)
            .iterator(chunk_size=200)
        )
        articles = 0
        for text in texts:
            articles += 1
            for token in tokenize(text):
                if len(token) >= min_len:
                    counter[token] += 1

        rows = [
            SearchVocab(word=word, frequency=freq)
            for word, freq in counter.items()
            if freq >= min_freq
        ]
        with transaction.atomic():
            SearchVocab.objects.all().delete()
            SearchVocab.objects.bulk_create(rows, batch_size=_BATCH)

        self.stdout.write(
            self.style.SUCCESS(f"Статей обработано: {articles}; слов в словаре: {len(rows)}")
        )
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `python -m pytest search/tests/test_suggest.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Коммит**

```bash
git add search/suggest.py documents/management/commands/build_search_vocab.py search/tests/test_suggest.py
git commit -m "feat(search): команда build_search_vocab + токенизатор словаря"
```

---

### Task 3: Движок подсказки `suggest_query`

**Files:**
- Modify: `search/suggest.py`
- Test: `search/tests/test_suggest.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Дописать в `search/tests/test_suggest.py` (добавить `suggest_query` в импорт из `search.suggest`):

```python
from search.suggest import suggest_query, tokenize  # заменить прежний импорт tokenize


@pytest.mark.django_db
def test_suggest_corrects_typo():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    assert suggest_query("уволнение") == "увольнение"


@pytest.mark.django_db
def test_suggest_returns_none_when_all_known():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    assert suggest_query("увольнение") is None


@pytest.mark.django_db
def test_suggest_returns_none_when_no_close_match():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    assert suggest_query("ббббббб") is None


@pytest.mark.django_db
def test_suggest_fixes_only_unknown_token():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    SearchVocab.objects.create(word="работника", frequency=8)
    assert suggest_query("уволнение работника") == "увольнение работника"


@pytest.mark.django_db
def test_suggest_empty_vocab_returns_none():
    assert suggest_query("уволнение") is None
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `python -m pytest search/tests/test_suggest.py -k suggest_ -v`
Expected: FAIL — `ImportError: cannot import name 'suggest_query' from 'search.suggest'`.

- [ ] **Step 3: Добавить `suggest_query` в `search/suggest.py`**

Дописать импорты в начало файла и функцию в конец:

```python
import logging

from django.contrib.postgres.search import TrigramSimilarity

logger = logging.getLogger("search")

# Дефолтный порог сходства pg_trgm: ниже него кандидат считается несвязанным.
SIMILARITY_THRESHOLD = 0.3


def suggest_query(query_text: str) -> str | None:
    """Исправленный запрос или None.

    Возвращает строку, только если заменён хотя бы один незнакомый корпусу
    токен на ближайшее по триграммному сходству слово словаря. Известные
    корпусу слова не трогает. Любая ошибка/пустой словарь → None (деградация).
    """
    from documents.models import SearchVocab

    tokens = tokenize(query_text)
    if not tokens:
        return None
    try:
        known = set(
            SearchVocab.objects.filter(word__in=tokens).values_list("word", flat=True)
        )
        replaced = False
        out: list[str] = []
        for token in tokens:
            if token in known:
                out.append(token)
                continue
            nearest = (
                SearchVocab.objects.annotate(sim=TrigramSimilarity("word", token))
                .filter(sim__gte=SIMILARITY_THRESHOLD)
                .order_by("-sim", "-frequency")
                .first()
            )
            if nearest is not None:
                out.append(nearest.word)
                replaced = True
            else:
                out.append(token)
        return " ".join(out) if replaced else None
    except Exception:  # noqa: BLE001 — подсказка не критична: деградируем тихо
        logger.exception("suggest_query failed")
        return None
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `python -m pytest search/tests/test_suggest.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Коммит**

```bash
git add search/suggest.py search/tests/test_suggest.py
git commit -m "feat(search): движок suggest_query (триграммное исправление опечаток)"
```

---

### Task 4: Интеграция во view + шаблон

**Files:**
- Modify: `search/views.py`
- Modify: `templates/search/_results.html`
- Test: `search/tests/test_suggest.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Дописать в `search/tests/test_suggest.py` (импорты `reverse`, `Document` — в начало файла):

```python
from django.urls import reverse

from documents.models import Document


@pytest.mark.django_db
def test_search_suggests_on_zero_results(auth_client):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение", text="увольнение работника")
    red.publish()
    call_command("build_search_vocab", "--min-len", "4", "--min-freq", "1")

    response = auth_client.get(reverse("search"), {"q": "уволнение"})
    content = response.content.decode()
    assert response.status_code == 200
    assert "Возможно, вы искали" in content
    assert "увольнение" in content


@pytest.mark.django_db
def test_search_no_suggestion_when_results_exist(auth_client):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение", text="увольнение работника")
    red.publish()
    call_command("build_search_vocab", "--min-len", "4", "--min-freq", "1")

    response = auth_client.get(reverse("search"), {"q": "увольнение"})
    content = response.content.decode()
    assert "Возможно, вы искали" not in content


@pytest.mark.django_db
def test_suggestion_link_keeps_filters(auth_client):
    doc = make_document(
        slug="tk", title="ТК", official_number="197-ФЗ", doc_type=Document.DocType.FEDERAL_LAW
    )
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение", text="увольнение работника")
    red.publish()
    call_command("build_search_vocab", "--min-len", "4", "--min-freq", "1")

    response = auth_client.get(
        reverse("search"), {"q": "уволнение", "doc_type": "federal_law"}
    )
    content = response.content.decode()
    assert "Возможно, вы искали" in content
    assert "doc_type=federal_law" in content


@pytest.mark.django_db
def test_no_suggestion_when_corrected_query_still_empty(auth_client):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение", text="увольнение работника")
    red.publish()
    call_command("build_search_vocab", "--min-len", "4", "--min-freq", "1")

    response = auth_client.get(reverse("search"), {"q": "уволнение незнакомоеслово"})
    content = response.content.decode()
    assert "Возможно, вы искали" not in content
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `python -m pytest search/tests/test_suggest.py -k "suggests or suggestion or no_suggestion" -v`
Expected: FAIL — подсказки нет в выводе (`assert "Возможно, вы искали" in content` падает).

- [ ] **Step 3: Обновить `search/views.py`**

Полностью заменить тело `search_view` (и добавить импорт `suggest_query`):

```python
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from search.forms import SearchForm
from search.services import search_documents
from search.suggest import suggest_query

PAGE_SIZE = 20


@login_required
def search_view(request):
    form = SearchForm(request.GET or None)
    results = []
    suggestion = None
    suggestion_qs = ""
    query = request.GET.get("q", "")
    if form.is_valid() and form.cleaned_data.get("q"):
        cd = form.cleaned_data
        filters = dict(
            doc_type=cd["doc_type"],
            status=cd["status"],
            issuing_body=cd["issuing_body"],
            date_from=cd["date_from"],
            date_to=cd["date_to"],
        )
        results = search_documents(cd["q"], **filters)
        if cd.get("sort") == "date":
            # Новые первыми по дате подписания; акты без даты — в конце.
            results = sorted(
                results,
                key=lambda r: (r.document.sign_date is not None, r.document.sign_date),
                reverse=True,
            )
        if not results:
            # Did-you-mean: только при нуле и только если исправление даёт результаты.
            candidate = suggest_query(cd["q"])
            if candidate and search_documents(candidate, **filters):
                suggestion = candidate
                sug_params = request.GET.copy()
                sug_params["q"] = candidate
                sug_params.pop("page", None)
                suggestion_qs = sug_params.urlencode()

    page_obj = Paginator(results, PAGE_SIZE).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "form": form,
        "page_obj": page_obj,
        "query": query,
        "base_qs": params.urlencode(),
        "suggestion": suggestion,
        "suggestion_qs": suggestion_qs,
    }

    template = "search/_results.html" if request.headers.get("HX-Request") else "search/search.html"
    return render(request, template, context)
```

- [ ] **Step 4: Обновить `templates/search/_results.html`**

Заменить блок `{% empty %}` (строки 14-15) на:

```html
{% empty %}
{% if suggestion %}
<p>Ничего не найдено. Возможно, вы искали:
  <a href="?{{ suggestion_qs }}"
     hx-get="?{{ suggestion_qs }}"
     hx-target="#search-results" hx-push-url="true">{{ suggestion }}</a>?</p>
{% else %}
<p>Ничего не найдено.</p>
{% endif %}
{% endfor %}
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `python -m pytest search/tests/test_suggest.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 6: Коммит**

```bash
git add search/views.py templates/search/_results.html search/tests/test_suggest.py
git commit -m "feat(search): подсказка «Вы искали…» во view и шаблоне результатов"
```

---

### Task 5: Финальная верификация

**Files:** —

- [ ] **Step 1: Полный прогон тестов поиска + линт + миграции**

Run: `python -m pytest search/ -v`
Expected: PASS (включая прежние тесты поиска — регрессий нет).

Run: `ruff check .`
Expected: без ошибок.

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 2: Полный прогон всего набора**

Run: `python -m pytest`
Expected: все тесты зелёные (прежний baseline + новые).

- [ ] **Step 3: (Операционно, вне тестов) Наполнить словарь на dev-БД**

Run: `python manage.py build_search_vocab`
Expected: `Статей обработано: N; слов в словаре: M` (M > 0). Без этого подсказка не работает на реальных данных — словарь строится из корпуса.

---

## Заметки реализатору

- **DRY нормализации:** `tokenize()` в `search/suggest.py` — единственный токенизатор; команда импортирует его. Нормализация (`lower` + ё→е) совпадает с `search.lemmas._normalize`, чтобы слова словаря совпадали с тем, как ищет FTS.
- **Почему подсказка только на нуле:** см. спеку §«Решение». Лишний `search_documents(candidate)` платится лишь на нулевом (редком) запросе.
- **Деградация:** `suggest_query` ловит любые исключения (нет `pg_trgm`, пустой словарь) и возвращает `None` — поиск никогда не падает из-за подсказки.
- **Авто-перестроение словаря** на публикацию — намеренно вне scope (roadmap §6.1).
