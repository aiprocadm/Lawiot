import pytest
from django.urls import reverse

from documents.models import Article, Document, Redaction
from ingestion.services import import_manual


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser("cur", "c@example.test", "pass12345")
    client.force_login(user)
    return client


@pytest.fixture
def draft_with_raw(db):
    doc = Document.objects.create(doc_type="federal_law", title="ТК", official_number="197-ФЗ", slug="197-fz")
    return import_manual(doc, content="Статья 1. Альфа.\nСтатья 2. Бета.".encode("utf-8"))


@pytest.mark.django_db
def test_reparse_action_runs(staff_client, draft_with_raw):
    draft_with_raw.articles.filter(number="2").delete()
    resp = staff_client.post(
        reverse("admin:documents_redaction_changelist"),
        {"action": "reparse_from_raw", "_selected_action": [str(draft_with_raw.pk)]},
    )
    assert resp.status_code == 302
    draft_with_raw.refresh_from_db()
    assert draft_with_raw.articles.count() == 2


@pytest.mark.django_db
def test_diff_view_first_publication_banner(staff_client, draft_with_raw):
    url = reverse("admin:documents_redaction_diff", args=[draft_with_raw.pk])
    resp = staff_client.get(url)
    assert resp.status_code == 200
    assert "первая публикация" in resp.content.decode().lower()


@pytest.mark.django_db
def test_diff_view_shows_changed_article(staff_client, draft_with_raw):
    doc = draft_with_raw.document
    current = Redaction.objects.create(
        document=doc, redaction_date="2020-01-01", is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    Article.objects.create(redaction=current, number="1", text="старая альфа", order=0)
    resp = staff_client.get(reverse("admin:documents_redaction_diff", args=[draft_with_raw.pk]))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "changed" in body  # CSS-класс статуса статьи №1
