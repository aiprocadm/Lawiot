def test_ingestion_app_is_installed():
    from django.apps import apps

    assert apps.is_installed("ingestion")
