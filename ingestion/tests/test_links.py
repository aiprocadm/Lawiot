from ingestion.links import find_citations


def test_finds_fz_and_fkz_numbers():
    text = "В соответствии с Федеральным законом от 28.12.2013 № 400-ФЗ и 1-ФКЗ."
    numbers = {c.number for c in find_citations(text)}
    assert numbers == {"400-ФЗ", "1-ФКЗ"}


def test_dedups_repeated_numbers():
    text = "См. 197-ФЗ. Также 197-ФЗ применяется здесь."
    cites = find_citations(text)
    assert [c.number for c in cites] == ["197-ФЗ"]


def test_ignores_plain_numbers_and_dates():
    text = "Пункт 5 от 28.12.2013 года, страница 400."
    assert find_citations(text) == []


def test_captures_context_around_citation():
    text = "Изменения внесены Федеральным законом № 125-ФЗ о страховании."
    (cite,) = find_citations(text)
    assert cite.number == "125-ФЗ"
    assert "125-ФЗ" in cite.context
    assert "страховании" in cite.context
