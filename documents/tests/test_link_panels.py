import datetime

import pytest
from django.utils import timezone

from documents.models import Document, Link, Redaction


def test_reference_label_with_number():
    doc = Document(title="О специальной оценке условий труда", official_number="426-ФЗ")
    assert doc.reference_label == "О специальной оценке условий труда (426-ФЗ)"


def test_reference_label_without_number():
    doc = Document(title="Некий акт без номера", official_number="")
    assert doc.reference_label == "Некий акт без номера"


def _published(slug, title, number, status="in_force"):
    doc = Document.objects.create(
        slug=slug,
        doc_type="federal_law",
        title=title,
        official_number=number,
        status=status,
    )
    Redaction.objects.create(
        document=doc,
        redaction_date=datetime.date(2020, 1, 2),
        review_status="published",
        is_current=True,
        published_at=timezone.now(),
        full_text="текст",
    )
    return doc


@pytest.mark.django_db
def test_references_panel_shows_reference_label(client, django_user_model):
    user = django_user_model.objects.create_user("r1", password="x")
    client.force_login(user)
    src = _published("src-act", "Исходный акт", "1-ФЗ")
    tgt = _published("sout-426-fz", "О специальной оценке условий труда", "426-ФЗ")
    Link.objects.create(
        from_document=src,
        to_document=tgt,
        link_type=Link.LinkType.REFERENCES,
        status=Link.Status.CONFIRMED,
        origin=Link.Origin.CURATOR,
    )
    html = client.get("/doc/src-act/").content.decode()
    assert "О специальной оценке условий труда (426-ФЗ)" in html


@pytest.mark.django_db
def test_blank_number_target_renders_visible_link_text(client, django_user_model):
    user = django_user_model.objects.create_user("r2", password="x")
    client.force_login(user)
    src = _published("src2", "Исходный", "2-ФЗ")
    tgt = _published("no-number-act", "Акт без номера", "")
    Link.objects.create(
        from_document=src,
        to_document=tgt,
        link_type=Link.LinkType.REFERENCES,
        status=Link.Status.CONFIRMED,
        origin=Link.Origin.CURATOR,
    )
    html = client.get("/doc/src2/").content.decode()
    # Текст ссылки виден — это название, а не пустой номер.
    assert "Акт без номера" in html


@pytest.mark.django_db
def test_incoming_panel_shows_reference_label(client, django_user_model):
    user = django_user_model.objects.create_user("r3", password="x")
    client.force_login(user)
    src = _published("citing-act", "Цитирующий акт", "7-ФЗ")
    tgt = _published("cited-act", "Цитируемый акт", "8-ФЗ")
    Link.objects.create(
        from_document=src,
        to_document=tgt,
        link_type=Link.LinkType.REFERENCES,
        status=Link.Status.CONFIRMED,
        origin=Link.Origin.CURATOR,
    )
    html = client.get("/doc/cited-act/").content.decode()
    assert "Цитирующий акт (7-ФЗ)" in html


@pytest.mark.django_db
def test_empty_panels_show_placeholder(client, django_user_model):
    user = django_user_model.objects.create_user("r4", password="x")
    client.force_login(user)
    _published("lonely-act", "Одинокий акт", "9-ФЗ")
    html = client.get("/doc/lonely-act/").content.decode()
    # Пустая панель связей рендерит приглушённую заглушку.
    assert "<small>—</small>" in html


@pytest.mark.django_db
def test_no_redundant_prefix_in_references_li(client, django_user_model):
    user = django_user_model.objects.create_user("r5", password="x")
    client.force_login(user)
    src = _published("src5", "Исходный", "5-ФЗ")
    tgt = _published("tgt5", "Цель", "6-ФЗ")
    Link.objects.create(
        from_document=src,
        to_document=tgt,
        link_type=Link.LinkType.REFERENCES,
        status=Link.Status.CONFIRMED,
        origin=Link.Origin.CURATOR,
    )
    html = client.get("/doc/src5/").content.decode()
    # Заголовок панели «Ссылается на» без двоеточия; внутри <li> префикс убран.
    assert "Ссылается на:" not in html
