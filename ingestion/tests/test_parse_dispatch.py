from ingestion.parsing import parse_text


def test_decree_dispatches_to_points():
    doc = parse_text("1. Пункт первый.", doc_type="decree")
    assert [n.kind for n in doc.articles] == ["point"]


def test_order_dispatches_to_points():
    doc = parse_text("1. Пункт.", doc_type="order")
    assert doc.articles[0].kind == "point"


def test_default_dispatches_to_codex_structure():
    doc = parse_text("Статья 1. Сфера действия.", doc_type=None)
    assert doc.articles[0].kind == "article"


def test_federal_law_dispatches_to_codex_structure():
    doc = parse_text("Статья 1. Сфера действия.", doc_type="federal_law")
    assert doc.articles[0].kind == "article"
