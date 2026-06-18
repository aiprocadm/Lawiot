import pytest
from django.db import IntegrityError

from documents.models import Document, PendingAct


@pytest.mark.django_db
def test_partial_unique_eo_number_blocks_duplicates():
    PendingAct.objects.create(
        slug="a-1", title="A", doc_type=Document.DocType.ORDER, eo_number="0001202606090026"
    )
    with pytest.raises(IntegrityError):
        PendingAct.objects.create(
            slug="a-2", title="B", doc_type=Document.DocType.ORDER, eo_number="0001202606090026"
        )


@pytest.mark.django_db
def test_blank_eo_number_allows_many_manual_rows():
    PendingAct.objects.create(slug="m-1", title="M1", doc_type=Document.DocType.ORDER)
    PendingAct.objects.create(slug="m-2", title="M2", doc_type=Document.DocType.ORDER)
    assert PendingAct.objects.filter(eo_number="").count() == 2


@pytest.mark.django_db
def test_discovery_defaults():
    pa = PendingAct.objects.create(slug="d-1", title="D", doc_type=Document.DocType.ORDER)
    assert pa.source == "manual"
    assert pa.resolution_status == "new"
    assert pa.ips_nd == ""
