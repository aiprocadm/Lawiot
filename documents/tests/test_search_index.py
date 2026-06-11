import pytest
from django.contrib.postgres.search import SearchQuery, SearchVectorField
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from documents.models import Article, Document, Redaction
from documents.tests.factories import make_article, make_document, make_redaction


def test_search_vector_fields_exist():
    assert isinstance(Redaction._meta.get_field("search_vector"), SearchVectorField)
    assert isinstance(Article._meta.get_field("search_vector"), SearchVectorField)


@pytest.mark.django_db
def test_no_pending_migrations_for_search_vectors():
    # Schema and migrations are in sync (the field migration exists).
    from io import StringIO
    from django.core.management import call_command

    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)


def _matches(model_qs, term):
    q = SearchQuery(term, config="russian", search_type="websearch")
    return model_qs.filter(search_vector=q).exists()


@pytest.mark.django_db
def test_publish_populates_vectors_for_redaction_and_articles():
    doc = make_document(title="О занятости населения")
    red = make_redaction(doc, full_text="пособие по безработице назначается гражданам")
    make_article(
        red, number="81", title="Расторжение", text="трудовой договор расторгается работодателем"
    )
    red.publish()
    red.refresh_from_db()

    assert red.search_vector is not None
    # redaction vector covers full_text and the document title
    assert _matches(Redaction.objects.filter(pk=red.pk), "безработице")
    assert _matches(Redaction.objects.filter(pk=red.pk), "занятости")
    # article vector covers article text
    assert _matches(Article.objects.filter(redaction=red), "работодателем")


@pytest.mark.django_db
def test_reindex_search_backfills_vectors():
    doc = make_document(title="Тест", slug="t1")
    red = make_redaction(doc, full_text="особоеслово для поиска")
    red.publish()
    # simulate stale index
    Redaction.objects.filter(pk=red.pk).update(search_vector=None)
    assert not _matches(Redaction.objects.filter(pk=red.pk), "особоеслово")

    from django.core.management import call_command

    call_command("reindex_search")

    assert _matches(Redaction.objects.filter(pk=red.pk), "особоеслово")


@pytest.mark.django_db
def test_bulk_reindex_matches_update_search_index():
    doc = Document.objects.create(
        doc_type="federal_law", title="Налоговый кодекс", official_number="1-ФЗ", slug="1-fz"
    )
    red = Redaction.objects.create(
        document=doc,
        redaction_date="2026-01-01",
        is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
        full_text="налог и сбор",
    )
    Article.objects.create(redaction=red, number="1", title="Общие", text="ставка налога", order=0)
    red.update_search_index()  # эталон (ORM-путь публикации)
    red.refresh_from_db()
    expected_red = red.search_vector
    expected_art = Article.objects.get(redaction=red, number="1").search_vector

    Redaction.objects.filter(pk=red.pk).update(search_vector=None)
    Article.objects.filter(redaction=red).update(search_vector=None)
    call_command("reindex_search")  # bulk-путь
    red.refresh_from_db()
    assert red.search_vector == expected_red  # паритет: тот же вектор
    assert Article.objects.get(redaction=red, number="1").search_vector == expected_art


@pytest.mark.django_db
def test_bulk_reindex_skips_drafts():
    doc = Document.objects.create(
        doc_type="federal_law", title="Док", official_number="2-ФЗ", slug="2-fz"
    )
    draft = Redaction.objects.create(
        document=doc,
        redaction_date="2026-01-01",
        review_status=Redaction.ReviewStatus.DRAFT,
        full_text="черновик налог",
    )
    call_command("reindex_search")
    draft.refresh_from_db()
    assert draft.search_vector is None  # черновики не индексируем


@pytest.mark.django_db
def test_bulk_reindex_uses_constant_queries():
    doc = Document.objects.create(
        doc_type="federal_law", title="Док", official_number="3-ФЗ", slug="3-fz"
    )
    for i in range(5):
        Redaction.objects.create(
            document=doc,
            redaction_date=f"2020-01-0{i + 1}",
            review_status=Redaction.ReviewStatus.PUBLISHED,
            full_text=f"налог {i}",
        )
    with CaptureQueriesContext(connection) as ctx:
        call_command("reindex_search")
    updates = [q for q in ctx.captured_queries if q["sql"].lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 2  # 5 редакций → всё ещё 2 UPDATE (не 2N)
