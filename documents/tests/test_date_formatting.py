"""Доводка v1: единообразный русский формат дат (ДД.ММ.ГГГГ) на читательских
страницах и отсутствие висячего «№» у актов без номера."""

from datetime import date

import pytest
from django.urls import reverse

from documents.tests.factories import make_document, make_redaction


@pytest.mark.django_db
def test_changes_feed_renders_redaction_date_as_dmy(auth_client):
    doc = make_document(slug="df-feed", official_number="1", title="Акт ленты")
    make_redaction(doc, redaction_date=date(2025, 12, 29)).publish()

    content = auth_client.get(reverse("changes_feed")).content.decode()

    assert "29.12.2025" in content
    assert "2025-12-29" not in content


@pytest.mark.django_db
def test_document_detail_other_redactions_render_date_as_dmy(auth_client):
    doc = make_document(slug="df-detail", official_number="1", title="Акт с историей")
    make_redaction(doc, redaction_date=date(2023, 1, 1)).publish()
    make_redaction(doc, redaction_date=date(2024, 6, 1)).publish()  # становится текущей

    content = auth_client.get(reverse("document_detail", args=["df-detail"])).content.decode()

    # блок «Другие редакции» показывает прошлую редакцию в формате ДД.ММ.ГГГГ
    assert "01.01.2023" in content
    assert "2023-01-01" not in content


@pytest.mark.django_db
def test_document_list_omits_number_label_when_blank(auth_client):
    doc = make_document(slug="df-nonum", official_number="", title="Акт без номера")
    make_redaction(doc).publish()

    content = auth_client.get(reverse("document_list")).content.decode()

    assert "Акт без номера" in content
    assert "№" not in content
