import pytest
from django.urls import reverse

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_print_requires_login(client):
    doc = make_document(slug="tk")
    make_redaction(doc).publish()
    resp = client.get(reverse("document_print", args=["tk"]))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_print_renders_clean_page_with_articles(auth_client):
    doc = make_document(slug="tk", title="Трудовой кодекс")
    red = make_redaction(doc, full_text="")
    make_article(red, number="1", title="Цели", text="цели трудового законодательства")
    red.publish()

    content = auth_client.get(reverse("document_print", args=["tk"])).content.decode()
    assert "Трудовой кодекс" in content
    assert "цели трудового законодательства" in content
    assert "window.print()" in content
    assert "hx-get" not in content  # standalone, без основной htmx-навигации


@pytest.mark.django_db
def test_print_404_without_published_redaction(auth_client):
    make_document(slug="empty")  # опубликованной редакции нет
    resp = auth_client.get(reverse("document_print", args=["empty"]))
    assert resp.status_code == 404
