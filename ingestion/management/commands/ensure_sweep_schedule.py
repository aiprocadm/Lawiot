from django.conf import settings
from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Идемпотентно зарегистрировать/обновить ежедневное расписание обхода целей (django-q2)."

    SCHEDULE_NAME = "daily-sweep"

    def handle(self, *args, **options):
        schedule, created = Schedule.objects.update_or_create(
            name=self.SCHEDULE_NAME,
            defaults={
                "func": "ingestion.scheduling.run_sweep",
                "schedule_type": Schedule.CRON,
                "cron": settings.SWEEP_CRON,
                "repeats": -1,  # бесконечно
            },
        )
        verb = "создано" if created else "обновлено"
        self.stdout.write(
            self.style.SUCCESS(
                f"Расписание «{schedule.name}» {verb}: func={schedule.func}, cron={schedule.cron}"
            )
        )
