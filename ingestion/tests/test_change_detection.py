from datetime import date

import httpx
import pytest

from ingestion.parsing import html_to_text
from ingestion.services import compute_text_hash, text_digest

# Два HTML, различающиеся ТОЛЬКО несущественным токеном в разметке
# (span без текста → html_to_text даёт идентичный текст).
HTML_A = b"<html><body><span id='t' data-v='111'></span><p>Statya 1. Celi</p><p>tekst</p></body></html>"
HTML_B = b"<html><body><span id='t' data-v='999'></span><p>Statya 1. Celi</p><p>tekst</p></body></html>"
# HTML с реально другим текстом.
HTML_C = b"<html><body><span id='t' data-v='111'></span><p>Statya 1. Celi</p><p>drugoy tekst</p></body></html>"


def _client_returning(content, content_type="text/html"):
    def handler(request):
        return httpx.Response(200, headers={"content-type": content_type}, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_text_hash_ignores_markup_churn():
    assert compute_text_hash(HTML_A, "text/html") == compute_text_hash(HTML_B, "text/html")


def test_text_hash_detects_real_text_change():
    assert compute_text_hash(HTML_A, "text/html") != compute_text_hash(HTML_C, "text/html")


def test_text_digest_matches_compute_text_hash():
    assert text_digest(html_to_text(HTML_A, "text/html")) == compute_text_hash(HTML_A, "text/html")


@pytest.mark.django_db
def test_store_raw_source_sets_text_hash():
    from ingestion.services import store_raw_source

    rs = store_raw_source("k", HTML_A, "text/html", "https://e.test/")
    assert rs.text_hash == compute_text_hash(HTML_A, "text/html")
    assert rs.content_hash  # сырой хэш по-прежнему заполнен


@pytest.mark.django_db
def test_text_changed_new_then_same():
    from ingestion.services import store_raw_source, text_changed

    h = compute_text_hash(HTML_A, "text/html")
    assert text_changed("k", h) is True
    store_raw_source("k", HTML_A, "text/html", "", text_hash=h)
    assert text_changed("k", h) is False
    assert text_changed("k", compute_text_hash(HTML_C, "text/html")) is True


@pytest.mark.django_db
def test_ingest_target_skips_on_markup_only_churn():
    from documents.tests.factories import make_document
    from ingestion.models import IngestionJob, RawSource
    from ingestion.services import IngestionTarget, ingest_target

    doc = make_document(slug="churn", official_number="x")
    t = IngestionTarget(document=doc, url="https://e.test/x", target_key="churn")
    first = ingest_target(t, client=_client_returning(HTML_A))
    second = ingest_target(t, client=_client_returning(HTML_B))  # отличается только токеном
    assert first.status == IngestionJob.Status.SUCCESS
    assert second.status == IngestionJob.Status.SKIPPED
    assert RawSource.objects.filter(target_key="churn").count() == 1


# Две сводные редакции одного акта. R2 = изменён текст ст.1 + новая дата поправки.
R1_HTML = (
    "<h1>Кодекс</h1>"
    "<p>(В редакции Федерального закона от 29.12.2025 № 500-ФЗ)</p>"
    "<p>Статья 1. Предмет</p><p>старый текст</p>"
    "<p>Статья 2. Сфера</p><p>текст два</p>"
).encode("utf-8")

R2_HTML = (
    "<h1>Кодекс</h1>"
    "<p>(В редакции Федерального закона от 15.01.2026 № 5-ФЗ)</p>"
    "<p>Статья 1. Предмет</p><p>НОВЫЙ текст</p>"
    "<p>Статья 2. Сфера</p><p>текст два</p>"
).encode("utf-8")


@pytest.mark.django_db
def test_second_redaction_publishes_supersedes_and_diffs():
    from documents.diffing import diff_articles
    from documents.models import Redaction
    from documents.tests.factories import make_document
    from ingestion.models import IngestionJob
    from ingestion.services import IngestionTarget, ingest_target

    doc = make_document(slug="e2e", official_number="500-ФЗ", auto_publish=True)
    t = IngestionTarget(document=doc, url="https://e.test/e2e", target_key="e2e")

    # R1 — первая публикация (текущей нет → гейт пропускает)
    job1 = ingest_target(t, client=_client_returning(R1_HTML))
    assert job1.status == IngestionJob.Status.SUCCESS
    r1 = Redaction.objects.get(document=doc, redaction_date=date(2025, 12, 29))
    assert r1.review_status == Redaction.ReviewStatus.PUBLISHED
    assert r1.is_current is True

    # R2 — новая редакция (новый текст ст.1, новая дата → новый text_hash)
    job2 = ingest_target(t, client=_client_returning(R2_HTML))
    assert job2.status == IngestionJob.Status.SUCCESS
    r2 = Redaction.objects.get(document=doc, redaction_date=date(2026, 1, 15))
    assert r2.review_status == Redaction.ReviewStatus.PUBLISHED
    assert r2.is_current is True
    assert r2.published_at is not None

    r1.refresh_from_db()
    assert r1.is_current is False  # вытеснена

    # diff R1→R2: ст.1 изменена, ст.2 без изменений
    diffs = {
        d.number: d.status
        for d in diff_articles(list(r1.articles.all()), list(r2.articles.all()))
    }
    assert diffs["1"] == "changed"
    assert diffs["2"] == "same"

    # R2 в ленте опубликованных
    published_pks = list(
        Redaction.objects.filter(review_status=Redaction.ReviewStatus.PUBLISHED).values_list(
            "pk", flat=True
        )
    )
    assert r2.pk in published_pks

    # повторный приём тем же R2 → текст не изменился → SKIPPED
    job3 = ingest_target(t, client=_client_returning(R2_HTML))
    assert job3.status == IngestionJob.Status.SKIPPED
