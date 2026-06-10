import pytest
from django.urls import reverse

from documents.models import Document
from documents.tests.factories import make_article, make_document, make_redaction
from search import views as search_views


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
def test_search_paginates_results(auth_client, monkeypatch):
    monkeypatch.setattr(search_views, "PAGE_SIZE", 2)
    for i in range(3):
        doc = make_document(slug=f"pg-{i}", official_number=str(i), title=f"Акт {i}")
        make_redaction(doc, full_text="пагинацияслово").publish()

    page1 = auth_client.get(reverse("search"), {"q": "пагинацияслово"})
    assert page1.context["page_obj"].paginator.count == 3
    assert len(page1.context["page_obj"].object_list) == 2
    assert page1.context["page_obj"].has_next() is True

    page2 = auth_client.get(reverse("search"), {"q": "пагинацияслово", "page": "2"})
    assert len(page2.context["page_obj"].object_list) == 1


@pytest.mark.django_db
def test_search_hx_request_returns_partial(auth_client):
    doc = make_document(slug="hx", title="HX-Акт", official_number="1")
    make_redaction(doc, full_text="живойпоиск").publish()

    response = auth_client.get(
        reverse("search"), {"q": "живойпоиск"}, HTTP_HX_REQUEST="true"
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert "HX-Акт" in content
    assert "<!doctype html" not in content.lower()
    assert "<nav>" not in content


@pytest.mark.django_db
def test_search_form_has_htmx_attrs(auth_client):
    response = auth_client.get(reverse("search"))
    content = response.content.decode()
    assert "hx-get=" in content
    assert 'hx-target="#search-results"' in content
    assert "delay:300ms" in content
    assert 'aria-live="polite"' in content


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
