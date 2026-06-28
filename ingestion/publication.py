import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from ingestion.fetching import managed_client

# ВНИМАНИЕ: http (не https) — намеренно. Портал не обслуживает TLS: проверено
# 2026-06-29 (http → 200, https → отказ соединения). Менять на https нельзя —
# сломается ингест. См. также IPS_BASE в ingestion/ips_resolve.py.
PUBLICATION_BASE = "http://publication.pravo.gov.ru"
# Федеральный Минтруд (signatoryAuthorityId портала опубликования).
FEDERAL_MINTRUD_ID = "2c4929b0-9323-4541-9705-76185b9e284b"

# GUID типов документа портала → значения Document.DocType (строки, без импорта
# модели — клиент остаётся свободным от Django; значения совпадают с DocType).
DOC_TYPE_BY_GUID = {
    "2dddb344-d3e2-4785-a899-7aa12bd47b6f": "order",  # Приказ
    "fd5a8766-f6fd-4ac2-8fd9-66f414d314ac": "decree",  # Постановление
}

# Портал валидирует PageSize по белому списку и отвергает чужие значения 400-ответом.
# Проверено вживую 2026-06-24: 30 и 100 принимаются, 20 и 50 → 400 (контракт менялся —
# прежние 10|20|50 больше не действуют; дефолт портала itemsPerPage=30).
ALLOWED_PAGE_SIZES = frozenset({30, 100})
PAGE_SIZE = 30


def doc_type_for(guid: str) -> str:
    return DOC_TYPE_BY_GUID.get(guid, "other")


@dataclass
class PublicationDoc:
    eo_number: str
    number: str
    name: str
    complex_name: str
    document_date: date | None
    signatory_authority_id: str
    document_type_id: str
    doc_type: str
    pages_count: int
    reg_number: str
    pdf_url: str


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def parse_item(item: dict) -> PublicationDoc:
    eo = item.get("eoNumber", "")
    type_id = item.get("documentTypeId", "")
    return PublicationDoc(
        eo_number=eo,
        number=item.get("number", ""),
        name=item.get("name", ""),
        complex_name=item.get("complexName", ""),
        document_date=_to_date(item.get("documentDate")),
        signatory_authority_id=item.get("signatoryAuthorityId", ""),
        document_type_id=type_id,
        doc_type=doc_type_for(type_id),
        pages_count=item.get("pagesCount") or 0,
        reg_number=item.get("jdRegNumber", "") or "",
        pdf_url=f"{PUBLICATION_BASE}/file/pdf?eoNumber={eo}",
    )


def iter_documents(
    authority_id: str,
    *,
    client: httpx.Client | None = None,
    since_date: date | None = None,
    max_pages: int | None = None,
) -> Iterator[PublicationDoc]:
    """Перебрать опубликованные акты органа постранично (новые сверху).

    since_date: если задан — остановиться, как только встретился акт старше даты
    (портал отдаёт по убыванию даты публикации). max_pages: предохранитель.
    Сеть изолирована здесь; в тестах передаётся client с httpx.MockTransport.
    """
    with managed_client(client) as client:
        index = 1
        while True:
            resp = client.get(
                f"{PUBLICATION_BASE}/api/Documents",
                params={
                    "SignatoryAuthorityId": authority_id,
                    "PageSize": PAGE_SIZE,
                    "Index": index,
                },
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                # Дрейф контракта: 200 OK, но тело — не JSON (HTML-заглушка прокси
                # или портала). Чёткое доменное сообщение вместо голого
                # JSONDecodeError в логе discovery (там это считается сбоем органа).
                raise RuntimeError(
                    f"портал опубликования вернул не-JSON "
                    f"(authority_id={authority_id}, страница {index})"
                ) from exc
            items = data.get("items") or []
            if not items:
                return
            for raw in items:
                doc = parse_item(raw)
                if since_date and doc.document_date and doc.document_date < since_date:
                    return
                yield doc
            if index >= (data.get("pagesTotalCount") or index):
                return
            if max_pages is not None and index >= max_pages:
                return
            index += 1
