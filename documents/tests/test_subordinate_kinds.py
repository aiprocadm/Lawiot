from datetime import date

import pytest

from documents.models import Article, Document, Redaction


def test_kind_has_point_and_appendix_labels():
    assert Article.Kind.POINT.label == "Пункт"
    assert Article.Kind.APPENDIX.label == "Приложение"


@pytest.mark.django_db
def test_point_and_appendix_anchors_generated():
    doc = Document.objects.create(
        doc_type=Document.DocType.DECREE, title="Пост.", slug="anchor-doc"
    )
    red = Redaction.objects.create(document=doc, redaction_date=date(2020, 1, 1))
    point = Article.objects.create(
        redaction=red, kind=Article.Kind.POINT, number="1.1", order=1
    )
    appendix = Article.objects.create(
        redaction=red, kind=Article.Kind.APPENDIX, number="2", order=2
    )
    assert point.anchor == "p-1-1"
    assert appendix.anchor == "pril-2"
