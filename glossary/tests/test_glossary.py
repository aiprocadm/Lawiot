import pytest
from django.urls import reverse

from documents.tests.factories import make_document
from glossary.models import Term


@pytest.mark.django_db
def test_glossary_requires_login(client):
    resp = client.get(reverse("glossary_list"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_empty_glossary_shows_placeholder(auth_client):
    resp = auth_client.get(reverse("glossary_list"))
    assert resp.status_code == 200
    assert "пока пуст" in resp.content.decode()


@pytest.mark.django_db
def test_only_published_terms_listed(auth_client):
    Term.objects.create(term="Опубликованный", is_published=True)
    Term.objects.create(term="Черновик", is_published=False)
    content = auth_client.get(reverse("glossary_list")).content.decode()
    assert "Опубликованный" in content
    assert "Черновик" not in content


@pytest.mark.django_db
def test_term_links_to_defining_act(auth_client):
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    Term.objects.create(
        term="Сверхурочная работа",
        definition="Работа за пределами установленной продолжительности.",
        document=doc,
        article_number="99",
        is_published=True,
    )
    content = auth_client.get(reverse("glossary_list")).content.decode()
    assert "Сверхурочная работа" in content
    assert reverse("document_detail", args=["tk"]) in content
    assert "ст. 99" in content


@pytest.mark.django_db
def test_query_filters_terms(auth_client):
    Term.objects.create(term="Отпуск", is_published=True)
    Term.objects.create(term="Командировка", is_published=True)
    content = auth_client.get(reverse("glossary_list"), {"q": "отпуск"}).content.decode()
    assert "Отпуск" in content
    assert "Командировка" not in content


@pytest.mark.django_db
def test_terms_alphabetical(auth_client):
    Term.objects.create(term="Яблоко", is_published=True)
    Term.objects.create(term="Абонент", is_published=True)
    content = auth_client.get(reverse("glossary_list")).content.decode()
    assert content.index("Абонент") < content.index("Яблоко")
