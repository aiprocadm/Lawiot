from datetime import date

import pytest

from documents.models import Article, Document, Redaction
from ingestion.services import _article_count, _is_safe_to_publish


@pytest.mark.django_db
def test_article_count_includes_points():
    doc = Document.objects.create(doc_type=Document.DocType.DECREE, title="П", slug="gate-1")
    red = Redaction.objects.create(document=doc, redaction_date=date(2020, 1, 1))
    Article.objects.create(redaction=red, kind=Article.Kind.POINT, number="1", order=1)
    Article.objects.create(redaction=red, kind=Article.Kind.POINT, number="2", order=2)
    assert _article_count(red) == 2


@pytest.mark.django_db
def test_decree_with_points_passes_publish_gate():
    doc = Document.objects.create(doc_type=Document.DocType.DECREE, title="П", slug="gate-2")
    red = Redaction.objects.create(
        document=doc, redaction_date=date(2020, 1, 1), full_text="текст"
    )
    Article.objects.create(redaction=red, kind=Article.Kind.POINT, number="1", order=1)
    assert _is_safe_to_publish(red, None) is True
