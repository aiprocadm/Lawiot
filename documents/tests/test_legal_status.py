import pytest

from documents.models import Document, Redaction
from documents.tests.factories import make_document, make_redaction


@pytest.mark.django_db
def test_new_document_defaults_to_federal_official():
    doc = make_document(slug="d1")
    assert doc.level == Document.Level.FEDERAL
    assert doc.source_status == Document.SourceStatus.OFFICIAL
    assert doc.region_code == ""


@pytest.mark.django_db
def test_new_redaction_defaults_to_official_text():
    red = make_redaction(make_document(slug="d2"))
    assert red.text_status == Redaction.TextStatus.OFFICIAL
    assert red.get_text_status_display() == "Официальная редакция"


@pytest.mark.django_db
def test_ingested_draft_marked_official():
    from datetime import date

    from ingestion.parsing import parse_text
    from ingestion.services import create_draft_from_parsed

    doc = make_document(slug="d3")
    parsed = parse_text("Статья 1. Право на труд.", "code")
    red = create_draft_from_parsed(doc, parsed, redaction_date=date(2022, 1, 1))
    assert red.text_status == Redaction.TextStatus.OFFICIAL
