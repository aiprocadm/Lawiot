from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

# Вежливый идентификатор: внутренний справочник, не агрессивный краулер.
USER_AGENT = "LawiotBot/1.0 (internal legal reference)"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3


@dataclass
class FetchResult:
    content: bytes
    content_type: str
    source_url: str
    fetched_at: datetime


def fetch(url: str, *, client: httpx.Client | None = None) -> FetchResult:
    """Вежливо скачать URL. Сетевой эффект изолирован здесь, чтобы разбор оставался чистым.
    В тестах передаётся `client` с `httpx.MockTransport` — живая сеть не нужна."""
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            transport=httpx.HTTPTransport(retries=MAX_RETRIES),
            follow_redirects=True,
        )
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
