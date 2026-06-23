import io

import pytest
from django.urls import reverse

from documents.tests.factories import make_article, make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    u = django_user_model.objects.create_user("r", password="p12345678")
    client.force_login(u)
    return client


@pytest.mark.django_db
def test_export_requires_login(client):
    doc = make_document(slug="tk")
    make_redaction(doc).publish()
    resp = client.get(reverse("document_export_docx", args=["tk"]))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_export_returns_valid_docx_with_content(auth_client):
    doc = make_document(slug="tk", title="Трудовой кодекс", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(red, number="1", title="Цели", text="цели трудового законодательства", order=0)
    red.publish()

    resp = auth_client.get(reverse("document_export_docx", args=["tk"]))
    assert resp.status_code == 200
    assert "wordprocessingml" in resp["Content-Type"]
    assert 'filename="tk.docx"' in resp["Content-Disposition"]

    # содержимое — валидный .docx с текстом акта
    from docx import Document as DocxDocument

    docx = DocxDocument(io.BytesIO(resp.content))
    full_text = "\n".join(p.text for p in docx.paragraphs)
    assert "Трудовой кодекс" in full_text
    assert "цели трудового законодательства" in full_text


@pytest.mark.django_db
def test_export_404_without_published_redaction(auth_client):
    make_document(slug="empty")
    resp = auth_client.get(reverse("document_export_docx", args=["empty"]))
    assert resp.status_code == 404
