"""Сводка состояния корпуса — операционная диагностика для куратора.

Печатает: документы (опубликованные/без редакции), редакции (опубл./черновики),
структурные единицы по виду, связи (по статусу, резолвлены/нет), реестр
ожидаемых актов. Только чтение; помогает оценить полноту и найти проблемы.
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from documents.models import Article, Document, Link, PendingAct, Redaction


class Command(BaseCommand):
    help = "Сводка состояния корпуса: акты, редакции, структура, связи, проблемы."

    def handle(self, *args, **options):
        w = self.stdout.write
        published = Redaction.ReviewStatus.PUBLISHED

        total_docs = Document.objects.count()
        current = Redaction.objects.filter(
            document=OuterRef("pk"), is_current=True, review_status=published
        )
        published_docs = Document.objects.filter(Exists(current)).count()

        w("=== Документы ===")
        w(f"Всего: {total_docs}")
        w(f"С опубликованной текущей редакцией: {published_docs}")
        w(f"Без опубликованной редакции: {total_docs - published_docs}")

        w("\n=== Редакции ===")
        w(f"Опубликовано: {Redaction.objects.filter(review_status=published).count()}")
        w(
            "Черновиков: "
            f"{Redaction.objects.filter(review_status=Redaction.ReviewStatus.DRAFT).count()}"
        )

        kinds = Counter(
            Article.objects.filter(
                redaction__is_current=True, redaction__review_status=published
            ).values_list("kind", flat=True)
        )
        w("\n=== Структурные единицы (текущие редакции) ===")
        for kind, label in Article.Kind.choices:
            w(f"{label}: {kinds.get(kind, 0)}")

        w("\n=== Связи ===")
        by_status = Counter(Link.objects.values_list("status", flat=True))
        for status, label in Link.Status.choices:
            w(f"{label}: {by_status.get(status, 0)}")
        w(f"Резолвлено в корпус: {Link.objects.filter(to_document__isnull=False).count()}")
        w(
            "Не резолвлено (внешние/неизвестные): "
            f"{Link.objects.filter(to_document__isnull=True).count()}"
        )

        w("\n=== Ожидаемые акты (обнаружение) ===")
        w(f"Всего в реестре: {PendingAct.objects.count()}")
