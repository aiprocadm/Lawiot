from django.core.management.base import BaseCommand

from ingestion.scheduling import sweep_targets


class Command(BaseCommand):
    help = (
        "Обойти все цели авто-приёма (Document.auto_ingest + source_url): скачать, "
        "обнаружить изменения, создать черновики для изменившихся актов."
    )

    def handle(self, *args, **options):
        summary = sweep_targets()
        self.stdout.write(self.style.SUCCESS(f"Обход завершён: {summary}"))
