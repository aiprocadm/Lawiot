"""Общие pytest-фикстуры для всего проекта.

Идентичная `auth_client` раньше дублировалась в полутора десятках тест-модулей.
Здесь — единственный источник правды. Модули с иной семантикой (другой
пользователь, возврат кортежа ``(user, client)`` и т.п.) определяют собственную
локальную фикстуру, которая по правилам pytest затеняет эту.
"""

import pytest


@pytest.fixture
def auth_client(client, django_user_model):
    """Авторизованный обычный читатель — весь просмотрщик за @login_required."""
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client
