import pytest
from django.urls import reverse

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.mark.django_db
def test_reader_linkifies_internal_reference(auth_client):
    doc = make_document(slug="tk", title="ТК")
    red = make_redaction(doc, full_text="")
    make_article(red, number="72", title="Перевод", text="изменение условий договора", order=0)
    make_article(
        red, number="81", title="Расторжение",
        text="расторжение в соответствии со статьёй 72 настоящего Кодекса", order=1,
    )
    red.publish()

    content = auth_client.get(reverse("document_detail", args=["tk"])).content.decode()
    assert 'href="#st-72"' in content
