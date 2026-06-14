from datetime import date
from pathlib import Path

import ingestion
from ingestion.parsing import (
    detect_redaction_date,
    detect_title,
    html_to_text,
    parse_articles,
    parse_document,
    parse_structure,
)

FIXTURES = Path(ingestion.__file__).parent / "fixtures_raw"


def test_html_to_text_strips_tags_scripts_and_head():
    html = b"<head><title>T</title><style>.x{}</style></head><body><h1>Hi</h1><script>x()</script><p>Body</p></body>"
    text = html_to_text(html, "text/html")
    assert "Hi" in text
    assert "Body" in text
    assert "x()" not in text  # script removed
    assert ".x{}" not in text  # style removed
    assert "T" not in text.splitlines()  # head/title removed


def test_html_to_text_converts_ips_superscript_numbering():
    # ИПС (pravo.gov.ru) размечает дробные номера надстрочным индексом:
    # «Статья 312<span class="W9">1</span>.» означает «Статья 312.1.».
    html = (
        '<body><p class="H">Статья 312<span class="W9" style="">1</span>.'
        " Общие положения</p>"
        '<p>в статьях 22<span class="W9">2</span> и 22<span class="W9">3</span> кодекса</p>'
        "</body>"
    ).encode("utf-8")
    text = html_to_text(html, "text/html")
    assert "Статья 312.1. Общие положения" in text.splitlines()
    assert "в статьях 22.2 и 22.3 кодекса" in text


def test_html_to_text_empty_w9_span_does_not_insert_dot():
    html = '<body><p>Текст<span class="W9"></span> продолжение</p></body>'.encode("utf-8")
    text = html_to_text(html, "text/html")
    assert "Текст продолжение" in text
    assert ".." not in text


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


def test_detect_title_prefers_act_keyword_line():
    text = (
        "Главная\nПоиск\nОфициальный интернет-портал\n"
        "Трудовой кодекс Российской Федерации\n"
        "Раздел I. Общие положения\nСтатья 1. Цели"
    )
    assert detect_title(text) == "Трудовой кодекс Российской Федерации"


def test_detect_title_falls_back_to_first_meaningful_line():
    text = "Некий акт без ключевых слов\nСтатья 1. Что-то"
    assert detect_title(text) == "Некий акт без ключевых слов"


def test_detect_title_skips_bare_act_type_header():
    # Шапка ИПС: тип акта отдельной строкой, название — следующей.
    text = (
        "РОССИЙСКАЯ ФЕДЕРАЦИЯ\n"
        "ФЕДЕРАЛЬНЫЙ ЗАКОН\n"
        "О специальной оценке условий труда\n"
        "Принят Государственной Думой 23 декабря 2013 года\n"
        "Статья 1. Предмет регулирования\nтекст"
    )
    assert detect_title(text) == "О специальной оценке условий труда"


def test_parse_document_extracts_requisite_hints():
    html = "Федеральный закон от 30.12.2001 N 197-ФЗ\nСтатья 1. Цели".encode()
    parsed = parse_document(html, "text/html")
    assert parsed.detected_number == "197-ФЗ"
    assert parsed.detected_date == "30.12.2001"


def test_parse_structure_uppercase_headers():
    text = "РАЗДЕЛ I. ОБЩИЕ ПОЛОЖЕНИЯ\nГЛАВА 1. НАЧАЛА\nСтатья 1. Цели\nТекст статьи."
    nodes = parse_structure(text)
    kinds = [(n.kind, n.number) for n in nodes]
    assert ("section", "I") in kinds
    assert ("chapter", "1") in kinds
    assert ("article", "1") in kinds


def test_detect_redaction_date_picks_max_citation_date():
    text = (
        "Одобрен 26 декабря 2001 года "
        "(В редакции федеральных законов от 24.07.2002 № 97-ФЗ, "
        "от 29.12.2025 № 999-ФЗ, от 30.06.2006 № 90-ФЗ)"
    )
    assert detect_redaction_date(text) == date(2025, 12, 29)


def test_detect_redaction_date_handles_fkz_and_letter_N():
    text = "часть дополнена (В редакции Федерального конституционного закона от 05.02.2014 N 2-ФКЗ)"
    assert detect_redaction_date(text) == date(2014, 2, 5)


def test_detect_redaction_date_ignores_bare_dates_without_law_number():
    text = "Договор от 01.01.2099 действует со дня подписания."
    assert detect_redaction_date(text) is None


def test_detect_redaction_date_returns_none_when_no_citations():
    assert detect_redaction_date("Статья 1. Без единой цитаты закона.") is None


def test_parse_text_parses_already_normalized_text():
    from ingestion.parsing import parse_text

    text = "Кодекс\nСтатья 1. Цели\nтекст статьи"
    parsed = parse_text(text)
    assert parsed.full_text == text
    assert parsed.title == "Кодекс"
    nums = [a.number for a in parsed.articles if a.kind == "article"]
    assert nums == ["1"]


def test_parse_document_delegates_to_parse_text():
    from ingestion.parsing import parse_document, parse_text

    html = b"<p>\xd0\x9a\xd0\xbe\xd0\xb4\xd0\xb5\xd0\xba\xd1\x81</p><p>\xd0\xa1\xd1\x82\xd0\xb0\xd1\x82\xd1\x8c\xd1\x8f 1. X</p><p>t</p>"
    doc = parse_document(html, "text/html")
    assert doc.full_text == parse_text(doc.full_text).full_text
    assert [a.number for a in doc.articles] == ["1"]
