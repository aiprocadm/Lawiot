import pytest
from django.utils import timezone


def test_ingestion_app_is_installed():
    from django.apps import apps

    assert apps.is_installed("ingestion")


def test_redaction_has_raw_source_fk():
    from documents.models import Redaction
    from ingestion.models import RawSource

    field = Redaction._meta.get_field("raw_source")
    assert field.related_model is RawSource
    assert field.null is True


@pytest.mark.django_db
def test_rawsource_stores_content_and_metadata():
    from ingestion.models import RawSource

    rs = RawSource.objects.create(
        target_key="tk-rf",
        content=b"<p>hi</p>",
        content_hash="deadbeef",
        content_type="text/html",
        source_url="https://example.test/doc",
    )
    rs.refresh_from_db()
    assert bytes(rs.content) == b"<p>hi</p>"
    assert rs.content_hash == "deadbeef"
    assert rs.fetched_at is not None


@pytest.mark.django_db
def test_ingestionjob_create_and_link_redaction():
    from documents.tests.factories import make_redaction
    from ingestion.models import IngestionJob

    red = make_redaction()
    job = IngestionJob.objects.create(
        target_key="tk-rf",
        status=IngestionJob.Status.SUCCESS,
        started_at=timezone.now(),
        produced_redaction=red,
    )
    assert job.status == IngestionJob.Status.SUCCESS
    assert job.produced_redaction == red
    assert red.ingestion_jobs.count() == 1


@pytest.mark.django_db
def test_no_pending_migrations():
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
