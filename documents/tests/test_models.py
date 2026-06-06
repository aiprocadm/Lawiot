import pytest

from documents.models import Document
from documents.tests.factories import make_document


@pytest.mark.django_db
def test_document_str_contains_type_and_number():
    doc = make_document()
    assert "Кодекс" in str(doc)
    assert "197-ФЗ" in str(doc)


@pytest.mark.django_db
def test_document_slug_is_unique():
    make_document(slug="tk-rf")
    with pytest.raises(Exception):
        make_document(slug="tk-rf", official_number="X")
