from datetime import date, datetime, timezone

import httpx
import pytest

from documents.models import Redaction
from documents.tests.factories import make_document, make_redaction
from ingestion.models import IngestionJob, RawSource
from ingestion.parsing import parse_document
from ingestion.services import (
    IngestionTarget,
    PublishedRedactionExists,
    compute_hash,
    content_changed,
    create_draft_from_parsed,
    import_manual,
    ingest_target,
    store_raw_source,
)

HTML = b"<h1>Kodeks</h1><p>\xd0\xa1\xd1\x82\xd0\xb0\xd1\x82\xd1\x8c\xd1\x8f 81. Uvolnenie</p><p>tekst</p>"
# (HTML с «Статья 81. Uvolnenie» в UTF-8; текст статьи — «tekst».)


def _client_returning(content, content_type="text/html"):
    def handler(request):
        return httpx.Response(200, headers={"content-type": content_type}, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_compute_hash_is_stable():
    assert compute_hash(b"abc") == compute_hash(b"abc")
    assert compute_hash(b"abc") != compute_hash(b"abd")


@pytest.mark.django_db
def test_store_raw_source_sets_hash():
    rs = store_raw_source("k", b"hello", "text/plain", "https://e.test/")
    assert rs.content_hash == compute_hash(b"hello")
    assert RawSource.objects.count() == 1


@pytest.mark.django_db
def test_content_changed_detects_new_then_same():
    assert content_changed("k", compute_hash(b"v1")) is True
    store_raw_source("k", b"v1", "text/plain", "")
    assert content_changed("k", compute_hash(b"v1")) is False
    assert content_changed("k", compute_hash(b"v2")) is True


@pytest.mark.django_db
def test_create_draft_creates_articles_with_anchors():
    doc = make_document(slug="d1", official_number="1")
    parsed = parse_document(
        "Статья 81. Расторжение\nтекст статьи".encode("utf-8"), "text/plain"
    )
    red = create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.is_current is False
    assert red.parser_version == "1.0"
    art = red.articles.get()
    assert art.number == "81"
    assert art.anchor == "st-81"  # anchor сгенерирован в Article.save()


@pytest.mark.django_db
def test_create_draft_is_idempotent_on_same_date():
    doc = make_document(slug="d2", official_number="2")
    parsed = parse_document("Статья 1. A\nx".encode("utf-8"), "text/plain")
    r1 = create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    r2 = create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    assert r1.pk == r2.pk                       # та же редакция (upsert)
    assert Redaction.objects.filter(document=doc).count() == 1
    assert r2.articles.count() == 1             # статьи не задублировались


@pytest.mark.django_db
def test_create_draft_never_overwrites_published():
    doc = make_document(slug="d3", official_number="3")
    published = make_redaction(doc, redaction_date=date(2024, 1, 1), full_text="старое")
    published.publish()
    parsed = parse_document("Статья 1. A\nновое".encode("utf-8"), "text/plain")
    with pytest.raises(PublishedRedactionExists):
        create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    published.refresh_from_db()
    assert published.full_text == "старое"      # не перезаписано


@pytest.mark.django_db
def test_ingest_target_success_creates_draft_and_job():
    doc = make_document(slug="tk", official_number="197-ФЗ")
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk")
    job = ingest_target(target, client=_client_returning(HTML))
    assert job.status == IngestionJob.Status.SUCCESS
    assert job.produced_redaction is not None
    assert job.raw_source is not None
    assert job.finished_at is not None
    red = job.produced_redaction
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.articles.filter(number="81").exists()


@pytest.mark.django_db
def test_ingest_target_skips_unchanged_on_second_run():
    doc = make_document(slug="tk2", official_number="x")
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk2")
    first = ingest_target(target, client=_client_returning(HTML))
    second = ingest_target(target, client=_client_returning(HTML))
    assert first.status == IngestionJob.Status.SUCCESS
    assert second.status == IngestionJob.Status.SKIPPED
    assert RawSource.objects.filter(target_key="tk2").count() == 1   # дубль не сохранён
    assert Redaction.objects.filter(document=doc).count() == 1


@pytest.mark.django_db
def test_ingest_target_quarantines_on_fetch_error():
    doc = make_document(slug="tk3", official_number="y")
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk3")

    def handler(request):
        return httpx.Response(500, content=b"boom")

    job = ingest_target(target, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert job.status == IngestionJob.Status.FAILED
    assert "HTTPStatusError" in job.error
    assert Redaction.objects.filter(document=doc).count() == 0       # ничего не создано


@pytest.mark.django_db
def test_ingest_target_quarantines_but_keeps_raw_when_published_blocks_draft():
    doc = make_document(slug="tk4", official_number="z")
    # Уже есть опубликованная редакция на сегодняшнюю дату → черновик создать нельзя.
    today = datetime.now(timezone.utc).date()
    published = make_redaction(doc, redaction_date=today, full_text="официальное")
    published.publish()
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk4")
    job = ingest_target(target, client=_client_returning(HTML))
    assert job.status == IngestionJob.Status.FAILED
    assert "PublishedRedactionExists" in job.error
    # Карантин, а не тихий пропуск: сырьё сохранено для повторного разбора.
    assert RawSource.objects.filter(target_key="tk4").count() == 1


@pytest.mark.django_db
def test_import_manual_creates_draft_from_text():
    doc = make_document(slug="man", official_number="m")
    content = "Статья 1. Общие положения\nНастоящий акт регулирует.".encode("utf-8")
    red = import_manual(doc, content=content, content_type="text/plain")
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.articles.get().number == "1"
    assert RawSource.objects.filter(target_key="manual:man").count() == 1
