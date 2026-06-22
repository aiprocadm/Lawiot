from assistant.citations import (
    allowed_article_numbers,
    cited_article_numbers,
    unverified_citations,
)
from assistant.retrieval import RetrievedArticle


def _art(label):
    return RetrievedArticle("ТК", label, "st-x", "/doc/tk/#st-x", "текст", 0.5)


def test_cited_article_numbers_finds_various_forms():
    text = "См. Статья 127 и статьёй 81, а также ст. 312.1."
    assert cited_article_numbers(text) == {"127", "81", "312.1"}


def test_allowed_article_numbers_from_labels():
    arts = [_art("Статья 127"), _art("Статья 312.1"), _art("Приложение 1")]
    assert allowed_article_numbers(arts) == {"127", "312.1"}


def test_unverified_is_cited_minus_allowed():
    arts = [_art("Статья 127")]
    text = "Согласно Статья 127 и Статья 999, …"
    assert unverified_citations(text, arts) == ["999"]


def test_unverified_empty_when_all_in_set():
    arts = [_art("Статья 127"), _art("Статья 81")]
    text = "Статья 127 и статьёй 81 регулируют это."
    assert unverified_citations(text, arts) == []
