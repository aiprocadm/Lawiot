import pytest

from documents.tests.factories import make_article, make_document, make_redaction
from search.services import search_in_document


@pytest.fixture
def tk(db):
    doc = make_document(slug="tk", title="ТК")
    red = make_redaction(doc, full_text="")
    make_article(red, number="127", title="Отпуск",
                 text="компенсация за неиспользованный отпуск при увольнении", order=0)
    make_article(red, number="81", title="Расторжение",
                 text="расторжение трудового договора работодателем", order=1)
    red.publish()
    return doc


@pytest.mark.django_db
def test_finds_matching_article_with_anchor_and_snippet(tk):
    hits = search_in_document(tk, "компенсация отпуск")
    assert hits
    h = hits[0]
    assert h.anchor == "st-127"
    assert h.label == "Статья 127"
    assert h.title == "Отпуск"
    assert "<mark>" in h.snippet


@pytest.mark.django_db
def test_empty_query_returns_nothing(tk):
    assert search_in_document(tk, "") == []
    assert search_in_document(tk, "   ") == []


@pytest.mark.django_db
def test_no_match_returns_empty(tk):
    assert search_in_document(tk, "блокчейнкриптовалюта") == []


@pytest.mark.django_db
def test_scope_excludes_other_documents(tk):
    other = make_document(slug="other", title="Другой акт")
    ored = make_redaction(other, full_text="")
    make_article(ored, number="1", title="Чужая", text="компенсация отпуск в другом акте")
    ored.publish()

    hits = search_in_document(tk, "компенсация отпуск")
    anchors = {h.anchor for h in hits}
    # только статьи tk; статья «other» (тоже про компенсацию) не попадает
    assert anchors <= {"st-127", "st-81"}
