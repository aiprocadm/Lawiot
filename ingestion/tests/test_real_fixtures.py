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
