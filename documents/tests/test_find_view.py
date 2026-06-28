import pytest
from django.urls import reverse

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def tk(db):
    doc = make_document(slug="tk", title="ТК")
    red = make_redaction(doc, full_text="")
    make_article(red, number="127", title="Отпуск",
                 text="компенсация за неиспользованный отпуск при увольнении")
    red.publish()
    return doc


@pytest.mark.django_db
def test_find_requires_login(client, tk):
    resp = client.get(reverse("document_search", args=["tk"]))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_find_returns_partial_with_anchor_link(auth_client, tk):
    resp = auth_client.get(reverse("document_search", args=["tk"]), {"q": "компенсация отпуск"})
    content = resp.content.decode()
    assert resp.status_code == 200
    assert 'href="#st-127"' in content
    assert "<!doctype html" not in content.lower()  # партиал, не полная страница


@pytest.mark.django_db
def test_find_without_query_renders_empty_partial(auth_client, tk):
    resp = auth_client.get(reverse("document_search", args=["tk"]))
    assert resp.status_code == 200
    assert "<!doctype html" not in resp.content.decode().lower()


@pytest.mark.django_db
def test_find_no_match_message(auth_client, tk):
    resp = auth_client.get(reverse("document_search", args=["tk"]), {"q": "блокчейнтокен"})
    assert "ничего не найдено" in resp.content.decode().lower()
