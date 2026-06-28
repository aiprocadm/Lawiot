"""Lawiot работает только на PostgreSQL (pgvector + полнотекстовый поиск).

Тихий фолбэк на SQLite при пустом DATABASE_URL опасен: на чистом устройстве
`migrate` падал бы на миграции VectorField с непонятной ошибкой. Конфигуратор БД
обязан падать явно и понятно.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings import database_config


def test_empty_database_url_raises_clearly():
    with pytest.raises(ImproperlyConfigured) as exc:
        database_config("")
    assert "DATABASE_URL" in str(exc.value)


def test_postgres_url_is_parsed():
    cfg = database_config("postgres://lawiot:lawiot@localhost:5433/lawiot")
    assert "postgresql" in cfg["ENGINE"]
    assert cfg["NAME"] == "lawiot"


def test_sqlite_is_not_silently_accepted():
    # Даже если кто-то задаст sqlite-URL, мы не должны выдавать рабочий конфиг
    # SQLite-движка: код требует Postgres-возможностей.
    with pytest.raises(ImproperlyConfigured):
        database_config("sqlite:///db.sqlite3")
