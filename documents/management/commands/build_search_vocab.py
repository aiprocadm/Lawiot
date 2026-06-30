"""Сборка словаря словоформ корпуса для исправления опечаток (did-you-mean).

Вне request-пути. Идемпотентна: полностью пересобирает SearchVocab из текста
статей текущих опубликованных редакций. По образцу embed_articles.
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from documents.models import Article, Redaction, SearchVocab
from search.suggest import tokenize

_BATCH = 1000


class Command(BaseCommand):
    help = "Строит словарь словоформ корпуса для исправления опечаток (did-you-mean)."

    def add_arguments(self, parser):
        parser.add_argument("--min-len", type=int, default=4, help="Минимальная длина слова.")
        parser.add_argument(
            "--min-freq", type=int, default=2, help="Минимальная частота слова в корпусе."
        )

    def handle(self, *args, **options):
        min_len = options["min_len"]
        min_freq = options["min_freq"]

        counter: Counter[str] = Counter()
        texts = (
            Article.objects.filter(
                redaction__is_current=True,
                redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
            )
            .values_list("text", flat=True)
            .iterator(chunk_size=200)
        )
        articles = 0
        for text in texts:
            articles += 1
            for token in tokenize(text):
                if len(token) >= min_len:
                    counter[token] += 1

        rows = [
            SearchVocab(word=word, frequency=freq)
            for word, freq in counter.items()
            if freq >= min_freq
        ]
        with transaction.atomic():
            SearchVocab.objects.all().delete()
            SearchVocab.objects.bulk_create(rows, batch_size=_BATCH)

        self.stdout.write(
            self.style.SUCCESS(f"Статей обработано: {articles}; слов в словаре: {len(rows)}")
        )
