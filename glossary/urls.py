from django.urls import path

from glossary import views

urlpatterns = [
    path("", views.glossary_list, name="glossary_list"),
]
