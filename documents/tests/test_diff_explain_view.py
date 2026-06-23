from datetime import date

import pytest
from django.urls import reverse

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.fixture
def two_redactions(db):
    """Акт с двумя опубликованными редакциями: старая (не текущая) и текущая."""
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    older = make_redaction(doc, redaction_date=date(2023, 1, 1), full_text="")
    make_article(older, number="5", title="Отпуск", text="старая редакция статьи 5")
    older.publish()
    newer = make_redaction(doc, redaction_date=date(2024, 1, 1), full_text="")
    make_article(newer, number="5", title="Отпуск", text="новая редакция статьи 5")
    newer.publish()  # демотирует older, остаётся published
    return doc, older, newer


@pytest.mark.django_db
def test_explain_requires_login(client, two_redactions):
    doc, older, _ = two_redactions
    resp = client.get(reverse("redaction_diff_explain", args=[doc.slug, older.pk]))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_explain_degrades_without_api_key(auth_client, two_redactions, settings):
    settings.ANTHROPIC_API_KEY = ""  # без ключа — режим unavailable, без сети
    doc, older, _ = two_redactions
    resp = auth_client.get(reverse("redaction_diff_explain", args=[doc.slug, older.pk]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "<!doctype html" not in content.lower()  # это партиал
    assert "недоступно" in content


@pytest.mark.django_db
def test_explain_404_when_from_is_current(auth_client, two_redactions):
    doc, _, newer = two_redactions
    resp = auth_client.get(reverse("redaction_diff_explain", args=[doc.slug, newer.pk]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_diff_page_shows_explain_button(auth_client, two_redactions):
    doc, older, _ = two_redactions
    resp = auth_client.get(reverse("redaction_diff", args=[doc.slug, older.pk]))
    content = resp.content.decode()
    assert resp.status_code == 200
    assert "Объяснить изменения" in content
    assert reverse("redaction_diff_explain", args=[doc.slug, older.pk]) in content
