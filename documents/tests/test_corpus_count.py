import pytest
from django.urls import reverse

from documents.tests.factories import make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_document_list_shows_corpus_count(auth_client):
    for i in range(3):
        doc = make_document(slug=f"act-{i}", title=f"Акт {i}", official_number=str(i))
        make_redaction(doc).publish()

    content = auth_client.get(reverse("document_list")).content.decode()
    assert "Всего актов в корпусе: 3" in content
