from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from documents.models import Document
from ingestion.services import import_manual


class Command(BaseCommand):
    help = "Ручной импорт: создать черновик редакции из локального файла (HTML/текст)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="slug существующего документа")
        parser.add_argument("--file", required=True, help="путь к файлу (.html/.htm/.txt)")

    def handle(self, *args, **options):
        try:
            document = Document.objects.get(slug=options["slug"])
        except Document.DoesNotExist:
            raise CommandError(f"Документ со slug '{options['slug']}' не найден.")
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")
        content = path.read_bytes()
        content_type = (
            "text/html" if path.suffix.lower() in {".html", ".htm"} else "text/plain"
        )
        redaction = import_manual(document, content=content, content_type=content_type)
        self.stdout.write(
            self.style.SUCCESS(
                f"Создан черновик #{redaction.pk} ({redaction.articles.count()} статей)."
            )
        )
