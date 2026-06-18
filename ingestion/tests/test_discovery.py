import json
from pathlib import Path

import httpx
import pytest

from documents.models import Document, PendingAct
from ingestion.discovery import DiscoverySummary, discover

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures_raw" / "publication_mintrud_page1.json"


def _one_page_client():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["pagesTotalCount"] = 1

    def handler(request):
        return httpx.Response(200, json=data)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_discover_creates_pending_acts():
    summary = discover(["auth-1"], client=_one_page_client())
    assert isinstance(summary, DiscoverySummary)
    assert summary.created == 2
    pa = PendingAct.objects.get(eo_number="0001202606090026")
    assert pa.official_number == "200н"
    assert pa.doc_type == Document.DocType.ORDER
    assert pa.source == PendingAct.Source.AUTO
    assert pa.publication_url.endswith("eoNumber=0001202606090026")


@pytest.mark.django_db
def test_discover_is_idempotent():
    discover(["auth-1"], client=_one_page_client())
    summary = discover(["auth-1"], client=_one_page_client())
    assert summary.created == 0
    assert summary.skipped == 2
    assert PendingAct.objects.count() == 2


@pytest.mark.django_db
def test_discover_skips_already_in_corpus(monkeypatch):
    # Если акт уже в корпусе (is_resolved=True), PendingAct не создаём.
    monkeypatch.setattr(PendingAct, "is_resolved", property(lambda self: True))
    summary = discover(["auth-1"], client=_one_page_client())
    assert summary.created == 0
    assert summary.skipped == 2
    assert PendingAct.objects.count() == 0


@pytest.mark.django_db
def test_discover_isolates_failing_document(monkeypatch):
    # Сбой _upsert на одном документе не должен оборвать обход остальных.
    import ingestion.discovery as disc

    real_upsert = disc._upsert
    seen = {"n": 0}

    def flaky(doc):
        seen["n"] += 1
        if seen["n"] == 1:
            raise RuntimeError("boom")
        return real_upsert(doc)

    monkeypatch.setattr(disc, "_upsert", flaky)
    summary = discover(["auth-1"], client=_one_page_client())
    assert summary.failed == 1
    assert summary.created == 1  # второй документ всё равно обработан
    assert PendingAct.objects.count() == 1
