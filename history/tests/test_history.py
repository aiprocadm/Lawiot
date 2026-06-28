from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from documents.tests.factories import make_document, make_redaction
from history.models import ViewHistory


@pytest.mark.django_db
def test_history_requires_login(client):
    resp = client.get(reverse("history_list"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_visiting_document_records_history(auth):
    user, client = auth
    doc = make_document(slug="tk", title="ТК")
    make_redaction(doc).publish()
    client.get(reverse("document_detail", args=["tk"]))
    assert ViewHistory.objects.filter(user=user, document=doc).exists()


@pytest.mark.django_db
def test_revisit_updates_single_row(auth):
    user, client = auth
    doc = make_document(slug="tk", title="ТК")
    make_redaction(doc).publish()
    client.get(reverse("document_detail", args=["tk"]))
    client.get(reverse("document_detail", args=["tk"]))
    assert ViewHistory.objects.filter(user=user, document=doc).count() == 1


@pytest.mark.django_db
def test_history_list_shows_viewed(auth):
    _, client = auth
    doc = make_document(slug="tk", title="Трудовой кодекс")
    make_redaction(doc).publish()
    client.get(reverse("document_detail", args=["tk"]))
    assert "Трудовой кодекс" in client.get(reverse("history_list")).content.decode()


@pytest.mark.django_db
def test_non_document_pages_not_recorded(auth):
    user, client = auth
    client.get(reverse("document_list"))
    assert ViewHistory.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_revisit_outside_throttle_updates_viewed_at(auth):
    """Просмотр после окна троттлинга обновляет «последний просмотр»."""
    user, client = auth
    doc = make_document(slug="tk", title="ТК")
    make_redaction(doc).publish()
    old = timezone.now() - timedelta(hours=2)
    ViewHistory.objects.create(user=user, document=doc, viewed_at=old)
    client.get(reverse("document_detail", args=["tk"]))
    assert ViewHistory.objects.get(user=user, document=doc).viewed_at > old


@pytest.mark.django_db
def test_revisit_within_throttle_keeps_viewed_at(auth):
    """В пределах окна троттлинга записи не происходит (анти-амплификация)."""
    user, client = auth
    doc = make_document(slug="tk", title="ТК")
    make_redaction(doc).publish()
    recent = timezone.now()
    ViewHistory.objects.create(user=user, document=doc, viewed_at=recent)
    client.get(reverse("document_detail", args=["tk"]))
    refreshed = ViewHistory.objects.get(user=user, document=doc).viewed_at
    assert abs((refreshed - recent).total_seconds()) < 1
