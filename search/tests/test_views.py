import pytest
from django.urls import reverse

from documents.models import Document
from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_search_requires_login(client):
    response = client.get(reverse("search"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_search_returns_results_with_highlight_and_link(auth_client):
    doc = make_document(slug="tk", title="Трудовой кодекс", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение",
                 text="увольнение работника работодателем")
    red.publish()

    response = auth_client.get(reverse("search"), {"q": "работодателем"})
    content = response.content.decode()
    assert response.status_code == 200
    assert "Трудовой кодекс" in content
    assert "<mark>" in content                 # подсветка
    assert "/doc/tk/#st-81" in content          # deep-link в статью


@pytest.mark.django_db
def test_search_filter_by_doc_type(auth_client):
    law = make_document(slug="law", title="Закон-про-отпуск",
                        doc_type=Document.DocType.FEDERAL_LAW)
    make_redaction(law, full_text="отпускслово").publish()
    order = make_document(slug="ord", title="Приказ-про-отпуск",
                          doc_type=Document.DocType.ORDER)
    make_redaction(order, full_text="отпускслово").publish()

    response = auth_client.get(
        reverse("search"), {"q": "отпускслово", "doc_type": "federal_law"}
    )
    content = response.content.decode()
    assert "Закон-про-отпуск" in content
    assert "Приказ-про-отпуск" not in content
