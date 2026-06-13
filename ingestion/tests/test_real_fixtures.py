from datetime import date
from pathlib import Path

import pytest

from ingestion.parsing import parse_document

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures_raw"


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
