import pytest

from documents.models import Document
from documents.tests.factories import make_article, make_document, make_redaction
from search.services import search_documents


@pytest.mark.django_db
def test_finds_document_by_full_text():
    doc = make_document(slug="zan", title="О занятости")
    make_redaction(doc, full_text="пособие по безработице гражданам").publish()
    results = search_documents("безработице")
    assert len(results) == 1
    assert results[0].document == doc
    assert results[0].article_anchor is None
    assert "<mark>" in results[0].snippet


@pytest.mark.django_db
def test_finds_article_and_returns_anchor():
    doc = make_document(slug="tk", title="Трудовой кодекс")
    red = make_redaction(doc, full_text="")
    make_article(red, number="81", title="Расторжение",
                 text="увольнение работника работодателем")
    red.publish()
    results = search_documents("работодателем")
    assert len(results) == 1
    assert results[0].document == doc
    assert results[0].article_anchor == "st-81"
    assert "81" in results[0].article_label


@pytest.mark.django_db
def test_filters_by_doc_type():
    law = make_document(slug="law", title="Закон",
                        doc_type=Document.DocType.FEDERAL_LAW)
    make_redaction(law, full_text="общийтермин в законе").publish()
    order = make_document(slug="ord", title="Приказ",
                          doc_type=Document.DocType.ORDER)
    make_redaction(order, full_text="общийтермин в приказе").publish()

    results = search_documents("общийтермин", doc_type=Document.DocType.FEDERAL_LAW)
    assert {r.document for r in results} == {law}


@pytest.mark.django_db
def test_drafts_are_not_searched():
    doc = make_document(slug="d", title="Черновик")
    make_redaction(doc, full_text="секретноеслово")  # not published
    assert search_documents("секретноеслово") == []


@pytest.mark.django_db
def test_empty_query_returns_empty():
    assert search_documents("") == []
    assert search_documents("   ") == []
