import pytest
from django.contrib.postgres.search import SearchQuery, SearchVectorField

from documents.models import Article, Redaction
from documents.tests.factories import make_article, make_document, make_redaction


def test_search_vector_fields_exist():
    assert isinstance(
        Redaction._meta.get_field("search_vector"), SearchVectorField
    )
    assert isinstance(
        Article._meta.get_field("search_vector"), SearchVectorField
    )


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
    make_article(red, number="81", title="Расторжение",
                 text="трудовой договор расторгается работодателем")
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
