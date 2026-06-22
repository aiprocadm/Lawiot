from io import StringIO

import pytest
from django.core.management import call_command

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.mark.django_db
def test_corpus_health_reports_counts():
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="1", title="Цели", text="цели")
    red.publish()
    # документ-черновик без публикации
    make_document(slug="draft", title="Черновик", official_number="2")

    out = StringIO()
    call_command("corpus_health", stdout=out)
    text = out.getvalue()

    assert "Всего: 2" in text
    assert "С опубликованной текущей редакцией: 1" in text
    assert "Без опубликованной редакции: 1" in text
    assert "Статья: 1" in text
    assert "=== Связи ===" in text
