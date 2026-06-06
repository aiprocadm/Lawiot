import pytest
from datetime import date
from django.urls import reverse

from documents.models import Redaction
from documents.tests.factories import make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_list_requires_login(client):
    response = client.get(reverse("document_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_list_shows_only_documents_with_published_current_redaction(auth_client):
    published_doc = make_document(slug="published", official_number="1")
    red = make_redaction(published_doc, redaction_date=date(2024, 1, 1))
    red.publish()

    draft_doc = make_document(slug="draft-only", official_number="2")
    make_redaction(draft_doc, redaction_date=date(2024, 1, 1))  # остаётся черновиком

    response = auth_client.get(reverse("document_list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "published" in content or "№ 1" in content
    assert "draft-only" not in content
