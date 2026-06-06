import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_admin_document_changelist_loads_for_superuser(client):
    User = get_user_model()
    admin_user = User.objects.create_superuser("admin", "a@a.ru", "pass12345")
    client.force_login(admin_user)
    response = client.get(reverse("admin:documents_document_changelist"))
    assert response.status_code == 200
