from django.core.management.base import BaseCommand

from documents.models import Redaction
from ingestion.links import extract_links_for_redaction


class Command(BaseCommand):
    help = "Переизвлечь предложенные (auto) связи для текущих опубликованных редакций."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="", help="ограничить документом с этим slug")

    def handle(self, *args, **options):
        redactions = Redaction.objects.filter(
            is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
        ).select_related("document")
        if options["slug"]:
            redactions = redactions.filter(document__slug=options["slug"])
        total_links = 0
        total_red = 0
        for redaction in redactions:
            total_links += extract_links_for_redaction(redaction)
            total_red += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Обработано редакций: {total_red}; предложено связей: {total_links}."
            )
        )
