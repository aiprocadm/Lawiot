from datetime import date

import pytest

from documents.models import Article, Document, Redaction


@pytest.mark.django_db
def test_passport_shows_point_and_appendix_counts(client, django_user_model):
    user = django_user_model.objects.create_user("reader", "r@e.ru", "pw")
    client.force_login(user)
    doc = Document.objects.create(
        doc_type=Document.DocType.DECREE,
        title="Постановление",
        slug="card-decree",
        status=Document.Status.IN_FORCE,
    )
    red = Redaction.objects.create(
        document=doc,
        redaction_date=date(2020, 1, 1),
        review_status=Redaction.ReviewStatus.PUBLISHED,
        is_current=True,
        full_text="текст",
    )
    appendix = Article.objects.create(
        redaction=red, kind=Article.Kind.APPENDIX, number="1", order=1
    )
    Article.objects.create(
        redaction=red, kind=Article.Kind.POINT, number="1", order=2, parent=appendix
    )
    resp = client.get(f"/doc/{doc.slug}/", SERVER_NAME="localhost")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "приложени" in html.lower()
    assert "пункт" in html.lower()
