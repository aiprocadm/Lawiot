import pytest

from assistant.retrieval import retrieve
from documents.tests.factories import make_article, make_document, make_redaction


@pytest.mark.django_db
def test_retrieve_returns_cited_articles():
    doc = make_document(slug="tk", title="Трудовой кодекс", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(
        red, number="127", title="Отпуск при увольнении",
        text="компенсация за неиспользованный отпуск выплачивается при увольнении",
    )
    red.publish()

    out = retrieve("компенсация за отпуск")

    assert out
    a = out[0]
    assert a.document_title == "Трудовой кодекс"
    assert a.anchor == "st-127"
    assert a.url == "/doc/tk/#st-127"
    assert a.article_label == "Статья 127"
    assert "отпуск" in a.text.lower()


@pytest.mark.django_db
def test_retrieve_empty_question_returns_nothing():
    assert retrieve("") == []
    assert retrieve("   ") == []


@pytest.mark.django_db
def test_retrieve_respects_limit():
    doc = make_document(slug="tk", title="ТК")
    red = make_redaction(doc, full_text="")
    for i in range(5):
        make_article(red, number=str(i + 1), title=f"Статья про увольнение {i}",
                     text="порядок увольнения работника", order=i)
    red.publish()

    assert len(retrieve("увольнение", limit=2)) <= 2
