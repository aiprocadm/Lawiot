import pytest
from django.contrib.postgres.search import SearchVectorField

from documents.models import Article, Redaction


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
