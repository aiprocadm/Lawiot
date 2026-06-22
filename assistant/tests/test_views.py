import pytest
from django.urls import reverse

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_assistant_requires_login(client):
    resp = client.get(reverse("assistant"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_assistant_get_without_question(auth_client):
    resp = auth_client.get(reverse("assistant"))
    assert resp.status_code == 200
    assert "Ассистент" in resp.content.decode()


@pytest.mark.django_db
def test_assistant_answers_with_article_links(auth_client, settings):
    settings.ANTHROPIC_API_KEY = ""  # retrieval-only — без сети
    doc = make_document(slug="tk", title="Трудовой кодекс", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="127", title="Отпуск",
                 text="компенсация за неиспользованный отпуск")
    red.publish()

    resp = auth_client.get(reverse("assistant"), {"q": "компенсация отпуск"})
    content = resp.content.decode()
    assert resp.status_code == 200
    assert "/doc/tk/#st-127" in content


@pytest.mark.django_db
def test_assistant_hx_returns_partial(auth_client, settings):
    settings.ANTHROPIC_API_KEY = ""
    resp = auth_client.get(
        reverse("assistant"), {"q": "ничегонетпоэтомузапросу"}, HTTP_HX_REQUEST="true"
    )
    content = resp.content.decode()
    assert resp.status_code == 200
    assert "<!doctype html" not in content.lower()
