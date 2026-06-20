import re
from datetime import date

import pytest

from documents.models import Article, Document, Redaction


def _structure_value(html):
    """Достаёт текст панели «Структура» из паспорт-блока со сжатыми пробелами."""
    m = re.search(r"Структура</dt>\s*<dd>(.*?)</dd>", html, re.S)
    assert m, "панель «Структура» не найдена в карточке"
    return " ".join(m.group(1).split())


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
    html = resp.content.decode().lower()
    # Проверяем именно счётчики структуры (со значением), а не просто слова.
    assert "1 приложени" in html
    assert "1 пункт" in html


@pytest.mark.django_db
def test_structure_has_no_trailing_separator_without_articles(client, django_user_model):
    """Подзаконный акт без статей не оставляет висячий « · » в конце панели."""
    user = django_user_model.objects.create_user("reader2", "r2@e.ru", "pw")
    client.force_login(user)
    doc = Document.objects.create(
        doc_type=Document.DocType.DECREE,
        title="Постановление без статей",
        slug="card-decree-no-articles",
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

    value = _structure_value(resp.content.decode())
    # Разделитель только МЕЖДУ элементами — без висячего хвоста.
    assert value == "1 приложени(й) · 1 пункт(ов)"
    assert not value.endswith("·")


@pytest.mark.django_db
def test_structure_shows_dash_when_empty(client, django_user_model):
    """Полностью пустая структура (нет ни одной единицы) рендерит прочерк «—»."""
    user = django_user_model.objects.create_user("reader3", "r3@e.ru", "pw")
    client.force_login(user)
    doc = Document.objects.create(
        doc_type=Document.DocType.OTHER,
        title="Акт без структуры",
        slug="card-no-structure",
        status=Document.Status.IN_FORCE,
    )
    Redaction.objects.create(
        document=doc,
        redaction_date=date(2020, 1, 1),
        review_status=Redaction.ReviewStatus.PUBLISHED,
        is_current=True,
        full_text="текст",
    )
    resp = client.get(f"/doc/{doc.slug}/", SERVER_NAME="localhost")
    assert resp.status_code == 200

    assert _structure_value(resp.content.decode()) == "—"
