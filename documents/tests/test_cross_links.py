import re

import pytest
from django.urls import reverse

from documents.refs import linkify_internal_refs
from documents.tests.factories import make_article, make_document, make_redaction

_TRUDOV = re.compile(r"\bтрудов\w+\s+кодекс\w*", re.I)


def test_external_fz_links_when_in_corpus():
    html = linkify_internal_refs("в соответствии с 426-ФЗ", {"numbers": {"426-ФЗ": "/doc/sout/"}})
    assert '<a href="/doc/sout/">426-ФЗ</a>' in html


def test_external_fz_not_linked_when_absent():
    html = linkify_internal_refs("см. 999-ФЗ", {"numbers": {"426-ФЗ": "/x/"}})
    assert "<a" not in html
    assert "999-ФЗ" in html


def test_external_codex_links_by_name():
    html = linkify_internal_refs("по Трудовым кодексом", {"codices": [(_TRUDOV, "/doc/tk-rf/")]})
    assert 'href="/doc/tk-rf/"' in html
    assert "Трудовым кодексом" in html


def test_internal_and_external_combined():
    links = {"anchors": {"st-5"}, "numbers": {"426-ФЗ": "/doc/x/"}, "codices": [(_TRUDOV, "/doc/tk/")]}
    html = linkify_internal_refs("статьёй 5, 426-ФЗ и Трудовым кодексом", links)
    assert 'href="#st-5"' in html
    assert 'href="/doc/x/"' in html
    assert 'href="/doc/tk/"' in html


def test_escapes_html_with_external():
    html = linkify_internal_refs("<b> и 426-ФЗ", {"numbers": {"426-ФЗ": "/x/"}})
    assert "<b>" not in html
    assert "&lt;b&gt;" in html


def test_backward_compat_set_is_anchors():
    html = linkify_internal_refs("статьёй 5", {"st-5"})
    assert 'href="#st-5"' in html


@pytest.mark.django_db
def test_reader_renders_cross_act_links(client, django_user_model):
    user = django_user_model.objects.create_user("r", password="p12345678")
    client.force_login(user)

    tk = make_document(slug="tk-rf", title="Трудовой кодекс Российской Федерации",
                       official_number="197-ФЗ")
    tred = make_redaction(tk, full_text="")
    make_article(tred, number="1", title="Цели", text="цели")
    tred.publish()

    sout = make_document(slug="sout-426-fz", title="О специальной оценке условий труда",
                         official_number="426-ФЗ", doc_type="federal_law")
    sred = make_redaction(sout, full_text="")
    make_article(sred, number="3", title="Применение",
                 text="оценка проводится в соответствии с Трудовым кодексом")
    sred.publish()

    content = client.get(reverse("document_detail", args=["sout-426-fz"])).content.decode()
    # кодекс по имени в тексте 426-ФЗ → кликабельная ссылка на ТК РФ
    assert f'href="{reverse("document_detail", args=["tk-rf"])}"' in content
