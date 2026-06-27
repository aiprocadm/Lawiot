"""Проверки продакшн-безопасности config/settings.py.

Настройки читают .env и переменные окружения. Чтобы тесты были
детерминированными, мы всегда явно задаём проверяемые переменные через
monkeypatch (env() читает os.environ раньше .env), затем перезагружаем модуль.
"""

import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

import config.settings as settings_mod

INSECURE_DEFAULT_KEY = "dev-insecure-key-change-me"


def _reload(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(settings_mod)


@pytest.fixture(autouse=True)
def _restore_settings(monkeypatch):
    # После каждого теста снять подменённое окружение и вернуть модуль в
    # обычное (тестовое) состояние. undo() до reload — иначе перезагрузка
    # увидит прод-окружение и сработает guard SECRET_KEY.
    yield
    monkeypatch.undo()
    importlib.reload(settings_mod)


def test_production_forces_secure_transport(monkeypatch):
    s = _reload(monkeypatch, DEBUG="False", SECRET_KEY="a-real-production-secret")

    assert s.DEBUG is False
    assert s.SESSION_COOKIE_SECURE is True
    assert s.CSRF_COOKIE_SECURE is True
    assert s.SECURE_SSL_REDIRECT is True
    assert s.SECURE_HSTS_SECONDS >= 31_536_000
    assert s.SECURE_HSTS_INCLUDE_SUBDOMAINS is True


def test_production_rejects_insecure_secret_key(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        _reload(monkeypatch, DEBUG="False", SECRET_KEY=INSECURE_DEFAULT_KEY)


def test_debug_keeps_insecure_default_allowed(monkeypatch):
    # В DEBUG-режиме дефолтный ключ допустим — иначе не запустить локально.
    s = _reload(monkeypatch, DEBUG="True", SECRET_KEY=INSECURE_DEFAULT_KEY)
    assert s.DEBUG is True
    assert s.SESSION_COOKIE_SECURE is False


def test_logging_is_configured(monkeypatch):
    s = _reload(monkeypatch, DEBUG="False", SECRET_KEY="a-real-production-secret")
    assert isinstance(s.LOGGING, dict)
    assert s.LOGGING.get("handlers")
