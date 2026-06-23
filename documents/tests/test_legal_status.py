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
