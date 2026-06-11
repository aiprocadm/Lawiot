from django.core.management.base import BaseCommand

from documents.models import Document
from documents.seed.labor_law import SEED_ACTS


class Command(BaseCommand):
    help = "Идемпотентно заводит метаданные актов стартового корпуса (без текста/редакций)."

    def handle(self, *args, **options):
        created = updated = 0
        for act in SEED_ACTS:
            defaults = {k: v for k, v in act.items() if k != "slug"}
            _, was_created = Document.objects.update_or_create(slug=act["slug"], defaults=defaults)
            created += was_created
            updated += not was_created
        self.stdout.write(
            self.style.SUCCESS(f"Сид-корпус: создано {created}, обновлено {updated}.")
        )
