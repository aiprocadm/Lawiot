from datetime import date

import pytest
from django.utils import timezone

from documents.models import Document, Redaction
from documents.tests.factories import make_document, make_redaction

DISCLAIMER_MARK = "официального опубликования"


@pytest.mark.django_db
def test_new_document_defaults_to_federal_official():
    doc = make_document(slug="d1")
    assert doc.level == Document.Level.FEDERAL
    assert doc.source_status == Document.SourceStatus.OFFICIAL
    assert doc.region_code == ""


@pytest.mark.django_db
def test_new_redaction_defaults_to_official_text():
    red = make_redaction(make_document(slug="d2"))
    assert red.text_status == Redaction.TextStatus.OFFICIAL
    assert red.get_text_status_display() == "Официальная редакция"


@pytest.mark.django_db
def test_ingested_draft_marked_official():
    from datetime import date

    from ingestion.parsing import parse_text
    from ingestion.services import create_draft_from_parsed

    doc = make_document(slug="d3")
    parsed = parse_text("Статья 1. Право на труд.", "code")
    red = create_draft_from_parsed(doc, parsed, redaction_date=date(2022, 1, 1))
    assert red.text_status == Redaction.TextStatus.OFFICIAL


@pytest.mark.django_db
def test_disclaimer_in_footer_on_pages(client, django_user_model):
    user = django_user_model.objects.create_user("r-foot", password="x")
    client.force_login(user)
    make_document(slug="d-foot")
    # список актов и страница поиска — обе наследуют base.html
    assert DISCLAIMER_MARK in client.get("/").content.decode()
    assert DISCLAIMER_MARK in client.get("/search/").content.decode()


def _published_doc(*, source_url="", text_status="official"):
    doc = make_document(
        slug="card-act",
        doc_type="federal_law",
        title="Карточный акт",
        official_number="1-ФЗ",
        status="in_force",
        source_url=source_url,
    )
    make_redaction(
        doc,
        redaction_date=date(2020, 1, 2),
        review_status="published",
        is_current=True,
        published_at=timezone.now(),
        full_text="текст",
        text_status=text_status,
    )
    return doc


@pytest.mark.django_db
def test_card_shows_level_source_and_origin(client, django_user_model):
    user = django_user_model.objects.create_user("r-card", password="x")
    client.force_login(user)
    _published_doc()
    html = client.get("/doc/card-act/").content.decode()
    assert "Уровень" in html
    assert "Федеральный" in html
    assert "Источник" in html
    assert "Официальный источник" in html  # значение source_status display
    assert "Происхождение текста" in html
    assert "Официальная редакция" in html


@pytest.mark.django_db
def test_card_source_link_present_only_when_url_set(client, django_user_model):
    user = django_user_model.objects.create_user("r-link", password="x")
    client.force_login(user)
    _published_doc(source_url="http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=1&print=1")
    html = client.get("/doc/card-act/").content.decode()
    assert 'href="http://pravo.gov.ru/proxy/ips/?doc_itself=&amp;nd=1&amp;print=1"' in html


@pytest.mark.django_db
def test_card_no_source_link_when_url_blank(client, django_user_model):
    user = django_user_model.objects.create_user("r-nolink", password="x")
    client.force_login(user)
    _published_doc(source_url="")
    html = client.get("/doc/card-act/").content.decode()
    assert ">Официальный первоисточник<" not in html  # ссылка-якорь отсутствует


@pytest.mark.django_db
def test_print_page_has_disclaimer(client, django_user_model):
    user = django_user_model.objects.create_user("r-print", password="x")
    client.force_login(user)
    _published_doc()
    html = client.get("/doc/card-act/print/").content.decode()
    assert DISCLAIMER_MARK in html


@pytest.mark.django_db
def test_docx_export_has_disclaimer(client, django_user_model):
    import io

    from docx import Document as Dx

    user = django_user_model.objects.create_user("r-docx", password="x")
    client.force_login(user)
    _published_doc(source_url="http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=1&print=1")
    resp = client.get("/doc/card-act/export.docx")
    assert resp.status_code == 200
    dx = Dx(io.BytesIO(resp.content))
    texts = "\n".join(p.text for p in dx.paragraphs)
    assert DISCLAIMER_MARK in texts
    assert "pravo.gov.ru" in texts
