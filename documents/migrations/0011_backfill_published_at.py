"""Backfill published_at для уже опубликованных редакций.

Точный момент публикации исторических строк неизвестен; лучшее доступное
приближение — redaction_date («действует с») как aware datetime на полночь.
"""

from datetime import datetime, time

from django.db import migrations
from django.utils import timezone


def backfill_published_at(apps, schema_editor):
    Redaction = apps.get_model("documents", "Redaction")
    for redaction in Redaction.objects.filter(
        review_status="published", published_at__isnull=True
    ).iterator():
        naive = datetime.combine(redaction.redaction_date, time.min)
        redaction.published_at = timezone.make_aware(naive)
        redaction.save(update_fields=["published_at"])


def unset_published_at(apps, schema_editor):
    Redaction = apps.get_model("documents", "Redaction")
    Redaction.objects.update(published_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0010_redaction_published_at"),
    ]

    operations = [
        migrations.RunPython(backfill_published_at, unset_published_at),
    ]
