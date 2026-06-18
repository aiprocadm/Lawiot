from django.core.management.base import BaseCommand

from ingestion.discovery import discover


class Command(BaseCommand):
    help = "Ручной обход портала опубликования: завести PendingAct для новых актов."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-pages", type=int, default=None, help="Предел страниц на орган (отладка)."
        )

    def handle(self, *args, max_pages, **options):
        summary = discover(max_pages=max_pages)
        self.stdout.write(self.style.SUCCESS(str(summary)))
