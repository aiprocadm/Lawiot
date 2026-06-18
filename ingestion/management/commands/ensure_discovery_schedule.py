from django.conf import settings
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Идемпотентно зарегистрировать/обновить расписание обнаружения актов (django-q2)."

    SCHEDULE_NAME = "daily-discovery"

    def handle(self, *args, **options):
        schedule, created = Schedule.objects.update_or_create(
            name=self.SCHEDULE_NAME,
            defaults={
                "func": "ingestion.discovery.run_discovery",
                "schedule_type": Schedule.CRON,
                "cron": settings.DISCOVERY_CRON,
                "repeats": -1,
            },
        )
        verb = "создано" if created else "обновлено"
        self.stdout.write(
            self.style.SUCCESS(
                f"Расписание «{schedule.name}» {verb}: func={schedule.func}, cron={schedule.cron}"
            )
        )
