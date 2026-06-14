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
