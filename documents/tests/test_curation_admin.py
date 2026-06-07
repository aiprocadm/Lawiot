import pytest
from django.urls import reverse
from django.utils import timezone

from documents.models import Article, Document, Redaction
from ingestion.models import IngestionJob
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


@pytest.mark.django_db
def test_publish_from_diff_publishes_and_indexes(staff_client, draft_with_raw):
    resp = staff_client.post(reverse("admin:documents_redaction_diff", args=[draft_with_raw.pk]))
    assert resp.status_code == 302
    draft_with_raw.refresh_from_db()
    assert draft_with_raw.review_status == Redaction.ReviewStatus.PUBLISHED
    assert draft_with_raw.is_current is True
    assert draft_with_raw.search_vector is not None


@pytest.mark.django_db
def test_review_queue_lists_drafts_and_failures(staff_client, draft_with_raw):
    IngestionJob.objects.create(
        target_key="tk-fail", status=IngestionJob.Status.FAILED, started_at=timezone.now()
    )
    resp = staff_client.get(reverse("admin:documents_redaction_review_queue"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "197-ФЗ" in body          # черновик в очереди
    assert "tk-fail" in body         # сбой приёма (карантин)
