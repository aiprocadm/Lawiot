from pathlib import Path

import ingestion
from ingestion.parsing import html_to_text, parse_articles, parse_document, parse_structure

FIXTURES = Path(ingestion.__file__).parent / "fixtures_raw"


def test_html_to_text_strips_tags_scripts_and_head():
    html = b"<head><title>T</title><style>.x{}</style></head><body><h1>Hi</h1><script>x()</script><p>Body</p></body>"
    text = html_to_text(html, "text/html")
    assert "Hi" in text
    assert "Body" in text
    assert "x()" not in text       # script removed
    assert ".x{}" not in text      # style removed
    assert "T" not in text.splitlines()  # head/title removed


def test_parse_articles_splits_on_headers():
    text = "Статья 80. Заголовок один\nтекст один\nСтатья 81. Заголовок два\nтекст два"
    arts = parse_articles(text)
    assert [a.number for a in arts] == ["80", "81"]
    assert arts[0].title == "Заголовок один"
    assert arts[0].text == "текст один"
    assert arts[0].order == 1
    assert arts[1].order == 2
    assert arts[1].text == "текст два"


def test_parse_articles_handles_decimal_numbers():
    text = "Статья 312.1. Дистанционная работа\nположение"
    arts = parse_articles(text)
    assert arts[0].number == "312.1"
    assert arts[0].title == "Дистанционная работа"


def test_parse_document_on_html_fixture():
    content = (FIXTURES / "sample_tk.html").read_bytes()
    parsed = parse_document(content, "text/html")
    assert parsed.title == "Трудовой кодекс Российской Федерации"
    assert [a.number for a in parsed.articles] == ["80", "81"]
    assert "две недели" in parsed.articles[0].text
    assert "ликвидации организации" in parsed.articles[1].text
    # full_text сохраняет весь нормализованный текст
    assert "Трудовой кодекс" in parsed.full_text
    assert "работодателя" in parsed.full_text


def test_parse_document_accepts_plain_text():
    content = "Статья 1. Общие положения\nНастоящий акт регулирует отношения.".encode("utf-8")
    parsed = parse_document(content, "text/plain")
    assert [a.number for a in parsed.articles] == ["1"]
    assert parsed.articles[0].text == "Настоящий акт регулирует отношения."


SYNTHETIC = """Трудовой кодекс Российской Федерации
Раздел I. Общие положения
Глава 1. Основные начала трудового законодательства
Статья 1. Цели и задачи трудового законодательства
Целями трудового законодательства являются...
Статья 2. Основные принципы
Текст статьи два.
Раздел II. Социальное партнёрство
Глава 2. Общие понятия
Статья 23. Понятие социального партнёрства
Текст статьи 23."""


def test_parse_structure_detects_sections_and_chapters():
    nodes = parse_structure(SYNTHETIC)
    kinds = [(n.kind, n.number) for n in nodes]
    assert ("section", "I") in kinds
    assert ("section", "II") in kinds
    assert ("chapter", "1") in kinds
    assert ("chapter", "2") in kinds
    assert ("article", "1") in kinds
    assert ("article", "23") in kinds


def test_parse_structure_parent_links_and_text():
    nodes = parse_structure(SYNTHETIC)
    by_order = {n.order: n for n in nodes}
    chapter1 = next(n for n in nodes if n.kind == "chapter" and n.number == "1")
    section1 = next(n for n in nodes if n.kind == "section" and n.number == "I")
    article1 = next(n for n in nodes if n.kind == "article" and n.number == "1")
    assert by_order[chapter1.parent_order] is section1
    assert by_order[article1.parent_order] is chapter1
    assert "Целями трудового законодательства" in article1.text
    assert "Статья 2" not in article1.text


def test_parse_structure_flat_act_only_articles():
    flat = "Преамбула акта\nСтатья 1. Первая\nТекст.\nСтатья 2. Вторая\nЕщё текст."
    nodes = parse_structure(flat)
    assert [n.kind for n in nodes] == ["article", "article"]
    assert all(n.parent_order is None for n in nodes)
