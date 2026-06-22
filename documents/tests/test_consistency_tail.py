"""Доводка v1 — хвост двух классов консистентности UI (closeout #39/#40):

A. Сырая `redaction_date` (ISO) не должна утекать пользователю/куратору — везде
   формат ДД.ММ.ГГГГ через `|date:"d.m.Y"`.
B. У акта без `official_number` (blank=True) в результатах поиска не должно быть
   висячего «№».

Изолированный файл — hotspot `test_views.py` не трогаем.
"""

from datetime import date

import pytest
from django.urls import reverse

from documents.models import Document
from documents.tests.factories import make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser("cur", "c@example.test", "pass12345")
    client.force_login(user)
    return client


# --- Класс A: формат даты ДД.ММ.ГГГГ ---


@pytest.mark.django_db
def test_reader_redaction_diff_renders_dates_as_dmy(auth_client):
    """Читательская diff-страница: обе даты в заголовке — ДД.ММ.ГГГГ, не ISO."""
    doc = make_document(slug="ct-diff", official_number="1", title="Акт для diff")
    older = make_redaction(doc, redaction_date=date(2023, 1, 1))
    older.publish()
    newer = make_redaction(doc, redaction_date=date(2024, 6, 1))
    newer.publish()  # становится текущей, older перестаёт быть current

    url = reverse("redaction_diff", args=["ct-diff", older.pk])
    content = auth_client.get(url).content.decode()

    assert "01.01.2023" in content
    assert "01.06.2024" in content
    assert "2023-01-01" not in content
    assert "2024-06-01" not in content


@pytest.mark.django_db
def test_admin_diff_renders_current_date_as_dmy(staff_client):
    """Админский diff черновика: дата текущей редакции — ДД.ММ.ГГГГ, не ISO."""
    doc = make_document(slug="ct-admin-diff", official_number="1")
    current = make_redaction(doc, redaction_date=date(2020, 1, 1))
    current.publish()
    draft = make_redaction(doc, redaction_date=date(2025, 2, 3))  # DRAFT по умолчанию

    url = reverse("admin:documents_redaction_diff", args=[draft.pk])
    content = staff_client.get(url).content.decode()

    assert "01.01.2020" in content
    assert "2020-01-01" not in content


@pytest.mark.django_db
def test_admin_review_queue_renders_draft_date_as_dmy(staff_client):
    """Очередь ревью: дата черновика — ДД.ММ.ГГГГ, не ISO."""
    doc = make_document(slug="ct-queue", official_number="1")
    make_redaction(doc, redaction_date=date(2021, 3, 4))  # DRAFT — попадает в очередь

    url = reverse("admin:documents_redaction_review_queue")
    content = staff_client.get(url).content.decode()

    assert "04.03.2021" in content
    assert "2021-03-04" not in content


# --- Класс B: guard висячего «№» ---


@pytest.mark.django_db
def test_search_results_omit_number_label_when_blank(auth_client):
    """Результат поиска для акта без номера: тип и статус есть, висячего «№» нет."""
    doc = make_document(
        slug="ct-nonum",
        official_number="",
        title="Безномерной акт",
        doc_type=Document.DocType.FEDERAL_LAW,
    )
    make_redaction(doc, full_text="безномернойтокенуникум").publish()

    content = auth_client.get(
        reverse("search"), {"q": "безномернойтокенуникум"}
    ).content.decode()

    assert "Безномерной акт" in content  # результат отрендерен
    assert "Федеральный закон" in content  # тип акта остался
    assert "№" not in content  # нет висячего «№» (единственный № в шаблонах — этот)
