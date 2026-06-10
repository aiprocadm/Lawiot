import pytest

from documents.models import Document, Link


@pytest.mark.django_db
def test_deleting_target_preserves_incoming_link_as_raw_citation():
    src = Document.objects.create(
        doc_type="federal_law", title="Источник", official_number="1-ФЗ", slug="1-fz"
    )
    tgt = Document.objects.create(
        doc_type="federal_law", title="Цель", official_number="197-ФЗ", slug="197-fz"
    )
    link = Link.objects.create(from_document=src, to_document=tgt, raw_citation="")
    tgt.delete()
    link.refresh_from_db()  # связь НЕ удалена каскадом
    assert link.to_document_id is None  # обнулена
    assert link.raw_citation == "197-ФЗ"  # цитата сохранена сигналом
