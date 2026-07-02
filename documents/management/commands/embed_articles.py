"""Бэкфилл семантических эмбеддингов статей (AI-срез 4).

Вне request-пути: модель sentence-transformers грузится здесь, не в вебе.
По умолчанию эмбедит только статьи без вектора; `--all` — переэмбедить всё.
Идемпотентна. Обычный путь — авто-задача при publish() (search.tasks);
команда остаётся для первичного бэкфилла и ручного ремонта.
"""

from django.core.management.base import BaseCommand

from documents.models import Article, Redaction
from search.tasks import embed_queryset


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
        total = embed_queryset(qs.order_by("pk"))
        self.stdout.write(self.style.SUCCESS(f"Заэмбеддено статей: {total}"))
