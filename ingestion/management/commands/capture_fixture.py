from pathlib import Path

from django.core.management.base import BaseCommand

from ingestion.fetching import fetch


class Command(BaseCommand):
    help = "Скачать URL и сохранить сырьё в файл-фикстуру (инструмент разработки)."
    stealth_options = ("client",)

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("out_path")

    def handle(self, *args, url, out_path, client=None, **options):
        result = fetch(url, client=client)
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.content)
        self.stdout.write(
            self.style.SUCCESS(
                f"Сохранено {len(result.content)} байт ({result.content_type}) → {path}"
            )
        )
