from django.core.management.base import BaseCommand

from documents.models import Document, PendingAct
from documents.seed.labor_law import PENDING_ACTS, SEED_ACTS
from documents.seed.labor_safety_orders import (
    SAFETY_NORMATIVE_ACTS,
    SAFETY_ORDER_ACTS,
    SAFETY_PENDING_ACTS,
)

# Полный корпус = акты трудового права + кодексы (labor_law) + архив приказов по
# охране труда + действующие нормативные акты по ОТ (labor_safety_orders).
# Агрегируем здесь, чтобы держать модули раздельно и не плодить конфликты при
# параллельной работе над разными частями.
ALL_ACTS = SEED_ACTS + SAFETY_ORDER_ACTS + SAFETY_NORMATIVE_ACTS
ALL_PENDING = PENDING_ACTS + SAFETY_PENDING_ACTS


class Command(BaseCommand):
    help = "Идемпотентно заводит метаданные актов стартового корпуса (без текста/редакций)."

    def handle(self, *args, **options):
        created = updated = 0
        for act in ALL_ACTS:
            defaults = {k: v for k, v in act.items() if k != "slug"}
            _, was_created = Document.objects.update_or_create(slug=act["slug"], defaults=defaults)
            created += was_created
            updated += not was_created
        self.stdout.write(
            self.style.SUCCESS(f"Сид-корпус: создано {created}, обновлено {updated}.")
        )

        # Реестр ожидаемых актов: материализуем декларативный список и чистим разрешённые.
        p_created = p_updated = p_removed = 0
        for act in ALL_PENDING:
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
