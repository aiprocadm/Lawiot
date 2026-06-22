from datetime import date

import pytest
from django.urls import reverse

from documents.tests.factories import make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_sort_by_date_orders_newest_first(auth_client):
    old = make_document(slug="old", title="Старый акт", official_number="1",
                        sign_date=date(2010, 1, 1))
    make_redaction(old, full_text="общийтокенпоиска").publish()
    new = make_document(slug="new", title="Новый акт", official_number="2",
                        sign_date=date(2020, 1, 1))
    make_redaction(new, full_text="общийтокенпоиска").publish()

    resp = auth_client.get(reverse("search"), {"q": "общийтокенпоиска", "sort": "date"})
    slugs = [r.document.slug for r in resp.context["page_obj"].object_list]
    assert slugs.index("new") < slugs.index("old")


@pytest.mark.django_db
def test_default_sort_relevance_and_control_present(auth_client):
    doc = make_document(slug="tk", title="ТК", official_number="1")
    make_redaction(doc, full_text="релевантныйтокен").publish()

    resp = auth_client.get(reverse("search"), {"q": "релевантныйтокен"})
    assert resp.status_code == 200
    assert "Сортировка" in resp.content.decode()  # контрол сортировки на странице
