import pytest

from documents.admin import bind_to_ips
from documents.models import Document, PendingAct


@pytest.mark.django_db
def test_bind_to_ips_creates_auto_ingest_document():
    act = PendingAct.objects.create(
        slug="prikaz-320n-eo1",
        title="Об утверждении формы трудовых книжек",
        official_number="320н",
        doc_type=Document.DocType.ORDER,
        eo_number="0001202106020001",
        ips_nd="102074279",
        issuing_body="Минтруд России",
    )
    bind_to_ips(None, None, PendingAct.objects.filter(pk=act.pk))
    doc = Document.objects.get(slug="prikaz-320n-eo1")
    assert doc.doc_type == Document.DocType.ORDER
    assert doc.official_number == "320н"
    assert doc.auto_ingest is True
    assert doc.auto_publish is False
    assert "nd=102074279" in doc.source_url
    act.refresh_from_db()
    assert act.resolution_status == PendingAct.ResolutionStatus.BOUND


@pytest.mark.django_db
def test_bind_to_ips_skips_without_nd():
    act = PendingAct.objects.create(
        slug="no-nd", title="Без nd", doc_type=Document.DocType.ORDER
    )
    bind_to_ips(None, None, PendingAct.objects.filter(pk=act.pk))
    assert not Document.objects.filter(slug="no-nd").exists()
    act.refresh_from_db()
    assert act.resolution_status == PendingAct.ResolutionStatus.NEW
