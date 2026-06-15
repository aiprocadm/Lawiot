from django.core.management.base import BaseCommand

from documents.models import Document, PendingAct
from documents.seed.labor_law import PENDING_ACTS, SEED_ACTS


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

        # Реестр ожидаемых актов: материализуем декларативный список и чистим разрешённые.
        p_created = p_updated = p_removed = 0
        for act in PENDING_ACTS:
            defaults = {k: v for k, v in act.items() if k != "slug"}
            _, was_created = PendingAct.objects.update_or_create(
                slug=act["slug"], defaults=defaults
            )
            p_created += was_created
            p_updated += not was_created
        for pending in PendingAct.objects.all():
            if pending.is_resolved:
                pending.delete()
                p_removed += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Ожидаемые акты: создано {p_created}, обновлено {p_updated}, "
                f"удалено разрешённых {p_removed}."
            )
        )
