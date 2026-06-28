"""Общие pytest-фикстуры для всего проекта.

Идентичные `auth_client` / `auth` раньше дублировались в полутора десятках
тест-модулей. Здесь — единственный источник правды. Модули с иной семантикой
(другой пользователь и т.п.) определяют собственную локальную фикстуру, которая
по правилам pytest затеняет эту.
"""

import pytest


@pytest.fixture
def auth_client(client, django_user_model):
    """Авторизованный обычный читатель — весь просмотрщик за @login_required."""
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.fixture
def auth(client, django_user_model):
    """Как `auth_client`, но возвращает кортеж ``(user, client)`` — для тестов,
    которым нужен сам объект пользователя (bookmarks/history/notes)."""
    user = django_user_model.objects.create_user("r", password="p12345678")
    client.force_login(user)
    return user, client
