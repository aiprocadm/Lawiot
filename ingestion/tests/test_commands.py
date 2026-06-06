from datetime import datetime, timezone

import pytest
from django.core.management import call_command

from documents.models import Redaction
from documents.tests.factories import make_document
from ingestion.fetching import FetchResult


@pytest.mark.django_db
def test_ingest_url_command_creates_draft(monkeypatch):
    doc = make_document(slug="tkurl", official_number="1")
    from ingestion import services

    def fake_fetch(url, client=None):
        return FetchResult(
            content="Статья 1. Тест\nтело".encode("utf-8"),
            content_type="text/html",
            source_url=url,
            fetched_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(services, "fetch", fake_fetch)
    call_command("ingest_url", "--slug", "tkurl", "--url", "https://e.test/d")
    red = Redaction.objects.get(document=doc)
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.articles.get().number == "1"


@pytest.mark.django_db
def test_ingest_url_command_unknown_slug_errors():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("ingest_url", "--slug", "nope", "--url", "https://e.test/d")


@pytest.mark.django_db
def test_ingest_url_command_exits_nonzero_on_failed_job(monkeypatch):
    import httpx
    from django.core.management.base import CommandError

    make_document(slug="tkfail", official_number="9")
    from ingestion import services

    def boom(url, client=None):
        raise httpx.HTTPStatusError(
            "500", request=httpx.Request("GET", url), response=httpx.Response(500)
        )

    monkeypatch.setattr(services, "fetch", boom)
    # ingest_target catches the error into a FAILED job; the command must surface it
    # as a non-zero exit (CommandError), not a silent success.
    with pytest.raises(CommandError):
        call_command("ingest_url", "--slug", "tkfail", "--url", "https://e.test/d")


@pytest.mark.django_db
def test_import_document_command_creates_draft(tmp_path):
    doc = make_document(slug="tkfile", official_number="2")
    f = tmp_path / "act.txt"
    f.write_text("Статья 1. Общие положения\nНастоящий акт регулирует.", encoding="utf-8")
    call_command("import_document", "--slug", "tkfile", "--file", str(f))
    red = Redaction.objects.get(document=doc)
    assert red.articles.get().number == "1"


@pytest.mark.django_db
def test_extract_links_command_processes_current_redactions():
    from documents.models import Link
    from documents.tests.factories import make_redaction

    src = make_document(slug="cmd-src", official_number="197-ФЗ")
    make_document(slug="cmd-tgt", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Связано с 125-ФЗ.")
    red.publish()  # становится текущей
    call_command("extract_links")
    assert Link.objects.filter(from_document=src, status=Link.Status.SUGGESTED).exists()
