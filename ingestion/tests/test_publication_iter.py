import json
from pathlib import Path

import httpx

from ingestion.publication import FEDERAL_MINTRUD_ID, iter_documents

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures_raw" / "publication_mintrud_page1.json"


def _payload(index):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # Делаем «двухстраничный» источник: стр.1 = items фикстуры, стр.2 — пусто.
    data["pagesTotalCount"] = 2
    if index >= 2:
        data["items"] = []
    return data


def _client(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        index = int(request.url.params.get("Index", "1"))
        calls.append(index)
        return httpx.Response(200, json=_payload(index))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_iter_documents_walks_pages_until_empty():
    calls = []
    docs = list(iter_documents(FEDERAL_MINTRUD_ID, client=_client(calls)))
    assert [d.number for d in docs] == ["200н", "193н"]
    assert calls == [1, 2]  # дошёл до пустой второй страницы и остановился


def test_iter_documents_respects_max_pages():
    calls = []
    list(iter_documents(FEDERAL_MINTRUD_ID, client=_client(calls), max_pages=1))
    assert calls == [1]  # дальше первой страницы не пошёл
