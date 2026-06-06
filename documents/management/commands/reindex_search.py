from django.core.management.base import BaseCommand

from documents.models import Redaction


class Command(BaseCommand):
    help = "Пересобирает поисковые векторы для всех опубликованных редакций."

    def handle(self, *args, **options):
        published = Redaction.objects.filter(
            review_status=Redaction.ReviewStatus.PUBLISHED
        ).select_related("document")
        count = 0
        for redaction in published:
            redaction.update_search_index()
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Переиндексировано редакций: {count}"))
