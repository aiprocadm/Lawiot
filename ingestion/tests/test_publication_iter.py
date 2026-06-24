import json
from pathlib import Path

import httpx

from ingestion.publication import ALLOWED_PAGE_SIZES, FEDERAL_MINTRUD_ID, PAGE_SIZE, iter_documents

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


def test_iter_documents_sends_server_accepted_page_size():
    # Регрессия на дрейф контракта портала (2026-06-24): портал отвергает PageSize не
    # из белого списка 400-ответом. Мок имитирует это — тест падает, если PAGE_SIZE
    # вернут к отвергаемому значению (как прежний 50).
    assert PAGE_SIZE in ALLOWED_PAGE_SIZES

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        size = int(request.url.params.get("PageSize", "0"))
        seen.append(size)
        if size not in ALLOWED_PAGE_SIZES:
            return httpx.Response(
                400, json={"errors": {"PageSize": [f"The value '{size}' is invalid."]}}
            )
        return httpx.Response(200, json=_payload(int(request.url.params.get("Index", "1"))))

    list(iter_documents(FEDERAL_MINTRUD_ID, client=httpx.Client(transport=httpx.MockTransport(handler))))
    assert seen and all(s in ALLOWED_PAGE_SIZES for s in seen)
