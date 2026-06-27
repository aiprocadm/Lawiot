import logging
from datetime import date, datetime, timezone

import httpx
import pytest

from documents.models import Article, Document, Redaction
from documents.tests.factories import make_article, make_document, make_redaction
from ingestion.models import IngestionJob, RawSource
from ingestion.parsing import parse_document
from ingestion.services import (
    IngestionTarget,
    PublishedRedactionExists,
    ReparseYieldedNothing,
    _is_safe_to_publish,
    compute_hash,
    create_draft_from_parsed,
    import_manual,
    ingest_target,
    reparse_redaction,
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
def test_create_draft_creates_articles_with_anchors():
    doc = make_document(slug="d1", official_number="1")
    parsed = parse_document("Статья 81. Расторжение\nтекст статьи".encode("utf-8"), "text/plain")
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
    assert r1.pk == r2.pk  # та же редакция (upsert)
    assert Redaction.objects.filter(document=doc).count() == 1
    assert r2.articles.count() == 1  # статьи не задублировались


@pytest.mark.django_db
def test_create_draft_never_overwrites_published():
    doc = make_document(slug="d3", official_number="3")
    published = make_redaction(doc, redaction_date=date(2024, 1, 1), full_text="старое")
    published.publish()
    parsed = parse_document("Статья 1. A\nновое".encode("utf-8"), "text/plain")
    with pytest.raises(PublishedRedactionExists):
        create_draft_from_parsed(doc, parsed, redaction_date=date(2024, 1, 1))
    published.refresh_from_db()
    assert published.full_text == "старое"  # не перезаписано


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
    assert RawSource.objects.filter(target_key="tk2").count() == 1  # дубль не сохранён
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
    assert Redaction.objects.filter(document=doc).count() == 0  # ничего не создано


@pytest.mark.django_db
def test_ingest_target_skips_when_published_redaction_blocks_same_date():
    doc = make_document(slug="tk4", official_number="z")
    # Уже есть опубликованная редакция на сегодняшнюю дату → черновик создать нельзя.
    # HTML без цитаты-закона → дата редакции = «сегодня» → совпадение с published.
    today = datetime.now(timezone.utc).date()
    published = make_redaction(doc, redaction_date=today, full_text="официальное")
    published.publish()
    target = IngestionTarget(document=doc, url="https://e.test/tk", target_key="tk4")
    job = ingest_target(target, client=_client_returning(HTML))
    # Та же дата уже опубликована — обновлять нечего, это не ошибка, а пропуск (§6).
    assert job.status == IngestionJob.Status.SKIPPED
    assert not job.error
    published.refresh_from_db()
    assert published.full_text == "официальное"  # опубликованное не перезаписано
    # Сырьё всё равно сохранено (change-detection прошла до создания черновика).
    assert RawSource.objects.filter(target_key="tk4").count() == 1


@pytest.mark.django_db
def test_import_manual_creates_draft_from_text():
    doc = make_document(slug="man", official_number="m")
    content = "Статья 1. Общие положения\nНастоящий акт регулирует.".encode("utf-8")
    red = import_manual(doc, content=content, content_type="text/plain")
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.articles.get().number == "1"
    assert RawSource.objects.filter(target_key="manual:man").count() == 1


@pytest.mark.django_db
def test_ingest_target_extracts_suggested_links():
    from documents.models import Link

    src = make_document(slug="ing-src", official_number="197-ФЗ")
    make_document(slug="ing-tgt", official_number="125-ФЗ")
    html = "<p>Регулируется Федеральным законом № 125-ФЗ.</p>".encode("utf-8")
    target = IngestionTarget(document=src, url="https://e.test/x", target_key="ing-src")
    job = ingest_target(target, client=_client_returning(html))
    assert job.status == IngestionJob.Status.SUCCESS
    assert Link.objects.filter(
        from_document=src, status=Link.Status.SUGGESTED, origin=Link.Origin.AUTO
    ).exists()


@pytest.mark.django_db
def test_import_manual_extracts_suggested_links():
    from documents.models import Link

    src = make_document(slug="man-src", official_number="197-ФЗ")
    make_document(slug="man-tgt", official_number="125-ФЗ")
    content = "Статья 1. Сфера\nПрименяется вместе с 125-ФЗ.".encode("utf-8")
    import_manual(src, content=content, content_type="text/plain")
    assert Link.objects.filter(from_document=src, status=Link.Status.SUGGESTED).exists()


@pytest.mark.django_db
def test_import_manual_logs_when_link_extraction_fails(monkeypatch, caplog):
    # Сбой извлечения связей вторичен: черновик сохраняется (деградация), но
    # ошибка больше не проглатывается молча — пишется в лог с трейсбеком.
    import ingestion.services as svc

    def boom(_redaction):
        raise RuntimeError("link boom")

    monkeypatch.setattr(svc, "extract_links_for_redaction", boom)
    doc = make_document(slug="man-fail", official_number="mf")
    content = "Статья 1. Общие положения\nТекст акта.".encode("utf-8")

    # Логгер ingestion настроен с propagate=False — подключаем caplog напрямую.
    svc_logger = logging.getLogger("ingestion.services")
    svc_logger.addHandler(caplog.handler)
    svc_logger.setLevel(logging.WARNING)
    try:
        red = import_manual(doc, content=content, content_type="text/plain")
    finally:
        svc_logger.removeHandler(caplog.handler)

    assert red.review_status == Redaction.ReviewStatus.DRAFT  # черновик создан
    assert "import_manual" in caplog.text
    assert "link boom" in caplog.text  # трейсбек исходной ошибки


@pytest.mark.django_db
def test_reparse_restores_articles_from_raw():
    doc = Document.objects.create(
        doc_type="federal_law", title="Тест", official_number="1-ФЗ", slug="1-fz"
    )
    red = import_manual(doc, content="Статья 1. Первая.\nСтатья 2. Вторая.".encode("utf-8"))
    assert red.articles.count() == 2
    red.articles.filter(number="2").delete()  # «потеряли» статью
    assert red.articles.count() == 1
    reparse_redaction(red)  # переразбор из того же RawSource
    red.refresh_from_db()
    assert red.articles.count() == 2  # восстановлено


@pytest.mark.django_db
def test_reparse_zero_articles_does_not_wipe():
    doc = Document.objects.create(
        doc_type="federal_law", title="Тест", official_number="2-ФЗ", slug="2-fz"
    )
    raw = RawSource.objects.create(
        target_key="manual:2-fz",
        content="Текст без статей".encode("utf-8"),
        content_hash="x",
        content_type="text/plain",
    )
    red = Redaction.objects.create(document=doc, redaction_date="2026-01-01", raw_source=raw)
    Article.objects.create(redaction=red, number="1", text="была статья", order=0)
    with pytest.raises(ReparseYieldedNothing):
        reparse_redaction(red)
    red.refresh_from_db()
    assert red.articles.count() == 1  # не затёрли


@pytest.mark.django_db
def test_reparse_without_raw_raises():
    doc = Document.objects.create(
        doc_type="federal_law", title="Тест", official_number="3-ФЗ", slug="3-fz"
    )
    red = Redaction.objects.create(document=doc, redaction_date="2026-01-01", raw_source=None)
    with pytest.raises(ValueError):
        reparse_redaction(red)


@pytest.mark.django_db
def test_create_draft_persists_hierarchy():
    from documents.models import Article, Document
    from ingestion.parsing import parse_document
    from ingestion.services import create_draft_from_parsed

    html = (
        "<html><body>"
        "Закон о труде\nРаздел I. Общие положения\nГлава 1. Начала\n"
        "Статья 1. Цели\nТекст статьи 1.\n"
        "</body></html>"
    ).encode()
    doc = Document.objects.create(slug="hier-test", doc_type=Document.DocType.OTHER, title="t")
    parsed = parse_document(html, "text/html")
    redaction = create_draft_from_parsed(doc, parsed)
    section = redaction.articles.get(kind=Article.Kind.SECTION, number="I")
    chapter = redaction.articles.get(kind=Article.Kind.CHAPTER, number="1")
    article = redaction.articles.get(kind=Article.Kind.ARTICLE, number="1")
    assert chapter.parent_id == section.id
    assert article.parent_id == chapter.id
    assert article.anchor == "st-1"


def _redaction_with_n_articles(n, **kwargs):
    red = make_redaction(**kwargs)
    for i in range(n):
        make_article(redaction=red, number=str(i + 1), order=i + 1)
    return red


@pytest.mark.django_db
def test_gate_blocks_zero_articles_and_empty_text():
    new = make_redaction(full_text="")
    assert _is_safe_to_publish(new, None) is False


@pytest.mark.django_db
def test_gate_allows_first_redaction_with_articles():
    new = _redaction_with_n_articles(3)
    assert _is_safe_to_publish(new, None) is True


@pytest.mark.django_db
def test_gate_allows_unstructured_text_when_no_current():
    new = make_redaction(full_text="Длинный неструктурированный текст акта.")
    assert _is_safe_to_publish(new, None) is True


@pytest.mark.django_db
def test_gate_blocks_sharp_drop_vs_current():
    doc = make_document()
    current = _redaction_with_n_articles(10, document=doc, redaction_date=date(2023, 1, 1))
    new = _redaction_with_n_articles(3, document=doc, redaction_date=date(2024, 1, 1))
    assert _is_safe_to_publish(new, current) is False  # 3 < 0.8 * 10


@pytest.mark.django_db
def test_gate_allows_equal_or_more_articles():
    doc = make_document()
    current = _redaction_with_n_articles(10, document=doc, redaction_date=date(2023, 1, 1))
    same = _redaction_with_n_articles(10, document=doc, redaction_date=date(2024, 1, 1))
    more = _redaction_with_n_articles(12, document=doc, redaction_date=date(2025, 1, 1))
    assert _is_safe_to_publish(same, current) is True
    assert _is_safe_to_publish(more, current) is True


# HTML с цитатой поправки (→ дата редакции 15.03.2024) и одной статьёй.
HTML_DATED = (
    "<h1>Кодекс</h1>"
    "<p>(В редакции Федерального закона от 15.03.2024 № 50-ФЗ)</p>"
    "<p>Статья 1. Предмет</p><p>текст статьи</p>"
).encode("utf-8")


@pytest.mark.django_db
def test_ingest_sets_real_redaction_date():
    doc = make_document(slug="rd", official_number="50-ФЗ", auto_publish=False)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    ingest_target(target, client=_client_returning(HTML_DATED))
    red = Redaction.objects.get(document=doc)
    assert red.redaction_date == date(2024, 3, 15)
    assert red.review_status == Redaction.ReviewStatus.DRAFT  # auto_publish off → черновик


@pytest.mark.django_db
def test_auto_publish_publishes_safe_redaction():
    doc = make_document(slug="ap1", official_number="50-ФЗ", auto_publish=True)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    job = ingest_target(target, client=_client_returning(HTML_DATED))
    red = Redaction.objects.get(document=doc)
    assert red.review_status == Redaction.ReviewStatus.PUBLISHED
    assert red.is_current is True
    assert red.published_at is not None
    assert job.status == IngestionJob.Status.SUCCESS


@pytest.mark.django_db
def test_auto_publish_skips_when_no_date():
    # HTML без цитаты-закона → даты нет → не публикуем, остаётся черновик.
    html = b"<h1>Akt</h1><p>\xd0\xa1\xd1\x82\xd0\xb0\xd1\x82\xd1\x8c\xd1\x8f 1. X</p><p>t</p>"
    doc = make_document(slug="ap2", official_number="2", auto_publish=True)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    ingest_target(target, client=_client_returning(html))
    red = Redaction.objects.get(document=doc)
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.is_current is False


@pytest.mark.django_db
def test_auto_publish_blocked_by_gate_keeps_draft():
    doc = make_document(slug="ap3", official_number="50-ФЗ", auto_publish=True)
    # текущая опубликованная редакция с 10 статьями
    current = make_redaction(
        document=doc,
        redaction_date=date(2023, 1, 1),
        review_status=Redaction.ReviewStatus.PUBLISHED,
        is_current=True,
    )
    for i in range(10):
        make_article(redaction=current, number=str(i + 1), order=i + 1)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    ingest_target(target, client=_client_returning(HTML_DATED))  # 1 статья < 0.8*10
    new = Redaction.objects.get(document=doc, redaction_date=date(2024, 3, 15))
    assert new.review_status == Redaction.ReviewStatus.DRAFT
    current.refresh_from_db()
    assert current.is_current is True  # текущая не тронута


@pytest.mark.django_db
def test_ingest_skips_when_same_date_already_published():
    doc = make_document(slug="ap4", official_number="50-ФЗ", auto_publish=True)
    # уже опубликованная редакция на ту же дату, что даст HTML_DATED (15.03.2024)
    make_redaction(
        document=doc,
        redaction_date=date(2024, 3, 15),
        review_status=Redaction.ReviewStatus.PUBLISHED,
        is_current=True,
    )
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)
    job = ingest_target(target, client=_client_returning(HTML_DATED))
    assert job.status == IngestionJob.Status.SKIPPED
