from pathlib import Path

import pytest

from ingestion.parsing import parse_document

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures_raw"


@pytest.mark.skipif(
    not (FIXTURES / "tk_rf_real.html").exists(),
    reason="реальная фикстура ТК РФ не захвачена",
)
def test_tk_rf_real_fixture_structure():
    content = (FIXTURES / "tk_rf_real.html").read_bytes()
    parsed = parse_document(content, "text/html")
    sections = [n for n in parsed.articles if n.kind == "section"]
    chapters = [n for n in parsed.articles if n.kind == "chapter"]
    articles = [n for n in parsed.articles if n.kind == "article"]
    # Реальные инварианты ТК РФ (консервативные нижние границы): 14 разделов, 61 глава, 424 статьи.
    assert len(sections) >= 14
    assert len(chapters) >= 60
    assert len(articles) >= 400
    assert all(a.number for a in articles)
    assert "кодекс" in parsed.title.lower()
