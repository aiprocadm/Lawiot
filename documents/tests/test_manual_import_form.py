"""Валидация формы ручного импорта: ограничение размера и расширения файла."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from documents.forms import ManualImportForm
from documents.tests.factories import make_document


def _form(upload):
    doc = make_document()
    return ManualImportForm(
        data={"document": doc.pk, "content_type": "text/plain"},
        files={"upload_file": upload},
    )


@pytest.mark.django_db
def test_accepts_small_txt():
    upload = SimpleUploadedFile("act.txt", b"hello", content_type="text/plain")
    form = _form(upload)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_rejects_oversized_upload():
    upload = SimpleUploadedFile("act.txt", b"x", content_type="text/plain")
    upload.size = ManualImportForm.MAX_UPLOAD_BYTES + 1  # без аллокации огромного буфера
    form = _form(upload)
    assert not form.is_valid()
    assert "upload_file" in form.errors


@pytest.mark.django_db
def test_rejects_disallowed_extension():
    upload = SimpleUploadedFile("act.exe", b"data", content_type="application/octet-stream")
    form = _form(upload)
    assert not form.is_valid()
    assert "upload_file" in form.errors
