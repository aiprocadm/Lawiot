from datetime import date

import pytest
from django.urls import reverse

from documents.tests.factories import make_document
from practice.models import CourtDecision


@pytest.fixture
def auth_client(client, django_user_model):
    u = django_user_model.objects.create_user("r", password="p12345678")
    client.force_login(u)
    return client


@pytest.mark.django_db
def test_practice_requires_login(client):
    resp = client.get(reverse("practice_list"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_practice_lists_published_only(auth_client):
    CourtDecision.objects.create(
        court="ВС РФ", decision_date=date(2024, 1, 1), title="Опубликованное", is_published=True
    )
    CourtDecision.objects.create(
        court="ВС РФ", decision_date=date(2024, 2, 1), title="Черновик", is_published=False
    )
    content = auth_client.get(reverse("practice_list")).content.decode()
    assert "Опубликованное" in content
    assert "Черновик" not in content


@pytest.mark.django_db
def test_practice_filtered_by_document(auth_client):
    tk = make_document(slug="tk", title="ТК")
    other = make_document(slug="other", title="Другой", official_number="1")
    CourtDecision.objects.create(court="ВС", decision_date=date(2024, 1, 1),
                                 title="По ТК", document=tk, is_published=True)
    CourtDecision.objects.create(court="ВС", decision_date=date(2024, 1, 1),
                                 title="По другому акту", document=other, is_published=True)

    content = auth_client.get(reverse("practice_list"), {"doc": "tk"}).content.decode()
    assert "По ТК" in content
    assert "По другому акту" not in content


@pytest.mark.django_db
def test_practice_unknown_doc_404(auth_client):
    resp = auth_client.get(reverse("practice_list"), {"doc": "nope"})
    assert resp.status_code == 404
