from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

# Вежливый идентификатор: внутренний справочник, не агрессивный краулер.
USER_AGENT = "LawiotBot/1.0 (internal legal reference)"
# Консолидированные кодексы крупные: НК ч.2 ~9 МБ, КоАП ~4.8 МБ. На прежних 30 с
# их чтение не успевало (ReadTimeout в sweep). Тайм-аут — это ПОТОЛОК ожидания, а
# не задержка: мелкие акты возвращаются мгновенно, страдали только гиганты.
DEFAULT_TIMEOUT = 300.0
MAX_RETRIES = 3


@dataclass
class FetchResult:
    content: bytes
    content_type: str
    source_url: str
    fetched_at: datetime


def new_client() -> httpx.Client:
    """Единая фабрика httpx-клиента для всех модулей ingestion.

    Одинаковые тайм-аут/ретраи/редиректы + вежливый User-Agent по умолчанию.
    `fetch()` всё равно проставляет User-Agent на каждый запрос (на случай
    клиента-мока без заголовка), поэтому дефолтный заголовок здесь безвреден и
    лишь упрощает прямые `.get()` в ips_resolve/publication.
    """
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        transport=httpx.HTTPTransport(retries=MAX_RETRIES),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def fetch(url: str, *, client: httpx.Client | None = None) -> FetchResult:
    """Вежливо скачать URL. Сетевой эффект изолирован здесь, чтобы разбор оставался чистым.
    В тестах передаётся `client` с `httpx.MockTransport` — живая сеть не нужна."""
    owns_client = client is None
    if client is None:
        client = new_client()
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return FetchResult(
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            source_url=str(response.url),
            fetched_at=datetime.now(timezone.utc),
        )
    finally:
        if owns_client:
            client.close()
