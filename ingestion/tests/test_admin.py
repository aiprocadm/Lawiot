import pytest
from django.urls import reverse


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "curator", "c@example.test", "pass12345"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_rawsource_changelist_loads(staff_client):
    url = reverse("admin:ingestion_rawsource_changelist")
    assert staff_client.get(url).status_code == 200


@pytest.mark.django_db
def test_ingestionjob_changelist_loads(staff_client):
    url = reverse("admin:ingestion_ingestionjob_changelist")
    assert staff_client.get(url).status_code == 200


@pytest.mark.django_db
def test_rawsource_admin_blocks_add(staff_client):
    # has_add_permission=False должно давать 403 даже суперпользователю
    assert staff_client.get(reverse("admin:ingestion_rawsource_add")).status_code == 403


@pytest.mark.django_db
def test_ingestionjob_admin_blocks_add(staff_client):
    assert staff_client.get(reverse("admin:ingestion_ingestionjob_add")).status_code == 403
