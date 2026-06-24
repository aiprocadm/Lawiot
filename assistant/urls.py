from django.urls import path

from assistant import views

urlpatterns = [
    path("", views.assistant_view, name="assistant"),
    path("stream/", views.assistant_stream, name="assistant_stream"),
]
