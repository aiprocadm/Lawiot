# Lawiot MVP — План 2: Поиск (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать читателю страницу поиска: полнотекстовый поиск по корпусу (русская морфология) с фильтрами по реквизитам, ранжированием, подсветкой и переходом прямо к найденной статье.

**Architecture:** Переходим с SQLite на PostgreSQL (контейнер только для БД; Django по-прежнему локальный). Полнотекстовый поиск — на штатном Postgres FTS: `SearchVectorField` + GIN-индекс на `Redaction` (заголовок+текст) и на `Article` (номер/заголовок/текст), вектор обновляется при публикации. Запрос — `websearch_to_tsquery('russian', …)` + фильтры по реквизитам, ранжирование `ts_rank`, сниппеты `ts_headline`. Логика поиска вынесена в приложение `search`.

**Tech Stack:** Python 3.13 (`.venv`), Django 5.2, **PostgreSQL 16** (Docker, host-порт 5433), psycopg 3, `django.contrib.postgres`, pytest + pytest-django, HTMX/Pico.css (CDN).

**Спецификация:** [docs/superpowers/specs/2026-06-05-lawiot-design.md](../specs/2026-06-05-lawiot-design.md) — §8 (Поиск), §16.

**Место в дорожной карте:** **План 2 из 3** (Каркас+просмотрщик → **Поиск** → Приём данных). Реализует §16 шаг 4 и §8 спецификации. Строится поверх Плана 1 (модели Document/Redaction/Article/Link уже влиты в `main`). Ветка: `feature/lawiot-plan-2-search` (создана от `main`).

---

## Окружение исполнения

- Запуск Python — **только** через `.venv\Scripts\python.exe` (bare `python` — зависающая Store-заглушка). Лаунчер `py` для venv.
- **Docker запущен.** Порт 5432 занят другим проектом (`promtech-cabinet-db`), поэтому Lawiot-Postgres слушает **5433**.
- В Плане 1 была SQLite. Здесь переключаемся на Postgres через `DATABASE_URL` в `.env`. Файл `db.sqlite3` больше не используется (можно удалить; он в `.gitignore`).
- Тесты pytest-django создают тестовую БД `test_lawiot` на контейнере; роль `lawiot` — суперпользователь кластера, права на CREATE DATABASE есть.

---

## Структура файлов (План 2)

```
docker-compose.yml                              # NEW — только сервис db (postgres)
.env                                            # NEW/обновить — DATABASE_URL (gitignored)
.env.example                                    # MODIFY — пример DATABASE_URL на 5433
requirements.txt                                # MODIFY — + psycopg[binary]
config/settings.py                              # MODIFY — + django.contrib.postgres, + search
config/urls.py                                  # MODIFY — + маршрут поиска
documents/models.py                             # MODIFY — search_vector на Article/Redaction, publish(), update_search_index()
documents/migrations/0005_search_vectors.py     # NEW — поля + GIN-индексы (makemigrations)
documents/management/commands/reindex_search.py # NEW — переиндексация
documents/tests/test_search_index.py            # NEW — тесты индексации
search/__init__.py                              # NEW app
search/apps.py                                  # NEW
search/services.py                              # NEW — search_documents() + SearchResult
search/forms.py                                 # NEW — SearchForm
search/views.py                                 # NEW — search_view
search/tests/__init__.py                        # NEW
search/tests/test_services.py                   # NEW
search/tests/test_views.py                      # NEW
templates/base.html                             # MODIFY — ссылка «Поиск» в навигации
templates/search/search.html                    # NEW — страница поиска
```

**Ответственность:**
- `documents/models.py` — поля поискового вектора и их поддержка (индексация при публикации). Индекс «живёт» рядом с данными.
- `search/services.py` — чистая функция запроса (без HTTP), легко тестируется.
- `search/forms.py`/`views.py`/`templates` — UI поиска.

---

## Task 1: Переход на PostgreSQL (контейнер только для БД)

**Files:**
- Create: `docker-compose.yml`, `.env`
- Modify: `.env.example`, `requirements.txt`, `config/settings.py`

- [ ] **Step 1: Создать compose-файл и переменные окружения**

`docker-compose.yml`:
```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: lawiot-db
    environment:
      POSTGRES_DB: lawiot
      POSTGRES_USER: lawiot
      POSTGRES_PASSWORD: lawiot
    ports:
      - "5433:5432"
    volumes:
      - lawiot_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lawiot"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  lawiot_pgdata:
```

`.env` (создать в корне; файл в `.gitignore`, в репозиторий не попадёт):
```
SECRET_KEY=dev-insecure-key-change-me
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://lawiot:lawiot@localhost:5433/lawiot
```

Заменить содержимое `.env.example` на:
```
SECRET_KEY=dev-insecure-key-change-me
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
# План 2+: PostgreSQL в контейнере на порту 5433 (см. docker-compose.yml).
DATABASE_URL=postgres://lawiot:lawiot@localhost:5433/lawiot
```

- [ ] **Step 2: Добавить зависимость psycopg и приложение contrib.postgres**

В `requirements.txt` добавить строку:
```
psycopg[binary]>=3.2
```

В `config/settings.py` добавить `"django.contrib.postgres"` в `INSTALLED_APPS` (после `"django.contrib.staticfiles"`):
```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "accounts",
    "documents",
]
```

- [ ] **Step 3: Поднять БД и установить зависимости**

Run:
```powershell
docker compose up -d db
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Expected: контейнер `lawiot-db` поднят (через ~5–10 сек становится healthy); psycopg установлен.

Проверить доступность БД:
Run: `docker compose ps`
Expected: сервис `db` в статусе `running`/`healthy`, порт `0.0.0.0:5433->5432/tcp`.

- [ ] **Step 4: Применить миграции на Postgres и прогнать существующий набор тестов**

Run: `.venv\Scripts\python.exe manage.py migrate`
Expected: все миграции Плана 1 применяются на Postgres без ошибок.

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: **18 passed** (тот же набор, что и на SQLite — это подтверждает корректный переход на Postgres).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example requirements.txt config/settings.py
git commit -m "chore: switch dev/test DB to PostgreSQL (containerized, port 5433)"
```
(Файл `.env` не коммитим — он в `.gitignore`.)

---

## Task 2: Поля поискового вектора (схема)

**Files:**
- Modify: `documents/models.py` (импорты; поле `search_vector` + GIN-индекс на `Article` и `Redaction`)
- Create (via makemigrations): `documents/migrations/0005_search_vectors.py`
- Test: `documents/tests/test_search_index.py`

- [ ] **Step 1: Написать падающий тест (поля существуют и индексируются)**

`documents/tests/test_search_index.py`:
```python
import pytest
from django.contrib.postgres.search import SearchVectorField

from documents.models import Article, Redaction


def test_search_vector_fields_exist():
    assert isinstance(
        Redaction._meta.get_field("search_vector"), SearchVectorField
    )
    assert isinstance(
        Article._meta.get_field("search_vector"), SearchVectorField
    )


@pytest.mark.django_db
def test_no_pending_migrations_for_search_vectors():
    # Schema and migrations are in sync (the field migration exists).
    from io import StringIO
    from django.core.management import call_command

    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_search_index.py -v`
Expected: FAIL — поля `search_vector` ещё нет (`FieldDoesNotExist`); либо `makemigrations --check` сигналит о незакоммиченных изменениях после шага 3.

- [ ] **Step 3: Добавить поля и индексы в модели**

В начало `documents/models.py` добавить импорты:
```python
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
```

В классе `Article` добавить поле сразу после `anchor = models.SlugField(...)`:
```python
    search_vector = SearchVectorField(null=True, editable=False)
```
и заменить его `class Meta` на:
```python
    class Meta:
        ordering = ["order"]
        indexes = [GinIndex(fields=["search_vector"], name="article_search_gin")]
```

В классе `Redaction` добавить поле сразу после `created_at = models.DateTimeField(auto_now_add=True)`:
```python
    search_vector = SearchVectorField(null=True, editable=False)
```
и заменить его `class Meta` на (сохранив существующие constraints):
```python
    class Meta:
        ordering = ["-redaction_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "redaction_date"],
                name="uniq_document_redaction_date",
            ),
            models.UniqueConstraint(
                fields=["document"],
                condition=models.Q(is_current=True),
                name="uniq_current_redaction_per_document",
            ),
        ]
        indexes = [GinIndex(fields=["search_vector"], name="redaction_search_gin")]
```

- [ ] **Step 4: Создать миграцию и прогнать тесты**

Run: `.venv\Scripts\python.exe manage.py makemigrations documents`
Expected: создан `documents/migrations/0005_*.py` (AddField search_vector ×2 + AddIndex ×2). Переименуй файл при желании в `0005_search_vectors.py` не нужно — оставь как сгенерировано.

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_search_index.py -v`
Expected: оба теста passed (`makemigrations --check` не находит изменений).

- [ ] **Step 5: Commit**

```bash
git add documents/models.py documents/migrations documents/tests/test_search_index.py
git commit -m "feat(search): search_vector fields + GIN indexes on Redaction/Article"
```

---

## Task 3: Поддержка индекса (обновление при публикации + переиндексация)

**Files:**
- Modify: `documents/models.py` (импорты; `Redaction.publish()`; новый метод `update_search_index()`)
- Create: `documents/management/commands/reindex_search.py`
- Test: `documents/tests/test_search_index.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `documents/tests/test_search_index.py`:
```python
from django.contrib.postgres.search import SearchQuery

from documents.tests.factories import make_article, make_document, make_redaction


def _matches(model_qs, term):
    q = SearchQuery(term, config="russian", search_type="websearch")
    return model_qs.filter(search_vector=q).exists()


@pytest.mark.django_db
def test_publish_populates_vectors_for_redaction_and_articles():
    doc = make_document(title="О занятости населения")
    red = make_redaction(doc, full_text="пособие по безработице назначается гражданам")
    make_article(red, number="81", title="Расторжение",
                 text="трудовой договор расторгается работодателем")
    red.publish()
    red.refresh_from_db()

    assert red.search_vector is not None
    # redaction vector covers full_text and the document title
    assert _matches(Redaction.objects.filter(pk=red.pk), "безработице")
    assert _matches(Redaction.objects.filter(pk=red.pk), "занятости")
    # article vector covers article text
    assert _matches(Article.objects.filter(redaction=red), "работодателем")


@pytest.mark.django_db
def test_reindex_search_backfills_vectors():
    doc = make_document(title="Тест", slug="t1")
    red = make_redaction(doc, full_text="особоеслово для поиска")
    red.publish()
    # simulate stale index
    Redaction.objects.filter(pk=red.pk).update(search_vector=None)
    assert not _matches(Redaction.objects.filter(pk=red.pk), "особоеслово")

    from django.core.management import call_command
    call_command("reindex_search")

    assert _matches(Redaction.objects.filter(pk=red.pk), "особоеслово")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_search_index.py -k "publish_populates or reindex" -v`
Expected: FAIL — `publish()` пока не заполняет вектор; команды `reindex_search` нет.

- [ ] **Step 3: Реализовать обновление вектора и команду переиндексации**

В начало `documents/models.py` добавить импорты:
```python
from django.contrib.postgres.search import SearchVector
from django.db.models import Value
```

В классе `Redaction` заменить метод `publish` на следующий и добавить метод `update_search_index`:
```python
    def publish(self):
        with transaction.atomic():
            Redaction.objects.filter(
                document=self.document, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
            self.review_status = self.ReviewStatus.PUBLISHED
            self.is_current = True
            self.save(update_fields=["review_status", "is_current"])
            self.update_search_index()

    def update_search_index(self):
        Redaction.objects.filter(pk=self.pk).update(
            search_vector=(
                SearchVector(Value(self.document.title), weight="A", config="russian")
                + SearchVector("full_text", weight="B", config="russian")
            )
        )
        Article.objects.filter(redaction=self).update(
            search_vector=(
                SearchVector("number", weight="A", config="russian")
                + SearchVector("title", weight="A", config="russian")
                + SearchVector("text", weight="B", config="russian")
            )
        )
```

`documents/management/commands/reindex_search.py`:
```python
from django.core.management.base import BaseCommand

from documents.models import Redaction


class Command(BaseCommand):
    help = "Пересобирает поисковые векторы для всех опубликованных редакций."

    def handle(self, *args, **options):
        published = Redaction.objects.filter(
            review_status=Redaction.ReviewStatus.PUBLISHED
        ).select_related("document")
        count = 0
        for redaction in published:
            redaction.update_search_index()
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Переиндексировано редакций: {count}"))
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest documents/tests/test_search_index.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add documents/models.py documents/management/commands/reindex_search.py documents/tests/test_search_index.py
git commit -m "feat(search): populate vectors on publish + reindex_search command"
```

---

## Task 4: Сервис поиска (ядро запроса)

**Files:**
- Create: `search/__init__.py`, `search/apps.py`, `search/services.py`
- Create: `search/tests/__init__.py`, `search/tests/test_services.py`
- Modify: `config/settings.py` (добавить `"search"` в `INSTALLED_APPS`)

- [ ] **Step 1: Написать падающие тесты**

`search/__init__.py`: empty file.
`search/tests/__init__.py`: empty file.

`search/tests/test_services.py`:
```python
import pytest

from documents.models import Document
from documents.tests.factories import make_article, make_document, make_redaction
from search.services import search_documents


@pytest.mark.django_db
def test_finds_document_by_full_text():
    doc = make_document(slug="zan", title="О занятости")
    make_redaction(doc, full_text="пособие по безработице гражданам").publish()
    results = search_documents("безработице")
    assert len(results) == 1
    assert results[0].document == doc
    assert results[0].article_anchor is None
    assert "<mark>" in results[0].snippet


@pytest.mark.django_db
def test_finds_article_and_returns_anchor():
    doc = make_document(slug="tk", title="Трудовой кодекс")
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение",
                 text="увольнение работника работодателем")
    red.publish()
    results = search_documents("работодателем")
    assert len(results) == 1
    assert results[0].document == doc
    assert results[0].article_anchor == "st-81"
    assert "81" in results[0].article_label


@pytest.mark.django_db
def test_filters_by_doc_type():
    law = make_document(slug="law", title="Закон",
                        doc_type=Document.DocType.FEDERAL_LAW)
    make_redaction(law, full_text="общийтермин в законе").publish()
    order = make_document(slug="ord", title="Приказ",
                          doc_type=Document.DocType.ORDER)
    make_redaction(order, full_text="общийтермин в приказе").publish()

    results = search_documents("общийтермин", doc_type=Document.DocType.FEDERAL_LAW)
    assert {r.document for r in results} == {law}


@pytest.mark.django_db
def test_drafts_are_not_searched():
    doc = make_document(slug="d", title="Черновик")
    make_redaction(doc, full_text="секретноеслово")  # not published
    assert search_documents("секретноеслово") == []


@pytest.mark.django_db
def test_empty_query_returns_empty():
    assert search_documents("") == []
    assert search_documents("   ") == []
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest search/tests/test_services.py -v`
Expected: FAIL — модуля `search.services` нет.

- [ ] **Step 3: Реализовать приложение и сервис**

Добавить `"search"` в `INSTALLED_APPS` (`config/settings.py`), после `"documents"`:
```python
    "accounts",
    "documents",
    "search",
]
```

`search/apps.py`:
```python
from django.apps import AppConfig


class SearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "search"
```

`search/services.py`:
```python
from dataclasses import dataclass

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import F

from documents.models import Article, Document, Redaction


@dataclass
class SearchResult:
    document: Document
    rank: float
    snippet: str
    article_anchor: str | None = None
    article_label: str | None = None


def _headline(field, query):
    return SearchHeadline(
        field, query, config="russian", start_sel="<mark>", stop_sel="</mark>"
    )


def search_documents(
    query_text,
    *,
    doc_type="",
    status="",
    issuing_body="",
    date_from=None,
    date_to=None,
):
    query_text = (query_text or "").strip()
    if not query_text:
        return []

    query = SearchQuery(query_text, config="russian", search_type="websearch")

    def apply_doc_filters(qs, prefix):
        if doc_type:
            qs = qs.filter(**{f"{prefix}doc_type": doc_type})
        if status:
            qs = qs.filter(**{f"{prefix}status": status})
        if issuing_body:
            qs = qs.filter(**{f"{prefix}issuing_body__icontains": issuing_body})
        if date_from:
            qs = qs.filter(**{f"{prefix}sign_date__gte": date_from})
        if date_to:
            qs = qs.filter(**{f"{prefix}sign_date__lte": date_to})
        return qs

    redaction_hits = apply_doc_filters(
        Redaction.objects.filter(
            is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .annotate(snippet=_headline("full_text", query))
        .select_related("document"),
        "document__",
    )

    article_hits = apply_doc_filters(
        Article.objects.filter(
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .annotate(snippet=_headline("text", query))
        .select_related("redaction__document"),
        "redaction__document__",
    )

    best: dict[int, SearchResult] = {}
    for r in redaction_hits:
        existing = best.get(r.document_id)
        if existing is None or r.rank > existing.rank:
            best[r.document_id] = SearchResult(
                document=r.document, rank=r.rank, snippet=r.snippet
            )
    for a in article_hits:
        doc = a.redaction.document
        existing = best.get(doc.id)
        if existing is None or a.rank > existing.rank:
            best[doc.id] = SearchResult(
                document=doc,
                rank=a.rank,
                snippet=a.snippet,
                article_anchor=a.anchor,
                article_label=f"{a.get_kind_display()} {a.number}",
            )

    return sorted(best.values(), key=lambda x: x.rank, reverse=True)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest search/tests/test_services.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add search/__init__.py search/apps.py search/services.py search/tests config/settings.py
git commit -m "feat(search): search_documents service (FTS + filters + ranking)"
```

---

## Task 5: UI поиска (форма + view + маршрут + шаблон)

**Files:**
- Create: `search/forms.py`, `search/views.py`, `templates/search/search.html`
- Create: `search/tests/test_views.py`
- Modify: `config/urls.py` (маршрут `search`), `templates/base.html` (ссылка «Поиск»)

- [ ] **Step 1: Написать падающие тесты**

`search/tests/test_views.py`:
```python
import pytest
from django.urls import reverse

from documents.models import Document
from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_search_requires_login(client):
    response = client.get(reverse("search"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_search_returns_results_with_highlight_and_link(auth_client):
    doc = make_document(slug="tk", title="Трудовой кодекс", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение",
                 text="увольнение работника работодателем")
    red.publish()

    response = auth_client.get(reverse("search"), {"q": "работодателем"})
    content = response.content.decode()
    assert response.status_code == 200
    assert "Трудовой кодекс" in content
    assert "<mark>" in content                 # подсветка
    assert "/doc/tk/#st-81" in content          # deep-link в статью


@pytest.mark.django_db
def test_search_filter_by_doc_type(auth_client):
    law = make_document(slug="law", title="Закон-про-отпуск",
                        doc_type=Document.DocType.FEDERAL_LAW)
    make_redaction(law, full_text="отпускслово").publish()
    order = make_document(slug="ord", title="Приказ-про-отпуск",
                          doc_type=Document.DocType.ORDER)
    make_redaction(order, full_text="отпускслово").publish()

    response = auth_client.get(
        reverse("search"), {"q": "отпускслово", "doc_type": "federal_law"}
    )
    content = response.content.decode()
    assert "Закон-про-отпуск" in content
    assert "Приказ-про-отпуск" not in content
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest search/tests/test_views.py -v`
Expected: FAIL — маршрута `search`/view/шаблона нет.

- [ ] **Step 3: Реализовать форму, view, маршрут, шаблон, навигацию**

`search/forms.py`:
```python
from django import forms

from documents.models import Document


class SearchForm(forms.Form):
    q = forms.CharField(label="Запрос", required=False)
    doc_type = forms.ChoiceField(
        label="Тип", required=False,
        choices=[("", "Все типы")] + list(Document.DocType.choices),
    )
    status = forms.ChoiceField(
        label="Статус", required=False,
        choices=[("", "Любой статус")] + list(Document.Status.choices),
    )
    issuing_body = forms.CharField(label="Орган", required=False)
    date_from = forms.DateField(
        label="Дата с", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label="Дата по", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
```

`search/views.py`:
```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from search.forms import SearchForm
from search.services import search_documents


@login_required
def search_view(request):
    form = SearchForm(request.GET or None)
    results = []
    if form.is_valid() and form.cleaned_data.get("q"):
        cd = form.cleaned_data
        results = search_documents(
            cd["q"],
            doc_type=cd["doc_type"],
            status=cd["status"],
            issuing_body=cd["issuing_body"],
            date_from=cd["date_from"],
            date_to=cd["date_to"],
        )
    return render(
        request,
        "search/search.html",
        {"form": form, "results": results, "query": request.GET.get("q", "")},
    )
```

Modify `config/urls.py` — добавить импорт view поиска и маршрут:
```python
from django.contrib import admin
from django.urls import include, path

from documents import views
from search import views as search_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", views.document_list, name="document_list"),
    path("search/", search_views.search_view, name="search"),
    path("doc/<slug:slug>/", views.document_detail, name="document_detail"),
]
```

`templates/search/search.html`:
```html
{% extends "base.html" %}
{% block title %}Поиск — Lawiot{% endblock %}
{% block content %}
<h1>Поиск по актам</h1>

<form method="get" role="search">
  <input type="search" name="q" value="{{ query }}" placeholder="Введите запрос…" aria-label="Запрос">
  <details>
    <summary>Фильтры</summary>
    <div class="grid">
      <label>Тип {{ form.doc_type }}</label>
      <label>Статус {{ form.status }}</label>
      <label>Орган {{ form.issuing_body }}</label>
    </div>
    <div class="grid">
      <label>Дата с {{ form.date_from }}</label>
      <label>Дата по {{ form.date_to }}</label>
    </div>
  </details>
  <button type="submit">Найти</button>
</form>

{% if query %}
<p>Найдено: {{ results|length }} по запросу «{{ query }}».</p>
{% for r in results %}
<article>
  <h3>
    <a href="{% url 'document_detail' r.document.slug %}{% if r.article_anchor %}#{{ r.article_anchor }}{% endif %}">
      {{ r.document.title }}{% if r.article_label %} — {{ r.article_label }}{% endif %}
    </a>
  </h3>
  <small>{{ r.document.get_doc_type_display }} № {{ r.document.official_number }} · {{ r.document.get_status_display }}</small>
  <p>{{ r.snippet|safe }}</p>
</article>
{% empty %}
<p>Ничего не найдено.</p>
{% endfor %}
{% endif %}
{% endblock %}
```

Modify `templates/base.html` — заменить блок навигации (правый `<ul>`) так, чтобы добавить ссылку «Поиск» для залогиненных:
```html
      <ul>
        {% if user.is_authenticated %}
        <li><a href="{% url 'search' %}">Поиск</a></li>
        {% if user.is_staff %}<li><a href="{% url 'admin:index' %}">Курирование</a></li>{% endif %}
        <li>
          <form method="post" action="{% url 'logout' %}">{% csrf_token %}
            <button type="submit" class="secondary">Выйти</button>
          </form>
        </li>
        {% else %}
        <li><a href="{% url 'login' %}">Войти</a></li>
        {% endif %}
      </ul>
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv\Scripts\python.exe -m pytest search/tests/test_views.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add search/forms.py search/views.py templates/search/search.html search/tests/test_views.py config/urls.py templates/base.html
git commit -m "feat(search): search page (form, filters, highlighted results, article deep-links)"
```

---

## Task 6: Сквозная проверка и приёмка

**Files:**
- Test: запуск полного набора; ручная приёмка.

- [ ] **Step 1: Полный прогон тестов**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: все тесты passed (Plan 1 + Plan 2; ~30+).

- [ ] **Step 2: Django system check**

Run: `.venv\Scripts\python.exe manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 3: Переиндексировать демо-данные и проверить руками**

Run:
```powershell
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_demo
.venv\Scripts\python.exe manage.py reindex_search
```
Expected: демо-акт создан/опубликован; «Переиндексировано редакций: 1» (или больше).

Затем (интерактивно — для человека, субагент это НЕ запускает):
```powershell
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver
```
Открыть `http://localhost:8000/search/` → войти → ввести запрос (например, «расторжение» или «работодателем») → увидеть демо-акт в результатах с подсветкой и ссылкой на статью; проверить фильтры. Ctrl+C — остановить сервер.

- [ ] **Step 4: Commit (если остались незакоммиченные изменения)**

```bash
git status
# при необходимости:
git add -A && git commit -m "test(search): full acceptance pass for Plan 2"
```

---

## Self-Review (выполнено при написании плана)

**1. Покрытие спецификации (§8 Поиск):**
- Postgres FTS, конфигурация `russian` → Tasks 1–4 (`config="russian"` везде).
- `SearchVectorField` + GIN на Redaction и Article → Task 2.
- Вектор обновляется при публикации → Task 3 (`publish()` → `update_search_index()`), + `reindex_search` для бэкафилла.
- `websearch_to_tsquery` + фильтры по реквизитам → Task 4 (`SearchQuery(search_type="websearch")`, `apply_doc_filters`).
- Ранжирование `ts_rank` → `SearchRank`; сниппеты `ts_headline` → `SearchHeadline`.
- Совпадение в статье → deep-link к статье → `SearchResult.article_anchor` + шаблон `#{{ anchor }}`.
- Только опубликованные текущие редакции → фильтры `is_current=True, review_status=PUBLISHED` в сервисе.
- Логин обязателен → `@login_required` на `search_view` (Task 5).
- Масштаб v1: слияние двух выборок в Python — допустимо для небольшого корпуса (отмечено).

**2. Плейсхолдеры:** не найдено — везде полный код/команды.

**3. Согласованность имён/типов:**
- `search_documents(query_text, *, doc_type, status, issuing_body, date_from, date_to)` — одинаково в сервисе (Task 4) и во view (Task 5).
- `SearchResult(document, rank, snippet, article_anchor, article_label)` — поля совпадают в сервисе и шаблоне.
- `update_search_index()` — определён в Task 3, вызывается в `publish()` и в `reindex_search` (Task 3).
- `config="russian"`, селекторы `<mark>`/`</mark>` — едины в сервисе и в тестах/шаблоне.
- Маршрут `name="search"` — определён в Task 5, используется в тестах и `base.html`.

**Известные ограничения v1 (для будущих планов, не блокеры):**
- Вектор не пересобирается при ручном редактировании текста статьи в admin без повторной публикации — лечится `reindex_search` или повторной публикацией; в Плане 3 можно добавить сигнал.
- Слияние результатов в Python (без БД-пагинации) — ок для небольшого корпуса; при росте переедем на единый SQL-`UNION`/материализованное представление.
- Фильтр по дате применяется к `sign_date` документа.

---

## Execution Handoff

План сохранён. Способ исполнения выбирается в чате (рекомендуется субагентами — как в Плане 1).
