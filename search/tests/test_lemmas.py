"""Юнит-тесты морфологического расширения запроса (без БД)."""

from search import lemmas
from search.lemmas import build_expanded_tsquery, expand_word, has_websearch_operators


def test_expand_word_rebenok_contains_oblique_form():
    forms = expand_word("ребенок")
    assert "ребенок" in forms
    assert "ребенка" in forms  # косвенная форма с беглой гласной
    assert "дети" in forms  # супплетив той же лексемы


def test_expand_word_mat_contains_materi():
    forms = expand_word("мать")
    assert "матери" in forms


def test_expand_word_normalizes_yo_to_e():
    forms = expand_word("ребенок")
    assert all("ё" not in form for form in forms)
    # вход с «ё» тоже нормализуется
    assert "ребенка" in expand_word("ребёнок")


def test_expand_word_latin_garbage_does_not_break():
    assert expand_word("hello") == []
    assert expand_word("abc123") == []
    assert expand_word("") == []


def test_expand_word_hyphenated_does_not_break():
    forms = expand_word("кто-то")
    assert "кто-то" in forms
    # ни одна форма не начинается/кончается дефисом (край '-' = NOT-оператор raw-tsquery)
    assert all(not f.startswith("-") and not f.endswith("-") for f in forms)


def test_expand_word_prostoy_includes_noun_parse():
    # Именной разбор «простой» (score 0.065) не входит в топ-3 —
    # порог по score обязан его сохранить.
    forms = expand_word("простой")
    assert "простоя" in forms  # род. падеж существительного «простой»


def test_build_expanded_tsquery_basic():
    raw = build_expanded_tsquery("ребенок")
    assert raw is not None
    assert "ребенка" in raw
    assert raw.startswith("(") and raw.endswith(")")


def test_build_expanded_tsquery_ands_words():
    raw = build_expanded_tsquery("мать ребенок")
    assert raw is not None
    assert " & " in raw
    assert "матери" in raw
    assert "ребенка" in raw


def test_build_expanded_tsquery_synonyms_zarplata():
    raw = build_expanded_tsquery("зарплата")
    assert raw is not None
    assert "заработная & плата" in raw


def test_build_expanded_tsquery_synonyms_by_lemma():
    # «декрете» — косвенная форма: синоним ищется по лемме «декрет»
    raw = build_expanded_tsquery("декрете")
    assert raw is not None
    assert "беременности" in raw


def test_build_expanded_tsquery_keeps_numeric_tokens():
    raw = build_expanded_tsquery("статья 261")
    assert raw is not None
    assert "261" in raw


def test_build_expanded_tsquery_rejects_unsafe_tokens():
    # латиница — расширение не применяется целиком
    assert build_expanded_tsquery("labor code") is None
    assert build_expanded_tsquery("приказ N77н") is None  # смешанный токен с латиницей


def test_build_expanded_tsquery_drops_lone_specials():
    # одиночный спецсимвол-токен схлопывается в пустоту и пропускается,
    # в raw-строку пользовательский «&» не попадает буквально
    raw = build_expanded_tsquery("ребенок & мать")
    assert raw is not None
    assert "ребенка" in raw and "матери" in raw


def test_build_expanded_tsquery_strips_edge_punctuation():
    raw = build_expanded_tsquery("ребенок,")
    assert raw is not None
    assert "," not in raw


def test_build_expanded_tsquery_only_safe_chars():
    import re

    for query in ("ребенок", "мать дитя", "зарплата", "кто-то", "мрот"):
        raw = build_expanded_tsquery(query)
        assert raw is not None
        assert re.fullmatch(r"[а-яе0-9|&()\s-]+", raw), raw


def test_guard_websearch_operators():
    assert has_websearch_operators('"точная фраза"')
    assert has_websearch_operators("отпуск -ребенок")
    assert has_websearch_operators("мать OR отец")
    assert has_websearch_operators("мать or отец")  # websearch понимает и lowercase
    assert not has_websearch_operators("ребенок")
    assert not has_websearch_operators("кто-то")  # дефис внутри слова — не оператор


def test_guard_disables_expansion():
    assert build_expanded_tsquery("отпуск -ребенок") is None
    assert build_expanded_tsquery('"заработная плата"') is None


def test_morph_analyzer_is_singleton():
    assert lemmas._morph() is lemmas._morph()
