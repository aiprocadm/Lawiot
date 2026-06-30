import pytest
from django.contrib.postgres.search import TrigramSimilarity

from documents.models import SearchVocab


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
