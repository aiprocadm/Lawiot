import datetime

import pytest
from django.utils import timezone

from documents.models import Article, Document, Redaction
from documents.seed.labor_law import SEED_ACTS


@pytest.mark.django_db
def test_seed_corpus_stamps_requisites_on_existing_document():
    from django.core.management import call_command

    Document.objects.create(
        slug="tk-rf",
        doc_type="code",
        title="Трудовой кодекс Российской Федерации",
        official_number="197-ФЗ",
    )
    call_command("seed_corpus")
    doc = Document.objects.get(slug="tk-rf")
    assert doc.sign_date == datetime.date(2001, 12, 30)
    assert doc.official_pub_date == datetime.date(2001, 12, 31)


def test_seed_acts_have_requisite_dates():
    by_slug = {a["slug"]: a for a in SEED_ACTS}
    assert by_slug["tk-rf"]["sign_date"] == datetime.date(2001, 12, 30)
    assert by_slug["tk-rf"]["official_pub_date"] == datetime.date(2001, 12, 31)
    assert by_slug["sout-426-fz"]["sign_date"] == datetime.date(2013, 12, 28)
    assert by_slug["sout-426-fz"]["official_pub_date"] == datetime.date(2013, 12, 30)


def _published_doc_with_structure():
    doc = Document.objects.create(
        slug="demo-act",
        doc_type="federal_law",
        title="Демонстрационный акт",
        official_number="1-ФЗ",
        sign_date=datetime.date(2020, 1, 1),
        official_pub_date=datetime.date(2020, 1, 2),
        status="in_force",
    )
    red = Redaction.objects.create(
        document=doc,
        redaction_date=datetime.date(2020, 1, 2),
        review_status="published",
        is_current=True,
        published_at=timezone.now(),
    )
    sec = Article.objects.create(redaction=red, kind="section", number="I", order=1)
    ch = Article.objects.create(
        redaction=red, kind="chapter", number="1", order=2, parent=sec
    )
    Article.objects.create(
        redaction=red, kind="article", number="1", title="Ст 1", text="t", order=3, parent=ch
    )
    Article.objects.create(
        redaction=red, kind="article", number="2", title="Ст 2", text="t", order=4, parent=ch
    )
    return doc


@pytest.mark.django_db
def test_detail_context_has_structure_counts(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="x")
    client.force_login(user)
    _published_doc_with_structure()
    resp = client.get("/doc/demo-act/")
    assert resp.status_code == 200
    assert resp.context["section_count"] == 1
    assert resp.context["chapter_count"] == 1
    assert resp.context["article_count"] == 2


@pytest.mark.django_db
def test_detail_renders_passport_fields(client, django_user_model):
    user = django_user_model.objects.create_user("reader2", password="x")
    client.force_login(user)
    _published_doc_with_structure()
    html = client.get("/doc/demo-act/").content.decode()
    assert "Дата подписания" in html
    assert "01.01.2020" in html  # sign_date
    assert "02.01.2020" in html  # official_pub_date
    assert "Дата опубликования" in html
    assert "status-badge" in html
    assert "status-in_force" in html
    assert "статей" in html


@pytest.mark.django_db
def test_detail_empty_requisites_show_dash(client, django_user_model):
    user = django_user_model.objects.create_user("reader3", password="x")
    client.force_login(user)
    doc = Document.objects.create(
        slug="bare-act",
        doc_type="order",
        title="Акт без реквизитов",
        official_number="",
        status="repealed",
    )
    Redaction.objects.create(
        document=doc,
        redaction_date=datetime.date(2021, 5, 5),
        review_status="published",
        is_current=True,
        published_at=timezone.now(),
        full_text="текст",
    )
    html = client.get("/doc/bare-act/").content.decode()
    assert "—" in html
    assert "status-repealed" in html
