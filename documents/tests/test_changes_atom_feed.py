"""Тесты Atom-ленты изменений (/changes/feed/) — машиночитаемая версия /changes/."""

from datetime import date, datetime, timezone as dt_timezone

import pytest
from django.urls import reverse

from documents.models import Redaction
from documents.tests.factories import make_document, make_redaction


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="pass12345")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_atom_feed_requires_login(client):
    response = client.get(reverse("changes_feed_atom"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_atom_feed_content_type_is_atom(auth_client):
    make_redaction(
        make_document(slug="f1", official_number="1", title="Акт"),
        redaction_date=date(2024, 1, 1),
    ).publish()
    response = auth_client.get(reverse("changes_feed_atom"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/atom+xml")


@pytest.mark.django_db
def test_atom_feed_lists_published_excludes_drafts(auth_client):
    make_redaction(
        make_document(slug="pub", official_number="1", title="Опубликованный акт"),
        redaction_date=date(2024, 1, 1),
    ).publish()
    make_redaction(
        make_document(slug="draft", official_number="2", title="Черновой акт"),
        redaction_date=date(2024, 1, 1),
    )  # остаётся черновиком
    content = auth_client.get(reverse("changes_feed_atom")).content.decode()
    assert "Опубликованный акт" in content
    assert "Черновой акт" not in content


@pytest.mark.django_db
def test_atom_feed_entry_links_to_diff_when_prev_exists(auth_client):
    doc = make_document(slug="hist", official_number="1", title="Акт с историей")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    old.publish()
    make_redaction(doc, redaction_date=date(2024, 6, 1)).publish()
    content = auth_client.get(reverse("changes_feed_atom")).content.decode()
    # запись новой редакции ведёт на diff с предыдущей опубликованной
    assert reverse("redaction_diff", args=["hist", old.pk]) in content


@pytest.mark.django_db
def test_atom_feed_entry_links_to_document_when_no_prev(auth_client):
    make_redaction(
        make_document(slug="single", official_number="1", title="Без истории"),
        redaction_date=date(2024, 1, 1),
    ).publish()
    content = auth_client.get(reverse("changes_feed_atom")).content.decode()
    assert reverse("document_detail", args=["single"]) in content
    assert "diff" not in content  # ссылок на сравнение нет


@pytest.mark.django_db
def test_atom_feed_orders_newest_first(auth_client):
    doc_a = make_document(slug="a", official_number="1", title="Акт А")
    doc_b = make_document(slug="b", official_number="2", title="Акт Б")
    ra = make_redaction(doc_a, redaction_date=date(2024, 1, 1))
    ra.publish()
    rb = make_redaction(doc_b, redaction_date=date(2023, 1, 1))
    rb.publish()
    # А опубликован позже Б — независимо от redaction_date
    Redaction.objects.filter(pk=ra.pk).update(
        published_at=datetime(2026, 6, 2, 12, 0, tzinfo=dt_timezone.utc)
    )
    Redaction.objects.filter(pk=rb.pk).update(
        published_at=datetime(2026, 6, 1, 12, 0, tzinfo=dt_timezone.utc)
    )
    content = auth_client.get(reverse("changes_feed_atom")).content.decode()
    assert content.index("Акт А") < content.index("Акт Б")


@pytest.mark.django_db
def test_atom_feed_caps_items(auth_client, monkeypatch):
    from documents import feeds

    monkeypatch.setattr(feeds, "MAX_ITEMS", 2)
    for i in range(3):
        make_redaction(
            make_document(slug=f"cap{i}", official_number=str(i), title=f"Акт {i}"),
            redaction_date=date(2024, 1, 1),
        ).publish()
    content = auth_client.get(reverse("changes_feed_atom")).content.decode()
    assert content.count("<entry>") == 2
