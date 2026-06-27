import pytest
from django.urls import reverse

from documents.tests.factories import make_document, make_redaction


@pytest.mark.django_db
def test_document_list_shows_corpus_count(auth_client):
    for i in range(3):
        doc = make_document(slug=f"act-{i}", title=f"Акт {i}", official_number=str(i))
        make_redaction(doc).publish()

    content = auth_client.get(reverse("document_list")).content.decode()
    assert "Всего актов в корпусе: 3" in content
