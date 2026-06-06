from django.core.management.base import BaseCommand, CommandError

from documents.models import Document
from ingestion.services import IngestionTarget, ingest_target


class Command(BaseCommand):
    help = "Скачать URL и создать черновик редакции для документа (по slug)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="slug существующего документа")
        parser.add_argument("--url", required=True, help="URL официального источника")
        parser.add_argument(
            "--key", default="", help="target_key (по умолчанию совпадает со slug)"
        )

    def handle(self, *args, **options):
        try:
            document = Document.objects.get(slug=options["slug"])
        except Document.DoesNotExist:
            raise CommandError(f"Документ со slug '{options['slug']}' не найден.")
        target = IngestionTarget(
            document=document,
            url=options["url"],
            target_key=options["key"] or options["slug"],
        )
        job = ingest_target(target)
        self.stdout.write(self.style.SUCCESS(f"Job #{job.pk}: {job.status}"))
        if job.log:
            self.stdout.write(job.log)
        if job.error:
            self.stderr.write(job.error)
