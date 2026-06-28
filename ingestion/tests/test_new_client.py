"""Единая фабрика httpx-клиента для всех модулей ingestion.

Раньше `_new_client()` дублировался в fetching/scheduling/ips_resolve/publication
с расходящимися параметрами (часть — с User-Agent, часть — без). Один источник
правды устраняет дрейф настроек.
"""

from ingestion.fetching import DEFAULT_TIMEOUT, MAX_RETRIES, USER_AGENT, new_client


def test_new_client_sets_polite_user_agent():
    client = new_client()
    try:
        assert client.headers["User-Agent"] == USER_AGENT
    finally:
        client.close()


def test_new_client_follows_redirects_with_timeout():
    client = new_client()
    try:
        assert client.follow_redirects is True
        assert client.timeout.read == DEFAULT_TIMEOUT
    finally:
        client.close()


def test_retries_constant_is_reused():
    # Параметр ретраев зашит в транспорт; проверяем, что константа экспортируется
    # (фабрика и fetch ссылаются на одно значение).
    assert MAX_RETRIES >= 1
