# Lawiot MVP — План 1: Каркас и просмотрщик (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять работающее Django-приложение, где куратор заводит акт через admin, а читатель открывает его страницу с реквизитами, оглавлением, якорями статей и панелями подтверждённых связей.

**Architecture:** Django-монолит + PostgreSQL, всё в Docker compose. Модель данных «Document → Redaction → Article» + «Link». Чтение — серверные шаблоны (Pico.css + HTMX подключены на будущее). Доступ только для залогиненных; роли readers/curators.

**Tech Stack:** Python 3.12, Django 5.2 LTS, PostgreSQL 16, psycopg 3, django-environ, pytest + pytest-django, ruff, Docker Compose, Pico.css/HTMX (CDN).

**Спецификация:** [docs/superpowers/specs/2026-06-05-lawiot-design.md](../specs/2026-06-05-lawiot-design.md)

**Место в дорожной карте:** это **План 1 из 3** (Каркас+просмотрщик → Поиск → Приём данных). Покрывает шаги 1, 2, 3, 5 из §16 спецификации. Поиск (шаг 4) и ингест (6–9) — отдельными планами.

---

## Структура файлов (что создаём в Плане 1)

```
lawiot/
├── pyproject.toml                 # конфиг pytest + ruff (не пакет)
├── Dockerfile                     # образ web
├── docker-compose.yml             # сервисы db + web
├── .env.example                   # пример переменных окружения
├── .gitignore
├── manage.py
├── conftest.py                    # общие pytest-фикстуры
├── config/
│   ├── __init__.py
│   ├── settings.py                # настройки (env-based)
│   ├── urls.py                    # маршруты проекта
│   └── wsgi.py
├── accounts/                      # роли и доступ (миграция-only app)
│   ├── __init__.py
│   ├── apps.py
│   ├── migrations/__init__.py
│   ├── migrations/0001_groups.py  # группы readers/curators
│   └── tests/test_groups.py
├── documents/                     # ядро: модели + просмотрщик
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py                  # Document, Redaction, Article, Link
│   ├── admin.py                   # пульт куратора
│   ├── views.py                   # список + детальная
│   ├── migrations/__init__.py
│   └── tests/
│       ├── __init__.py
│       ├── factories.py           # хелперы создания объектов в тестах
│       ├── test_models.py
│       └── test_views.py
├── templates/
│   ├── base.html
│   ├── registration/login.html
│   └── documents/
│       ├── document_list.html
│       └── document_detail.html
└── static/.gitkeep
```

**Ответственность модулей:**
- `config/` — только конфигурация и маршрутизация.
- `accounts/` — роли доступа (без моделей; группы создаются миграцией).
- `documents/models.py` — доменная модель НПА (4 сущности).
- `documents/admin.py` — интерфейс куратора.
- `documents/views.py` — чтение для читателя.
- `templates/` — представление.

Сущности `RawSource` и `IngestionJob` появятся в Плане 3 (ингест) — здесь они не нужны.

---

## Task 1: Каркас проекта (Django + Postgres + Docker)

**Files:**
- Create: `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`, `manage.py`, `conftest.py`
- Create: `config/__init__.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py`
- Create: `static/.gitkeep`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Создать файлы каркаса**

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
python_files = ["test_*.py", "*_test.py", "tests.py"]
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py312"
```

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN pip install --upgrade pip && pip install \
    "Django>=5.2,<6.0" "psycopg[binary]>=3.2" "django-environ>=0.11" \
    "pytest>=8.0" "pytest-django>=4.8" "ruff>=0.6"
COPY . .
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

`docker-compose.yml`:
```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lawiot
      POSTGRES_USER: lawiot
      POSTGRES_PASSWORD: lawiot
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lawiot"]
      interval: 5s
      timeout: 5s
      retries: 5
  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    environment:
      DATABASE_URL: postgres://lawiot:lawiot@db:5432/lawiot
      SECRET_KEY: dev-insecure-key-change-me
      DEBUG: "True"
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
volumes:
  pgdata:
```

`.env.example`:
```
SECRET_KEY=dev-insecure-key-change-me
DEBUG=True
DATABASE_URL=postgres://lawiot:lawiot@db:5432/lawiot
ALLOWED_HOSTS=localhost,127.0.0.1
```

`.gitignore`:
```
__pycache__/
*.pyc
.env
.pytest_cache/
.ruff_cache/
staticfiles/
```

`manage.py`:
```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

`config/__init__.py`: empty file.

`config/settings.py`:
```python
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-change-me")
DEBUG = env("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "documents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://lawiot:lawiot@db:5432/lawiot",
    ),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "document_list"
LOGOUT_REDIRECT_URL = "login"
```

`config/urls.py`:
```python
from django.contrib import admin
from django.urls import include, path

from documents import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", views.document_list, name="document_list"),
    path("doc/<slug:slug>/", views.document_detail, name="document_detail"),
]
```

`config/wsgi.py`:
```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
```

`static/.gitkeep`: empty file.

`tests/test_smoke.py`:
```python
def test_smoke():
    assert True
```

> Примечание: `config/urls.py` ссылается на `documents.views`, которых ещё нет. Поэтому до Task 8 запускаем только `migrate`/`check` без импорта views — а `check` будет проходить лишь после Task 8. Для Task 1 проверяем БД-подключение и pytest отдельно (шаги ниже). Если хочется зелёный `check` уже сейчас — временно закомментируй две строки `path(...)` с `views` и раскомментируй в Task 8 (это указано там же).

- [ ] **Step 2: Поднять БД и проверить подключение**

Run: `docker compose run --rm web python -c "import django; print(django.get_version())"`
Expected: печатает версию `5.2.x` (образ собрался, Django установлен).

- [ ] **Step 3: Прогнать pytest (харнесс тестов работает)**

Run: `docker compose run --rm web pytest tests/test_smoke.py -v`
Expected: `1 passed`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml Dockerfile docker-compose.yml .env.example .gitignore manage.py conftest.py config static tests
git commit -m "chore: project skeleton (Django + Postgres + Docker)"
```

---

## Task 2: Роли доступа (accounts)

**Files:**
- Create: `accounts/__init__.py`, `accounts/apps.py`, `accounts/migrations/__init__.py`, `accounts/migrations/0001_groups.py`
- Test: `accounts/tests/__init__.py`, `accounts/tests/test_groups.py`

- [ ] **Step 1: Написать падающий тест**

`accounts/tests/__init__.py`: empty file.

`accounts/tests/test_groups.py`:
```python
import pytest
from django.contrib.auth.models import Group


@pytest.mark.django_db
def test_role_groups_exist():
    assert Group.objects.filter(name="readers").exists()
    assert Group.objects.filter(name="curators").exists()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest accounts/tests/test_groups.py -v`
Expected: FAIL — групп нет (миграция ещё не создана) либо приложение `accounts` без миграций.

- [ ] **Step 3: Создать приложение и миграцию групп**

`accounts/__init__.py`: empty file.

`accounts/apps.py`:
```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
```

`accounts/migrations/__init__.py`: empty file.

`accounts/migrations/0001_groups.py`:
```python
from django.db import migrations

ROLE_GROUPS = ["readers", "curators"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLE_GROUPS:
        Group.objects.get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLE_GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [("auth", "0001_initial")]
    operations = [migrations.RunPython(create_groups, remove_groups)]
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `docker compose run --rm web pytest accounts/tests/test_groups.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add accounts
git commit -m "feat(accounts): readers/curators role groups via migration"
```

---

## Task 3: Модель Document

**Files:**
- Create: `documents/__init__.py`, `documents/apps.py`, `documents/models.py`, `documents/migrations/__init__.py`
- Create: `documents/tests/__init__.py`, `documents/tests/factories.py`
- Test: `documents/tests/test_models.py`

- [ ] **Step 1: Написать падающий тест**

`documents/tests/__init__.py`: empty file.

`documents/tests/factories.py`:
```python
from documents.models import Document


def make_document(**kwargs):
    defaults = {
        "doc_type": Document.DocType.CODE,
        "title": "Трудовой кодекс Российской Федерации",
        "official_number": "197-ФЗ",
        "issuing_body": "Федеральное Собрание РФ",
        "status": Document.Status.IN_FORCE,
        "slug": "tk-rf",
    }
    defaults.update(kwargs)
    return Document.objects.create(**defaults)
```

`documents/tests/test_models.py`:
```python
import pytest

from documents.models import Document
from documents.tests.factories import make_document


@pytest.mark.django_db
def test_document_str_contains_type_and_number():
    doc = make_document()
    assert "Кодекс" in str(doc)
    assert "197-ФЗ" in str(doc)


@pytest.mark.django_db
def test_document_slug_is_unique():
    make_document(slug="tk-rf")
    with pytest.raises(Exception):
        make_document(slug="tk-rf", official_number="X")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_models.py -v`
Expected: FAIL — `documents.models` / `Document` не существует.

- [ ] **Step 3: Создать приложение и модель Document**

`documents/__init__.py`: empty file.

`documents/apps.py`:
```python
from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"
```

`documents/migrations/__init__.py`: empty file.

`documents/models.py`:
```python
from django.db import models


class Document(models.Model):
    class DocType(models.TextChoices):
        CODE = "code", "Кодекс"
        FEDERAL_LAW = "federal_law", "Федеральный закон"
        DECREE = "decree", "Постановление"
        ORDER = "order", "Приказ"
        OTHER = "other", "Иное"

    class Status(models.TextChoices):
        IN_FORCE = "in_force", "Действует"
        REPEALED = "repealed", "Утратил силу"
        NOT_IN_FORCE = "not_in_force", "Не вступил в силу"

    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    title = models.TextField()
    official_number = models.CharField(max_length=100, blank=True)
    sign_date = models.DateField(null=True, blank=True)
    issuing_body = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IN_FORCE
    )
    source_url = models.URLField(blank=True)
    official_pub_date = models.DateField(null=True, blank=True)
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return f"{self.get_doc_type_display()} {self.official_number}: {self.title[:60]}"
```

- [ ] **Step 4: Создать и применить миграцию**

Run: `docker compose run --rm web python manage.py makemigrations documents`
Expected: создан `documents/migrations/0001_initial.py`.

Run: `docker compose run --rm web pytest documents/tests/test_models.py -v`
Expected: `2 passed` (pytest-django применяет миграции к тестовой БД).

- [ ] **Step 5: Commit**

```bash
git add documents
git commit -m "feat(documents): Document model"
```

---

## Task 4: Модель Redaction (+ публикация и «текущая редакция»)

**Files:**
- Modify: `documents/models.py` (добавить класс `Redaction`)
- Modify: `documents/tests/factories.py` (добавить `make_redaction`)
- Test: `documents/tests/test_models.py` (добавить тесты)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `documents/tests/factories.py`:
```python
from datetime import date

from documents.models import Redaction


def make_redaction(document=None, **kwargs):
    if document is None:
        document = make_document()
    defaults = {
        "document": document,
        "redaction_date": date(2024, 1, 1),
        "full_text": "Текст редакции.",
        "review_status": Redaction.ReviewStatus.DRAFT,
        "is_current": False,
    }
    defaults.update(kwargs)
    return Redaction.objects.create(**defaults)
```

Добавить в конец `documents/tests/test_models.py`:
```python
from datetime import date

from django.db import IntegrityError, transaction

from documents.models import Redaction
from documents.tests.factories import make_redaction


@pytest.mark.django_db
def test_publish_sets_current_and_unsets_previous():
    doc = make_document()
    first = make_redaction(doc, redaction_date=date(2023, 1, 1))
    first.publish()
    second = make_redaction(doc, redaction_date=date(2024, 1, 1))
    second.publish()

    first.refresh_from_db()
    second.refresh_from_db()
    assert second.is_current is True
    assert second.review_status == Redaction.ReviewStatus.PUBLISHED
    assert first.is_current is False


@pytest.mark.django_db
def test_unique_document_redaction_date():
    doc = make_document()
    make_redaction(doc, redaction_date=date(2024, 1, 1))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_redaction(doc, redaction_date=date(2024, 1, 1))


@pytest.mark.django_db
def test_only_one_current_redaction_per_document():
    doc = make_document()
    make_redaction(doc, redaction_date=date(2023, 1, 1), is_current=True)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_redaction(doc, redaction_date=date(2024, 1, 1), is_current=True)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_models.py -k "redaction or publish or current" -v`
Expected: FAIL — `Redaction` не существует.

- [ ] **Step 3: Добавить модель Redaction**

Добавить в `documents/models.py` (после `Document`):
```python
from django.db import transaction


class Redaction(models.Model):
    class ReviewStatus(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликовано"

    document = models.ForeignKey(
        Document, related_name="redactions", on_delete=models.CASCADE
    )
    redaction_date = models.DateField(help_text="Действует с")
    full_text = models.TextField(blank=True)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.DRAFT
    )
    is_current = models.BooleanField(default=False)
    ingested_at = models.DateTimeField(null=True, blank=True)
    parser_version = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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

    def __str__(self):
        return f"{self.document} — ред. от {self.redaction_date}"

    def publish(self):
        with transaction.atomic():
            Redaction.objects.filter(
                document=self.document, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
            self.review_status = self.ReviewStatus.PUBLISHED
            self.is_current = True
            self.save(update_fields=["review_status", "is_current"])
```

- [ ] **Step 4: Миграция и прогон тестов**

Run: `docker compose run --rm web python manage.py makemigrations documents`
Expected: создан `0002_redaction...py`.

Run: `docker compose run --rm web pytest documents/tests/test_models.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add documents
git commit -m "feat(documents): Redaction with publish() and current-redaction constraints"
```

---

## Task 5: Модель Article (структура + якоря)

**Files:**
- Modify: `documents/models.py` (класс `Article`)
- Modify: `documents/tests/factories.py` (`make_article`)
- Test: `documents/tests/test_models.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `documents/tests/factories.py`:
```python
from documents.models import Article


def make_article(redaction=None, **kwargs):
    if redaction is None:
        redaction = make_redaction()
    defaults = {
        "redaction": redaction,
        "kind": Article.Kind.ARTICLE,
        "number": "81",
        "title": "Расторжение трудового договора",
        "text": "Трудовой договор может быть расторгнут...",
        "order": 1,
    }
    defaults.update(kwargs)
    return Article.objects.create(**defaults)
```

Добавить в конец `documents/tests/test_models.py`:
```python
from documents.models import Article
from documents.tests.factories import make_article


@pytest.mark.django_db
def test_article_anchor_autogenerated_from_number():
    art = make_article(number="81")
    assert art.anchor == "st-81"


@pytest.mark.django_db
def test_article_hierarchy_parent_children():
    red = make_redaction()
    chapter = make_article(
        red, kind=Article.Kind.CHAPTER, number="13", title="Глава 13", order=1
    )
    article = make_article(red, number="81", parent=chapter, order=2)
    assert article.parent == chapter
    assert list(chapter.children.all()) == [article]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_models.py -k article -v`
Expected: FAIL — `Article` не существует.

- [ ] **Step 3: Добавить модель Article**

Добавить импорт в начало `documents/models.py`:
```python
from django.utils.text import slugify
```

Добавить в `documents/models.py` (после `Redaction`):
```python
class Article(models.Model):
    class Kind(models.TextChoices):
        SECTION = "section", "Раздел"
        CHAPTER = "chapter", "Глава"
        ARTICLE = "article", "Статья"

    redaction = models.ForeignKey(
        Redaction, related_name="articles", on_delete=models.CASCADE
    )
    kind = models.CharField(
        max_length=20, choices=Kind.choices, default=Kind.ARTICLE
    )
    number = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=500, blank=True)
    text = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
    )
    anchor = models.SlugField(max_length=100, blank=True)

    _ANCHOR_PREFIX = {"section": "razdel", "chapter": "glava", "article": "st"}

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):
        if not self.anchor and self.number:
            prefix = self._ANCHOR_PREFIX.get(self.kind, "p")
            self.anchor = f"{prefix}-{slugify(self.number)}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}".strip()
```

- [ ] **Step 4: Миграция и прогон тестов**

Run: `docker compose run --rm web python manage.py makemigrations documents`
Expected: создан `0003_article...py`.

Run: `docker compose run --rm web pytest documents/tests/test_models.py -v`
Expected: все passed.

- [ ] **Step 5: Commit**

```bash
git add documents
git commit -m "feat(documents): Article model with hierarchy and auto anchors"
```

---

## Task 6: Модель Link (связи)

**Files:**
- Modify: `documents/models.py` (класс `Link`)
- Modify: `documents/tests/factories.py` (`make_link`)
- Test: `documents/tests/test_models.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `documents/tests/factories.py`:
```python
from documents.models import Link


def make_link(from_document=None, to_document=None, **kwargs):
    if from_document is None:
        from_document = make_document(slug="from-doc", official_number="1")
    defaults = {
        "from_document": from_document,
        "to_document": to_document,
        "link_type": Link.LinkType.REFERENCES,
        "origin": Link.Origin.CURATOR,
        "status": Link.Status.SUGGESTED,
    }
    defaults.update(kwargs)
    return Link.objects.create(**defaults)
```

Добавить в конец `documents/tests/test_models.py`:
```python
from documents.models import Link
from documents.tests.factories import make_link


@pytest.mark.django_db
def test_link_defaults_to_suggested():
    link = make_link()
    assert link.status == Link.Status.SUGGESTED
    assert link.origin == Link.Origin.CURATOR


@pytest.mark.django_db
def test_link_str_uses_target_document_when_present():
    target = make_document(slug="to-doc", official_number="2")
    link = make_link(to_document=target, link_type=Link.LinkType.AMENDS)
    assert "Изменяет" in str(link)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_models.py -k link -v`
Expected: FAIL — `Link` не существует.

- [ ] **Step 3: Добавить модель Link**

Добавить в `documents/models.py` (после `Article`):
```python
class Link(models.Model):
    class LinkType(models.TextChoices):
        REFERENCES = "references", "Ссылается на"
        AMENDS = "amends", "Изменяет"
        AMENDED_BY = "amended_by", "Изменён"

    class Origin(models.TextChoices):
        AUTO = "auto", "Парсер"
        CURATOR = "curator", "Куратор"

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Предложена"
        CONFIRMED = "confirmed", "Подтверждена"

    from_document = models.ForeignKey(
        Document, related_name="outgoing_links", on_delete=models.CASCADE
    )
    from_article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        related_name="outgoing_links",
        on_delete=models.SET_NULL,
    )
    to_document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        related_name="incoming_links",
        on_delete=models.CASCADE,
    )
    to_article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        related_name="incoming_links",
        on_delete=models.SET_NULL,
    )
    raw_citation = models.TextField(blank=True)
    link_type = models.CharField(
        max_length=20, choices=LinkType.choices, default=LinkType.REFERENCES
    )
    origin = models.CharField(
        max_length=20, choices=Origin.choices, default=Origin.CURATOR
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUGGESTED
    )
    context = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        target = self.to_document or self.raw_citation or "—"
        return f"{self.from_document} — {self.get_link_type_display()} → {target}"
```

- [ ] **Step 4: Миграция и прогон тестов**

Run: `docker compose run --rm web python manage.py makemigrations documents`
Expected: создан `0004_link...py`.

Run: `docker compose run --rm web pytest documents/tests/test_models.py -v`
Expected: все passed.

- [ ] **Step 5: Commit**

```bash
git add documents
git commit -m "feat(documents): Link model (typed cross-references)"
```

---

## Task 7: Admin (пульт куратора)

**Files:**
- Create: `documents/admin.py`
- Test: `documents/tests/test_admin.py`

- [ ] **Step 1: Написать падающий тест**

`documents/tests/test_admin.py`:
```python
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_admin_document_changelist_loads_for_superuser(client):
    User = get_user_model()
    admin_user = User.objects.create_superuser("admin", "a@a.ru", "pass12345")
    client.force_login(admin_user)
    response = client.get(reverse("admin:documents_document_changelist"))
    assert response.status_code == 200
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_admin.py -v`
Expected: FAIL — `documents.Document` не зарегистрирован в admin (NoReverseMatch).

- [ ] **Step 3: Зарегистрировать модели в admin**

`documents/admin.py`:
```python
from django.contrib import admin

from documents.models import Article, Document, Link, Redaction


class ArticleInline(admin.TabularInline):
    model = Article
    extra = 0
    fields = ("kind", "number", "title", "order", "parent", "anchor")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "doc_type", "official_number", "status")
    list_filter = ("doc_type", "status")
    search_fields = ("title", "official_number")
    prepopulated_fields = {"slug": ("official_number",)}


@admin.register(Redaction)
class RedactionAdmin(admin.ModelAdmin):
    list_display = ("document", "redaction_date", "review_status", "is_current")
    list_filter = ("review_status", "is_current")
    inlines = [ArticleInline]
    actions = ["publish_selected"]

    @admin.action(description="Опубликовать выбранные редакции")
    def publish_selected(self, request, queryset):
        for redaction in queryset:
            redaction.publish()
        self.message_user(request, f"Опубликовано: {queryset.count()}")


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("from_document", "link_type", "to_document", "status", "origin")
    list_filter = ("link_type", "status", "origin")
    actions = ["confirm_selected"]

    @admin.action(description="Подтвердить выбранные связи")
    def confirm_selected(self, request, queryset):
        updated = queryset.update(status=Link.Status.CONFIRMED)
        self.message_user(request, f"Подтверждено: {updated}")
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `docker compose run --rm web pytest documents/tests/test_admin.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add documents/admin.py documents/tests/test_admin.py
git commit -m "feat(documents): admin curation cockpit (publish/confirm actions)"
```

---

## Task 8: Страница списка актов (только опубликованные)

**Files:**
- Create: `documents/views.py`
- Create: `templates/base.html`, `templates/documents/document_list.html`, `templates/registration/login.html`
- Modify: `config/urls.py` (раскомментировать `views`-маршруты, если комментировал в Task 1)
- Test: `documents/tests/test_views.py`

- [ ] **Step 1: Написать падающие тесты**

`documents/tests/test_views.py`:
```python
import pytest
from datetime import date
from django.urls import reverse

from documents.models import Redaction
from documents.tests.factories import make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_list_requires_login(client):
    response = client.get(reverse("document_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_list_shows_only_documents_with_published_current_redaction(auth_client):
    published_doc = make_document(slug="published", official_number="1")
    red = make_redaction(published_doc, redaction_date=date(2024, 1, 1))
    red.publish()

    draft_doc = make_document(slug="draft-only", official_number="2")
    make_redaction(draft_doc, redaction_date=date(2024, 1, 1))  # остаётся черновиком

    response = auth_client.get(reverse("document_list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "published" in content or "№ 1" in content
    assert "draft-only" not in content
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_views.py -v`
Expected: FAIL — `document_list` view / шаблон отсутствуют.

- [ ] **Step 3: Реализовать view, шаблоны, маршруты**

Если в Task 1 ты комментировал строки с `views` в `config/urls.py` — раскомментируй их сейчас (маршруты `document_list` и `document_detail`).

`documents/views.py`:
```python
from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from documents.models import Document, Link, Redaction


@login_required
def document_list(request):
    current = Redaction.objects.filter(
        document=OuterRef("pk"),
        is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    documents = Document.objects.filter(Exists(current))
    return render(
        request, "documents/document_list.html", {"documents": documents}
    )


@login_required
def document_detail(request, slug):
    document = get_object_or_404(Document, slug=slug)
    redaction = document.redactions.filter(
        is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
    ).first()
    if redaction is None:
        raise Http404("Нет опубликованной редакции")

    articles = redaction.articles.select_related("parent").all()
    outgoing = document.outgoing_links.filter(
        status=Link.Status.CONFIRMED
    ).select_related("to_document")
    incoming = document.incoming_links.filter(
        status=Link.Status.CONFIRMED
    ).select_related("from_document")
    published_redactions = document.redactions.filter(
        review_status=Redaction.ReviewStatus.PUBLISHED
    )

    return render(
        request,
        "documents/document_detail.html",
        {
            "document": document,
            "redaction": redaction,
            "articles": articles,
            "outgoing": outgoing,
            "incoming": incoming,
            "published_redactions": published_redactions,
        },
    )
```

`templates/base.html`:
```html
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Lawiot{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <script src="https://unpkg.com/htmx.org@2.0.2"></script>
</head>
<body>
  <main class="container">
    <nav>
      <ul><li><strong><a href="{% url 'document_list' %}">Lawiot</a></strong></li></ul>
      <ul>
        {% if user.is_authenticated %}
        <li><a href="{% url 'admin:index' %}">Курирование</a></li>
        <li>
          <form method="post" action="{% url 'logout' %}">{% csrf_token %}
            <button type="submit" class="secondary">Выйти</button>
          </form>
        </li>
        {% else %}
        <li><a href="{% url 'login' %}">Войти</a></li>
        {% endif %}
      </ul>
    </nav>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

`templates/documents/document_list.html`:
```html
{% extends "base.html" %}
{% block title %}Акты — Lawiot{% endblock %}
{% block content %}
<h1>Нормативно-правовые акты</h1>
{% if documents %}
<ul>
  {% for doc in documents %}
  <li>
    <a href="{% url 'document_detail' doc.slug %}">{{ doc.title }}</a>
    <small>({{ doc.get_doc_type_display }} № {{ doc.official_number }})</small>
  </li>
  {% endfor %}
</ul>
{% else %}
<p>Опубликованных актов пока нет.</p>
{% endif %}
{% endblock %}
```

`templates/registration/login.html`:
```html
{% extends "base.html" %}
{% block title %}Вход — Lawiot{% endblock %}
{% block content %}
<h1>Вход</h1>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Войти</button>
</form>
{% endblock %}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `docker compose run --rm web pytest documents/tests/test_views.py -v`
Expected: оба теста passed.

- [ ] **Step 5: Commit**

```bash
git add documents/views.py templates config/urls.py documents/tests/test_views.py
git commit -m "feat(documents): document list page (published only, login required)"
```

---

## Task 9: Страница просмотра акта (реквизиты, оглавление, статьи, связи)

**Files:**
- Create: `templates/documents/document_detail.html`
- Test: `documents/tests/test_views.py` (добавить тесты)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `documents/tests/test_views.py`:
```python
from documents.models import Article, Link
from documents.tests.factories import make_article, make_link


@pytest.mark.django_db
def test_detail_shows_requisites_articles_and_confirmed_links(auth_client):
    doc = make_document(slug="tk-rf", official_number="197-ФЗ")
    red = make_redaction(doc, redaction_date=date(2024, 1, 1))
    red.publish()
    make_article(red, number="81", title="Расторжение трудового договора")

    target = make_document(slug="other", official_number="125-ФЗ")
    make_link(
        from_document=doc,
        to_document=target,
        link_type=Link.LinkType.REFERENCES,
        status=Link.Status.CONFIRMED,
    )
    make_link(
        from_document=doc,
        to_document=target,
        link_type=Link.LinkType.AMENDS,
        status=Link.Status.SUGGESTED,  # не должна показываться читателю
    )

    response = auth_client.get(reverse("document_detail", args=["tk-rf"]))
    content = response.content.decode()
    assert response.status_code == 200
    assert "197-ФЗ" in content
    assert "Расторжение трудового договора" in content
    assert "st-81" in content  # якорь статьи
    assert "125-ФЗ" in content  # подтверждённая связь видна
    assert content.count("Ссылается на") >= 1
    assert "Изменяет" not in content  # предложенная связь скрыта


@pytest.mark.django_db
def test_detail_404_when_no_published_redaction(auth_client):
    doc = make_document(slug="draft-only", official_number="X")
    make_redaction(doc, redaction_date=date(2024, 1, 1))  # черновик
    response = auth_client.get(reverse("document_detail", args=["draft-only"]))
    assert response.status_code == 404
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_views.py -k detail -v`
Expected: FAIL — шаблон `document_detail.html` отсутствует (`TemplateDoesNotExist`).

- [ ] **Step 3: Создать шаблон просмотрщика**

`templates/documents/document_detail.html`:
```html
{% extends "base.html" %}
{% block title %}{{ document.title|truncatechars:60 }} — Lawiot{% endblock %}
{% block content %}

<article>
  <header>
    <h1>{{ document.title }}</h1>
    <p>
      <strong>{{ document.get_doc_type_display }}</strong> № {{ document.official_number }}<br>
      Орган: {{ document.issuing_body|default:"—" }}<br>
      Статус: {{ document.get_status_display }}<br>
      Редакция от: {{ redaction.redaction_date }}
    </p>
    {% if published_redactions.count > 1 %}
    <details>
      <summary>Другие редакции ({{ published_redactions.count }})</summary>
      <ul>
        {% for r in published_redactions %}
        <li>Редакция от {{ r.redaction_date }}{% if r.is_current %} — текущая{% endif %}</li>
        {% endfor %}
      </ul>
    </details>
    {% endif %}
  </header>
</article>

<div class="grid">
  <section>
    {% if articles %}
    <h2>Оглавление</h2>
    <ul>
      {% for a in articles %}
      <li><a href="#{{ a.anchor }}">{{ a.get_kind_display }} {{ a.number }}. {{ a.title }}</a></li>
      {% endfor %}
    </ul>

    <h2>Текст</h2>
    {% for a in articles %}
    <section id="{{ a.anchor }}">
      <h3>{{ a.get_kind_display }} {{ a.number }}. {{ a.title }}</h3>
      <p>{{ a.text|linebreaks }}</p>
    </section>
    {% endfor %}
    {% else %}
    <h2>Текст</h2>
    <p>{{ redaction.full_text|linebreaks }}</p>
    {% endif %}
  </section>

  <aside>
    <h3>Изменяющие / изменённые акты</h3>
    <ul>
      {% for link in outgoing %}
        {% if link.link_type == "amends" or link.link_type == "amended_by" %}
        <li>{{ link.get_link_type_display }}:
          {% if link.to_document %}
          <a href="{% url 'document_detail' link.to_document.slug %}">{{ link.to_document.official_number }}</a>
          {% else %}{{ link.raw_citation }}{% endif %}
        </li>
        {% endif %}
      {% endfor %}
    </ul>

    <h3>Ссылается на</h3>
    <ul>
      {% for link in outgoing %}
        {% if link.link_type == "references" %}
        <li>Ссылается на:
          {% if link.to_document %}
          <a href="{% url 'document_detail' link.to_document.slug %}">{{ link.to_document.official_number }}</a>
          {% else %}<span>{{ link.raw_citation }} (вне корпуса)</span>{% endif %}
        </li>
        {% endif %}
      {% endfor %}
    </ul>

    <h3>На него ссылаются</h3>
    <ul>
      {% for link in incoming %}
      <li><a href="{% url 'document_detail' link.from_document.slug %}">{{ link.from_document.official_number }}</a></li>
      {% endfor %}
    </ul>
  </aside>
</div>
{% endblock %}
```

> Примечание по тесту: метка «Ссылается на» в шаблоне выводится буквальной строкой `Ссылается на:` для `references`-связей, а `get_link_type_display` для `amends`/`amended_by` даёт «Изменяет»/«Изменён». Предложенная (suggested) связь типа «Изменяет» во view не передаётся (фильтр `status=CONFIRMED`), поэтому «Изменяет» в выводе отсутствует — что и проверяет тест.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `docker compose run --rm web pytest documents/tests/test_views.py -v`
Expected: все тесты passed.

- [ ] **Step 5: Commit**

```bash
git add templates/documents/document_detail.html documents/tests/test_views.py
git commit -m "feat(documents): document viewer (requisites, TOC, articles, confirmed links)"
```

---

## Task 10: Сквозная проверка и фикстура для ручной приёмки

**Files:**
- Create: `documents/management/__init__.py`, `documents/management/commands/__init__.py`, `documents/management/commands/seed_demo.py`
- Test: `documents/tests/test_seed.py`

- [ ] **Step 1: Написать падающий тест**

`documents/tests/test_seed.py`:
```python
import pytest
from django.core.management import call_command

from documents.models import Document, Redaction


@pytest.mark.django_db
def test_seed_demo_creates_published_document():
    call_command("seed_demo")
    doc = Document.objects.get(slug="tk-rf-demo")
    assert doc.redactions.filter(
        is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
    ).exists()
    assert doc.redactions.first().articles.exists()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `docker compose run --rm web pytest documents/tests/test_seed.py -v`
Expected: FAIL — команда `seed_demo` не найдена.

- [ ] **Step 3: Создать management-команду для демо-данных**

`documents/management/__init__.py`: empty file.
`documents/management/commands/__init__.py`: empty file.

`documents/management/commands/seed_demo.py`:
```python
from datetime import date

from django.core.management.base import BaseCommand

from documents.models import Article, Document, Redaction


class Command(BaseCommand):
    help = "Создаёт демонстрационный акт для ручной приёмки."

    def handle(self, *args, **options):
        doc, _ = Document.objects.get_or_create(
            slug="tk-rf-demo",
            defaults={
                "doc_type": Document.DocType.CODE,
                "title": "Трудовой кодекс Российской Федерации (демо)",
                "official_number": "197-ФЗ",
                "issuing_body": "Федеральное Собрание РФ",
                "status": Document.Status.IN_FORCE,
            },
        )
        redaction, created = Redaction.objects.get_or_create(
            document=doc, redaction_date=date(2024, 1, 1),
            defaults={"full_text": "Демонстрационная редакция."},
        )
        if created:
            Article.objects.create(
                redaction=redaction,
                kind=Article.Kind.ARTICLE,
                number="81",
                title="Расторжение трудового договора по инициативе работодателя",
                text="Трудовой договор может быть расторгнут работодателем в случаях...",
                order=1,
            )
        redaction.publish()
        self.stdout.write(self.style.SUCCESS("Демо-акт создан и опубликован."))
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `docker compose run --rm web pytest documents/tests/test_seed.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Полный прогон + ручная приёмка**

Run: `docker compose run --rm web pytest -v`
Expected: все тесты passed.

Run: `docker compose run --rm web python manage.py migrate`
Run: `docker compose run --rm web python manage.py seed_demo`
Run: `docker compose run --rm web python manage.py createsuperuser` (задать логин/пароль)
Run: `docker compose up`
Открыть `http://localhost:8000/` → войти → увидеть демо-акт в списке → открыть → проверить реквизиты, оглавление, якорь `#st-81`. Открыть `http://localhost:8000/admin/` → убедиться, что куратор может править акт.

- [ ] **Step 6: Commit**

```bash
git add documents/management documents/tests/test_seed.py
git commit -m "feat(documents): seed_demo command + full acceptance pass"
```

---

## Self-Review (выполнено при написании плана)

**1. Покрытие спецификации (План 1 = §16 шаги 1,2,3,5):**
- §5 Модель данных (Document/Redaction/Article/Link) → Tasks 3–6. RawSource/IngestionJob — намеренно в Плане 3 (ингест), здесь не требуются.
- §7 Курирование (admin, publish, confirm) → Task 7.
- §9 Просмотрщик (реквизиты, оглавление, якоря, панели связей, переключатель редакций, только confirmed читателю) → Task 9.
- §10 Авторизация и роли → Task 2 + `login_required` (Tasks 8–9).
- §11 Стек и Docker → Task 1.
- §12 Тестирование (pytest, фикстуры) → во всех задачах; фикстуры в `factories.py`.
- §4 «текущая редакция» (одна на документ, публикация) → Task 4.
- Поиск (§8) и Приём данных (§6) — НЕ в этом плане (Планы 2 и 3). Это явно зафиксировано в шапке.

**2. Плейсхолдеры:** не найдено — каждый шаг содержит полный код/команду.

**3. Согласованность типов/имён:** `Redaction.ReviewStatus.{DRAFT,PUBLISHED}`, `Link.Status.{SUGGESTED,CONFIRMED}`, `Article.Kind.{SECTION,CHAPTER,ARTICLE}`, метод `publish()`, поле `is_current`, якорь `anchor` — используются единообразно во всех задачах (модели → admin → views → шаблоны → тесты). `make_document/redaction/article/link` определены в `factories.py` до первого использования.

---

## Execution Handoff

План сохранён. Дальше — выбор способа исполнения (см. сообщение в чате).
