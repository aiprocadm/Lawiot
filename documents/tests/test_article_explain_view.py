import pytest
from django.urls import reverse

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def published(db):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="127", title="Отпуск",
                 text="Работодатель обязан предоставить отпуск.")
    red.publish()
    return doc


@pytest.mark.django_db
def test_explain_requires_login(client, published):
    resp = client.get(reverse("article_explain", args=[published.slug, "st-127"]))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_explain_degrades_without_api_key(auth_client, published, settings):
    settings.ANTHROPIC_API_KEY = ""  # без ключа — режим unavailable, без сети
    resp = auth_client.get(reverse("article_explain", args=[published.slug, "st-127"]))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "<!doctype html" not in content.lower()  # партиал
    assert "недоступно" in content


@pytest.mark.django_db
def test_explain_unknown_anchor_404(auth_client, published):
    resp = auth_client.get(reverse("article_explain", args=[published.slug, "st-999"]))
    assert resp.status_code == 404


# Прежний тест «дубли якорей не дают 500» удалён: уникальность (redaction, anchor)
# теперь обеспечивает БД-ограничение uniq_redaction_anchor (миграция 0018), поэтому
# создать дубль для сценария больше нельзя — он структурно невозможен.


@pytest.mark.django_db
def test_reader_shows_explain_button(auth_client, published):
    resp = auth_client.get(reverse("document_detail", args=[published.slug]))
    content = resp.content.decode()
    assert resp.status_code == 200
    assert "Разъяснить простыми словами" in content
    assert reverse("article_explain", args=[published.slug, "st-127"]) in content


@pytest.mark.django_db
def test_print_view_has_no_explain_button(auth_client, published):
    resp = auth_client.get(reverse("document_print", args=[published.slug]))
    content = resp.content.decode()
    assert resp.status_code == 200
    assert "Разъяснить простыми словами" not in content
