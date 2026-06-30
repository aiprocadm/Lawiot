import pytest
from django.contrib.postgres.search import TrigramSimilarity
from django.core.management import call_command

from documents.models import SearchVocab
from documents.tests.factories import make_article, make_document, make_redaction
from search.suggest import suggest_query, tokenize


@pytest.mark.django_db
def test_searchvocab_trigram_similarity_query_works():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    SearchVocab.objects.create(word="отпуск", frequency=5)
    nearest = (
        SearchVocab.objects.annotate(sim=TrigramSimilarity("word", "уволнение"))
        .order_by("-sim")
        .first()
    )
    assert nearest.word == "увольнение"


def test_tokenize_normalizes_and_splits():
    assert tokenize("Увольнение по СОБСТВЕННОМУ; ёлка") == [
        "увольнение",
        "по",
        "собственному",
        "елка",
    ]


@pytest.mark.django_db
def test_build_search_vocab_counts_filters_and_normalizes():
    doc = make_document(slug="tk", title="ТК", official_number="197-ФЗ")
    red = make_redaction(doc, full_text="")
    make_article(
        red,
        number="81",
        title="Расторжение",
        text="увольнение работника. увольнение по статье. ёлка ёлка",
    )
    red.publish()

    call_command("build_search_vocab", "--min-len", "4", "--min-freq", "2")

    words = {v.word: v.frequency for v in SearchVocab.objects.all()}
    assert words.get("увольнение") == 2  # частотное слово сохранено
    assert words.get("елка") == 2  # ё→е нормализовано, посчитано как одно слово
    assert "по" not in words  # короче min-len=4
    assert "работника" not in words  # частота 1 < min-freq=2


@pytest.mark.django_db
def test_suggest_corrects_typo():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    assert suggest_query("уволнение") == "увольнение"


@pytest.mark.django_db
def test_suggest_returns_none_when_all_known():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    assert suggest_query("увольнение") is None


@pytest.mark.django_db
def test_suggest_returns_none_when_no_close_match():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    assert suggest_query("ббббббб") is None


@pytest.mark.django_db
def test_suggest_fixes_only_unknown_token():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    SearchVocab.objects.create(word="работника", frequency=8)
    assert suggest_query("уволнение работника") == "увольнение работника"


@pytest.mark.django_db
def test_suggest_empty_vocab_returns_none():
    assert suggest_query("уволнение") is None


@pytest.mark.django_db
def test_suggest_empty_query_returns_none():
    SearchVocab.objects.create(word="увольнение", frequency=10)
    assert suggest_query("") is None
    assert suggest_query("   ") is None
