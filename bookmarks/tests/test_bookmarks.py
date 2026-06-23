import pytest
from django.urls import reverse

from bookmarks.models import Bookmark
from documents.tests.factories import make_document, make_redaction


@pytest.fixture
def auth(client, django_user_model):
    user = django_user_model.objects.create_user("r", password="p12345678")
    client.force_login(user)
    return user, client


@pytest.mark.django_db
def test_bookmark_list_requires_login(client):
    resp = client.get(reverse("bookmark_list"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_toggle_adds_then_removes(auth):
    user, client = auth
    doc = make_document(slug="tk", title="ТК")
    make_redaction(doc).publish()
    url = reverse("bookmark_toggle", args=["tk"])

    client.post(url, {"next": reverse("bookmark_list")})
    assert Bookmark.objects.filter(user=user, document=doc).exists()

    client.post(url, {"next": reverse("bookmark_list")})
    assert not Bookmark.objects.filter(user=user, document=doc).exists()


@pytest.mark.django_db
def test_toggle_requires_post(auth):
    _, client = auth
    doc = make_document(slug="tk")
    make_redaction(doc).publish()
    resp = client.get(reverse("bookmark_toggle", args=["tk"]))
    assert resp.status_code == 405


@pytest.mark.django_db
def test_list_shows_saved_acts(auth):
    user, client = auth
    doc = make_document(slug="tk", title="Трудовой кодекс")
    make_redaction(doc).publish()
    Bookmark.objects.create(user=user, document=doc)
    assert "Трудовой кодекс" in client.get(reverse("bookmark_list")).content.decode()


@pytest.mark.django_db
def test_document_list_shows_bookmark_state(auth):
    user, client = auth
    doc = make_document(slug="tk", title="ТК")
    make_redaction(doc).publish()
    Bookmark.objects.create(user=user, document=doc)
    assert "★ в избранном" in client.get(reverse("document_list")).content.decode()
