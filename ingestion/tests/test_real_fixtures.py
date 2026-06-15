from datetime import date
from pathlib import Path

import httpx
import pytest

from documents.models import Article, Redaction
from documents.tests.factories import make_document
from ingestion.models import IngestionJob
from ingestion.parsing import parse_document
from ingestion.services import IngestionTarget, ingest_target

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures_raw"


def _client_returning(content, content_type="text/html"):
    """Сетево-изолированный httpx-клиент, отдающий заранее заданный ответ."""

    def handler(request):
        return httpx.Response(200, headers={"content-type": content_type}, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.skipif(
    not (FIXTURES / "tk_rf_real.html").exists(),
    reason="реальная фикстура ТК РФ не захвачена",
)
def test_tk_rf_real_fixture_structure():
    # Фикстура — АКТУАЛЬНАЯ редакция (doc_itself&print=1 без rdk, захват 2026-06-11):
    # 15 разделов, 70 глав, 538 статей, из них 114 с дробными номерами.
    content = (FIXTURES / "tk_rf_real.html").read_bytes()
    parsed = parse_document(content, "text/html")
    sections = [n for n in parsed.articles if n.kind == "section"]
    chapters = [n for n in parsed.articles if n.kind == "chapter"]
    articles = [n for n in parsed.articles if n.kind == "article"]
    # Консервативные нижние границы: будущие правки могут менять состав.
    assert len(sections) >= 14
    assert len(chapters) >= 63
    assert len(articles) >= 450
    assert all(a.number for a in articles)
    assert all(a.parent_order is not None for a in articles)  # без «сирот»
    assert "кодекс" in parsed.title.lower()
    # Надстрочная нумерация ИПС (span.W9) собрана в дробные номера.
    assert any(c.number == "49.1" for c in chapters)  # дистанционные работники
    assert any(a.number == "312.1" for a in articles)


@pytest.mark.skipif(
    not (FIXTURES / "sout_426fz_real.html").exists(),
    reason="реальная фикстура 426-ФЗ не захвачена",
)
def test_sout_426fz_real_fixture_structure():
    # Плоский ФЗ без разделов: 4 главы, 28 статей (актуальная редакция).
    content = (FIXTURES / "sout_426fz_real.html").read_bytes()
    parsed = parse_document(content, "text/html")
    sections = [n for n in parsed.articles if n.kind == "section"]
    chapters = [n for n in parsed.articles if n.kind == "chapter"]
    articles = [n for n in parsed.articles if n.kind == "article"]
    assert sections == []
    assert len(chapters) == 4
    assert len(articles) >= 27
    assert all(a.parent_order is not None for a in articles)
    # Шапка ИПС «ФЕДЕРАЛЬНЫЙ ЗАКОН» не должна затмить название акта.
    assert "специальной оценке условий труда" in parsed.title.lower()


@pytest.mark.skipif(
    not (FIXTURES / "prof_10fz_real.html").exists(),
    reason="реальная фикстура 10-ФЗ не захвачена",
)
def test_prof10fz_real_fixture_structure():
    # ФЗ с главами РИМСКИМИ цифрами (Глава I … Глава VI): 6 глав, 33 статьи.
    # Раньше CHAPTER_RE знал только арабские номера → статьи висели «сиротами».
    content = (FIXTURES / "prof_10fz_real.html").read_bytes()
    parsed = parse_document(content, "text/html")
    sections = [n for n in parsed.articles if n.kind == "section"]
    chapters = [n for n in parsed.articles if n.kind == "chapter"]
    articles = [n for n in parsed.articles if n.kind == "article"]
    assert sections == []
    assert [c.number for c in chapters] == ["I", "II", "III", "IV", "V", "VI"]
    assert len(articles) >= 33
    assert all(a.parent_order is not None for a in articles)  # без «сирот»
    assert "профессиональных союзах" in parsed.title.lower()


@pytest.mark.skipif(
    not (FIXTURES / "tk_rf_real.html").exists(),
    reason="реальная фикстура ТК РФ не захвачена",
)
def test_real_tk_rf_redaction_date_is_latest_amendment():
    content = (FIXTURES / "tk_rf_real.html").read_bytes()
    parsed = parse_document(content, "text/html")
    assert parsed.detected_redaction_date == date(2025, 12, 29)


@pytest.mark.django_db
@pytest.mark.skipif(
    not (FIXTURES / "tk_rf_real.html").exists(),
    reason="реальная фикстура ТК РФ не захвачена",
)
def test_real_tk_rf_auto_publishes_consolidated_redaction():
    """Сквозная приёмка §17 на ЖИВОЙ фикстуре ТК РФ: при auto_publish=True конвейер
    сам публикует свежую сводную редакцию (дата = последняя инкорпорированная поправка),
    минуя куратора, с пройденным гейтом безопасности. Это и есть dry-run, обосновывающий
    включение auto_publish=True для tk-rf в сиде (documents/seed/labor_law.py)."""
    content = (FIXTURES / "tk_rf_real.html").read_bytes()
    doc = make_document(slug="tk-rf", official_number="197-ФЗ", auto_publish=True)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)

    job = ingest_target(target, client=_client_returning(content))

    assert job.status == IngestionJob.Status.SUCCESS
    red = Redaction.objects.get(document=doc)
    assert red.review_status == Redaction.ReviewStatus.PUBLISHED
    assert red.is_current is True
    assert red.published_at is not None
    # дата редакции вычислена из цитат-поправок, а не из плейсхолдера
    assert red.redaction_date == date(2025, 12, 29)
    # опубликована вся сводная редакция, а не обрезок (гейт AUTOPUBLISH_MIN_RATIO)
    assert red.articles.filter(kind=Article.Kind.ARTICLE).count() >= 450


@pytest.mark.django_db
@pytest.mark.skipif(
    not (FIXTURES / "sout_426fz_real.html").exists(),
    reason="реальная фикстура 426-ФЗ не захвачена",
)
def test_real_sout426_ingest_creates_clean_draft():
    """Приёмка парсера на 2-м акте корпуса (426-ФЗ СОУТ): сквозной ingest_target на
    ЖИВОЙ фикстуре при auto_publish=False даёт ЧИСТЫЙ ЧЕРНОВИК (не публикует) с
    корректной структурой — 4 главы, ≥27 статей, без «сирот». Это и есть приёмка,
    обосновывающая включение auto_ingest=True для sout-426-fz в сиде (черновики для
    куратора, без авто-публикации)."""
    content = (FIXTURES / "sout_426fz_real.html").read_bytes()
    doc = make_document(
        slug="sout-426-fz",
        doc_type="federal_law",
        title="О специальной оценке условий труда",
        official_number="426-ФЗ",
        auto_publish=False,
    )
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)

    job = ingest_target(target, client=_client_returning(content))

    assert job.status == IngestionJob.Status.SUCCESS
    red = Redaction.objects.get(document=doc)
    # auto_publish=False → остаётся черновиком, текущим не становится
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.is_current is False
    assert red.articles.filter(kind=Article.Kind.ARTICLE).count() >= 27
    assert red.articles.filter(kind=Article.Kind.CHAPTER).count() == 4
    # без «сирот»: у каждой статьи есть родительская глава
    assert not red.articles.filter(kind=Article.Kind.ARTICLE, parent__isnull=True).exists()


@pytest.mark.django_db
@pytest.mark.skipif(
    not (FIXTURES / "sout_426fz_real.html").exists(),
    reason="реальная фикстура 426-ФЗ не захвачена",
)
def test_real_sout426_links_to_tk_rf_by_name():
    """Закрывает пробой §9: 426-ФЗ упоминает «Трудовой кодекс» по имени (а не «197-ФЗ»).
    Когда tk-rf уже в корпусе, сквозной ingest_target должен создать резолвленную
    suggested-связь 426-ФЗ → ТК РФ через find_named_citations."""
    from documents.models import Link

    tk = make_document(slug="tk-rf", title="Трудовой кодекс Российской Федерации",
                       official_number="197-ФЗ")
    content = (FIXTURES / "sout_426fz_real.html").read_bytes()
    doc = make_document(slug="sout-426-fz", doc_type="federal_law",
                        title="О специальной оценке условий труда",
                        official_number="426-ФЗ", auto_publish=False)
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)

    ingest_target(target, client=_client_returning(content))

    link = Link.objects.get(from_document=doc, to_document=tk)
    assert link.link_type == Link.LinkType.REFERENCES
    assert link.origin == Link.Origin.AUTO
    assert link.status == Link.Status.SUGGESTED
    assert "кодекс" in link.context.lower()


@pytest.mark.django_db
@pytest.mark.skipif(
    not (FIXTURES / "prof_10fz_real.html").exists(),
    reason="реальная фикстура 10-ФЗ не захвачена",
)
def test_real_prof10_ingest_creates_clean_draft():
    """Приёмка парсера на 3-м акте корпуса (10-ФЗ о профсоюзах, главы римскими
    цифрами): сквозной ingest_target на ЖИВОЙ фикстуре при auto_publish=False даёт
    ЧИСТЫЙ ЧЕРНОВИК с корректной структурой — 6 глав, ≥33 статьи, без «сирот».
    Обосновывает auto_ingest=True для prof-10-fz в сиде (черновики для куратора)."""
    content = (FIXTURES / "prof_10fz_real.html").read_bytes()
    doc = make_document(
        slug="prof-10-fz",
        doc_type="federal_law",
        title="О профессиональных союзах, их правах и гарантиях деятельности",
        official_number="10-ФЗ",
        auto_publish=False,
    )
    target = IngestionTarget(document=doc, url="http://x/", target_key=doc.slug)

    job = ingest_target(target, client=_client_returning(content))

    assert job.status == IngestionJob.Status.SUCCESS
    red = Redaction.objects.get(document=doc)
    # auto_publish=False → остаётся черновиком, текущим не становится
    assert red.review_status == Redaction.ReviewStatus.DRAFT
    assert red.is_current is False
    assert red.articles.filter(kind=Article.Kind.ARTICLE).count() >= 33
    assert red.articles.filter(kind=Article.Kind.CHAPTER).count() == 6
    # без «сирот»: у каждой статьи есть родительская глава
    assert not red.articles.filter(kind=Article.Kind.ARTICLE, parent__isnull=True).exists()
