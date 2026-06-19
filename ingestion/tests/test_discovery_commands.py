import pytest
from django.core.management import call_command
from django_q.models import Schedule


@pytest.mark.django_db
def test_ensure_discovery_schedule_is_idempotent():
    call_command("ensure_discovery_schedule")
    call_command("ensure_discovery_schedule")
    qs = Schedule.objects.filter(name="daily-discovery")
    assert qs.count() == 1
    assert qs.first().func == "ingestion.discovery.run_discovery"
