from django.urls import path

from assistant import views

urlpatterns = [
    path("", views.assistant_view, name="assistant"),
]
