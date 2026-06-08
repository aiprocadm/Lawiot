import pytest
from django.core.management import call_command

from documents.models import Document


@pytest.mark.django_db
def test_seed_corpus_is_idempotent():
    call_command("seed_corpus")
    first = Document.objects.count()
    assert Document.objects.filter(slug="tk-rf").exists()
    call_command("seed_corpus")  # повтор не плодит дубликаты и не падает
    assert Document.objects.count() == first


@pytest.mark.django_db
def test_seed_corpus_does_not_publish_anything():
    call_command("seed_corpus")
    doc = Document.objects.get(slug="tk-rf")
    assert not doc.redactions.exists()
