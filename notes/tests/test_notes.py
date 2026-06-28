import pytest
from django.urls import reverse

from documents.tests.factories import make_document
from notes.models import Note


@pytest.mark.django_db
def test_notes_requires_login(client):
    resp = client.get(reverse("note_list"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_create_note(auth):
    user, client = auth
    doc = make_document(slug="tk", title="ТК")
    resp = client.post(
        reverse("note_list"),
        {"document": doc.id, "article_number": "81", "text": "моя заметка"},
    )
    assert resp.status_code == 302
    note = Note.objects.get(user=user)
    assert note.text == "моя заметка"
    assert note.document == doc
    assert note.article_number == "81"


@pytest.mark.django_db
def test_list_shows_own_notes_only(auth, django_user_model):
    user, client = auth
    doc = make_document(slug="tk", title="Трудовой кодекс")
    Note.objects.create(user=user, document=doc, text="видно")
    other = django_user_model.objects.create_user("o", password="p12345678")
    Note.objects.create(user=other, document=doc, text="чужая заметка")

    content = client.get(reverse("note_list")).content.decode()
    assert "видно" in content
    assert "чужая заметка" not in content


@pytest.mark.django_db
def test_delete_own_note(auth):
    user, client = auth
    note = Note.objects.create(user=user, document=make_document(slug="tk"), text="x")
    resp = client.post(reverse("note_delete", args=[note.pk]))
    assert resp.status_code == 302
    assert not Note.objects.filter(pk=note.pk).exists()


@pytest.mark.django_db
def test_cannot_delete_others_note(auth, django_user_model):
    _, client = auth
    other = django_user_model.objects.create_user("o", password="p12345678")
    note = Note.objects.create(user=other, document=make_document(slug="tk"), text="x")
    resp = client.post(reverse("note_delete", args=[note.pk]))
    assert resp.status_code == 404
    assert Note.objects.filter(pk=note.pk).exists()
