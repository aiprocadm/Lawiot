import pytest

from documents.models import Document
from documents.tests.factories import make_article, make_document, make_redaction
from search import services
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
    make_article(red, number="81", title="Расторжение", text="увольнение работника работодателем")
    red.publish()
    results = search_documents("работодателем")
    assert len(results) == 1
    assert results[0].document == doc
    assert results[0].article_anchor == "st-81"
    assert "81" in results[0].article_label


@pytest.mark.django_db
def test_filters_by_doc_type():
    law = make_document(slug="law", title="Закон", doc_type=Document.DocType.FEDERAL_LAW)
    make_redaction(law, full_text="общийтермин в законе").publish()
    order = make_document(slug="ord", title="Приказ", doc_type=Document.DocType.ORDER)
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


@pytest.mark.django_db
def test_filters_by_date_range():
    from datetime import date

    old = make_document(slug="old", title="Старыйдок", sign_date=date(2010, 1, 1))
    make_redaction(old, full_text="редкийтермин примертекст").publish()
    new = make_document(slug="new", title="Новыйдок", sign_date=date(2024, 1, 1))
    make_redaction(new, full_text="редкийтермин примертекст").publish()

    only_new = search_documents("редкийтермин", date_from=date(2020, 1, 1))
    assert {r.document for r in only_new} == {new}

    only_old = search_documents("редкийтермин", date_to=date(2015, 1, 1))
    assert {r.document for r in only_old} == {old}


@pytest.mark.django_db
def test_filters_by_status_and_issuing_body():
    active = make_document(
        slug="act",
        title="Действующий",
        status=Document.Status.IN_FORCE,
        issuing_body="Минтруд России",
    )
    make_redaction(active, full_text="статусслово примертекст").publish()
    repealed = make_document(
        slug="rep",
        title="Утративший",
        status=Document.Status.REPEALED,
        issuing_body="Иной орган",
    )
    make_redaction(repealed, full_text="статусслово примертекст").publish()

    by_status = search_documents("статусслово", status=Document.Status.IN_FORCE)
    assert {r.document for r in by_status} == {active}

    by_body = search_documents("статусслово", issuing_body="минтруд")
    assert {r.document for r in by_body} == {active}


@pytest.mark.django_db
def test_search_caps_hits_per_source(monkeypatch):
    monkeypatch.setattr(services, "_MAX_HITS_PER_SOURCE", 2)
    for i in range(3):
        doc = make_document(slug=f"cap-{i}", official_number=str(i), title=f"Акт {i}")
        make_redaction(doc, full_text="уникальноеслово").publish()

    results = search_documents("уникальноеслово")
    assert len(results) == 2


@pytest.mark.django_db
def test_search_snippet_escapes_html_keeps_mark():
    doc = make_document(slug="xss", title="Док")
    # Внешний текст с HTML-спецсимволами и тегом-инъекцией: сниппет должен быть
    # экранирован, а подсветка <mark> — сохранена (защита от stored-XSS).
    make_redaction(
        doc, full_text="Договор «А & Б» <script>alert(1)</script> про налог тут."
    ).publish()
    [result] = search_documents("налог")
    snippet = str(result.snippet)
    assert "<script>" not in snippet  # исполняемый тег не проходит
    assert "&amp;" in snippet  # спецсимвол «&» экранирован
    assert "<mark>налог</mark>" in snippet  # подсветка совпадения сохранена
