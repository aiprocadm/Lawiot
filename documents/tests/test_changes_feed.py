"""Тесты ленты изменений (/changes/) — список недавно опубликованных редакций."""

import importlib
from datetime import date, datetime, timezone as dt_timezone

import pytest
from django.apps import apps
from django.urls import reverse
from django.utils import timezone

from documents import views as doc_views
from documents.models import Redaction
from documents.tests.factories import make_document, make_redaction


@pytest.mark.django_db
def test_publish_sets_published_at():
    red = make_redaction()
    assert red.published_at is None
    red.publish()
    red.refresh_from_db()
    assert red.published_at is not None


@pytest.mark.django_db
def test_backfill_migration_fills_published_at_from_redaction_date():
    """Data-миграция 0011: published-строки без published_at получают полночь redaction_date."""
    backfill_mod = importlib.import_module("documents.migrations.0011_backfill_published_at")

    published = make_redaction(redaction_date=date(2023, 5, 10))
    published.publish()
    Redaction.objects.filter(pk=published.pk).update(published_at=None)
    draft = make_redaction(
        make_document(slug="bf-draft", official_number="2"),
        redaction_date=date(2023, 5, 10),
    )

    backfill_mod.backfill_published_at(apps, None)

    published.refresh_from_db()
    draft.refresh_from_db()
    assert published.published_at is not None
    assert timezone.localdate(published.published_at) == date(2023, 5, 10)
    assert draft.published_at is None


@pytest.mark.django_db
def test_feed_requires_login(client):
    response = client.get(reverse("changes_feed"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_feed_empty_state(auth_client):
    response = auth_client.get(reverse("changes_feed"))
    assert response.status_code == 200
    assert "Изменений пока нет." in response.content.decode()


@pytest.mark.django_db
def test_feed_shows_only_published(auth_client):
    doc = make_document(slug="feed-pub", official_number="1", title="Опубликованный акт")
    make_redaction(doc, redaction_date=date(2024, 1, 1)).publish()

    draft_doc = make_document(slug="feed-draft", official_number="2", title="Черновой акт")
    make_redaction(draft_doc, redaction_date=date(2024, 1, 1))  # остаётся черновиком

    response = auth_client.get(reverse("changes_feed"))
    content = response.content.decode()
    assert "Опубликованный акт" in content
    assert reverse("document_detail", args=["feed-pub"]) in content
    assert "Черновой акт" not in content


@pytest.mark.django_db
def test_feed_orders_by_published_at_desc(auth_client):
    doc_a = make_document(slug="feed-a", official_number="1", title="Акт А")
    doc_b = make_document(slug="feed-b", official_number="2", title="Акт Б")
    red_a = make_redaction(doc_a, redaction_date=date(2024, 1, 1))
    red_a.publish()
    red_b = make_redaction(doc_b, redaction_date=date(2023, 1, 1))
    red_b.publish()
    # А опубликован позже Б — независимо от redaction_date
    Redaction.objects.filter(pk=red_a.pk).update(
        published_at=datetime(2026, 6, 2, 12, 0, tzinfo=dt_timezone.utc)
    )
    Redaction.objects.filter(pk=red_b.pk).update(
        published_at=datetime(2026, 6, 1, 12, 0, tzinfo=dt_timezone.utc)
    )

    response = auth_client.get(reverse("changes_feed"))
    feed = list(response.context["page_obj"].object_list)
    assert [r.pk for r in feed] == [red_a.pk, red_b.pk]


@pytest.mark.django_db
def test_feed_diff_link_only_when_older_published_exists(auth_client):
    doc = make_document(slug="feed-diff", official_number="1", title="Акт с историей")
    old = make_redaction(doc, redaction_date=date(2023, 1, 1))
    old.publish()
    new = make_redaction(doc, redaction_date=date(2024, 6, 1))
    new.publish()

    single_doc = make_document(slug="feed-single", official_number="2", title="Акт без истории")
    make_redaction(single_doc, redaction_date=date(2024, 1, 1)).publish()

    response = auth_client.get(reverse("changes_feed"))
    content = response.content.decode()
    # у новой редакции акта с историей — ссылка на diff с предыдущей опубликованной
    assert reverse("redaction_diff", args=["feed-diff", old.pk]) in content
    assert "что изменилось" in content
    # у единственной редакции второго акта ссылки на diff нет
    assert reverse("redaction_diff", args=["feed-single", 0])[:-2] not in content


@pytest.mark.django_db
def test_feed_diff_link_absent_for_oldest_redaction(auth_client):
    doc = make_document(slug="feed-oldest", official_number="1")
    only = make_redaction(doc, redaction_date=date(2024, 1, 1))
    only.publish()
    response = auth_client.get(reverse("changes_feed"))
    assert "что изменилось" not in response.content.decode()


@pytest.mark.django_db
def test_feed_paginates(auth_client, monkeypatch):
    monkeypatch.setattr(doc_views, "PAGE_SIZE", 2)
    for i in range(3):
        d = make_document(slug=f"feed-p-{i}", official_number=str(i), title=f"Акт {i}")
        make_redaction(d, redaction_date=date(2024, 1, 1)).publish()

    page1 = auth_client.get(reverse("changes_feed"))
    assert page1.context["page_obj"].paginator.count == 3
    assert len(page1.context["page_obj"].object_list) == 2

    page2 = auth_client.get(reverse("changes_feed"), {"page": "2"})
    assert len(page2.context["page_obj"].object_list) == 1
