import pytest
from django.contrib.auth.models import Group


@pytest.mark.django_db
def test_role_groups_exist():
    assert Group.objects.filter(name="readers").exists()
    assert Group.objects.filter(name="curators").exists()
