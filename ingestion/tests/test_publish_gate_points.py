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


def _decree_redaction_with_points(slug, rdate, n_points):
    doc, _ = Document.objects.get_or_create(
        doc_type=Document.DocType.DECREE, slug=slug, defaults={"title": "П"}
    )
    red = Redaction.objects.create(document=doc, redaction_date=rdate, full_text="т")
    for i in range(n_points):
        Article.objects.create(
            redaction=red, kind=Article.Kind.POINT, number=str(i + 1), order=i + 1
        )
    return red


@pytest.mark.django_db
def test_ratio_gate_with_points_blocks_sharp_drop():
    # Ветка «коэффициентного» гейта раньше была недостижима для актов-с-пунктами
    # (старый счётчик давал 0). Теперь current тоже считается по пунктам.
    current = _decree_redaction_with_points("gate-ratio", date(2020, 1, 1), 10)
    new_ok = _decree_redaction_with_points("gate-ratio", date(2021, 1, 1), 8)  # 8/10 = 0.8
    new_bad = _decree_redaction_with_points("gate-ratio", date(2022, 1, 1), 2)  # 2/10 < 0.8
    assert _is_safe_to_publish(new_ok, current) is True
    assert _is_safe_to_publish(new_bad, current) is False
