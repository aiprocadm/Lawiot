"""Грунтованные синонимы: разговорное слово, которого нет в тексте ТК, должно
расширяться в присутствующую юр.формулировку (проверено по фикстуре)."""

from search.lemmas import build_expanded_tsquery


def test_polstavki_expands_to_part_time():
    # «полставки» (лемма «полставка») отсутствует в тексте; юр.форма —
    # «неполное рабочее время».
    q = build_expanded_tsquery("полставки")
    assert q is not None
    assert "неполное" in q and "рабочее" in q and "время" in q


def test_profzabolevanie_expands_to_legal_form():
    q = build_expanded_tsquery("профзаболевание")
    assert q is not None
    assert "профессионального" in q and "заболевания" in q


def test_disciplinarka_expands_to_legal_form():
    q = build_expanded_tsquery("дисциплинарка")
    assert q is not None
    assert "дисциплинарное" in q and "взыскание" in q


def test_matotvetstvennost_expands_to_legal_form():
    q = build_expanded_tsquery("матответственность")
    assert q is not None
    assert "материальной" in q and "ответственности" in q
