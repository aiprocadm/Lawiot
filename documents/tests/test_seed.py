import pytest
from django.core.management import call_command

from documents.models import Document, Redaction


@pytest.mark.django_db
def test_seed_demo_creates_published_document():
    call_command("seed_demo")
    doc = Document.objects.get(slug="tk-rf-demo")
    assert doc.redactions.filter(
        is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
    ).exists()
    assert doc.redactions.first().articles.exists()
