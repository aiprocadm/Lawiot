import datetime

import pytest

from documents.models import Document, Redaction


@pytest.mark.django_db
def test_new_document_defaults_to_federal_official():
    doc = Document.objects.create(slug="d1", doc_type="code", title="Акт")
    assert doc.level == Document.Level.FEDERAL
    assert doc.source_status == Document.SourceStatus.OFFICIAL
    assert doc.region_code == ""


@pytest.mark.django_db
def test_new_redaction_defaults_to_official_text():
    doc = Document.objects.create(slug="d2", doc_type="code", title="Акт")
    red = Redaction.objects.create(document=doc, redaction_date=datetime.date(2020, 1, 1))
    assert red.text_status == Redaction.TextStatus.OFFICIAL
    assert red.get_text_status_display() == "Официальная редакция"
