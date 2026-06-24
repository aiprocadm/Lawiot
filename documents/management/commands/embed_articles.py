"""Бэкфилл семантических эмбеддингов статей (AI-срез 4).

Вне request-пути: модель sentence-transformers грузится здесь, не в вебе.
По умолчанию эмбедит только статьи без вектора; `--all` — переэмбедить всё.
Идемпотентна.
"""

from django.core.management.base import BaseCommand

from documents.models import Article, Redaction
from search.embeddings import embed_passages

_BATCH = 64


class Command(BaseCommand):
    help = "Считает эмбеддинги статей текущих опубликованных редакций (для семантического поиска)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Переэмбедить все статьи, а не только без вектора.",
        )

    def handle(self, *args, **options):
        qs = Article.objects.filter(
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        if not options["all"]:
            qs = qs.filter(embedding__isnull=True)
        qs = qs.order_by("pk")

        total = 0
        batch = []
        for article in qs.iterator(chunk_size=_BATCH):
            batch.append(article)
            if len(batch) >= _BATCH:
                total += self._embed_batch(batch)
                batch = []
        if batch:
            total += self._embed_batch(batch)

        self.stdout.write(self.style.SUCCESS(f"Заэмбеддено статей: {total}"))

    def _embed_batch(self, articles):
        vectors = embed_passages([a.text for a in articles])
        for article, vector in zip(articles, vectors, strict=True):
            article.embedding = vector
        Article.objects.bulk_update(articles, ["embedding"])
        return len(articles)
