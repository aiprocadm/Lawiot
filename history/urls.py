from django.urls import path

from history import views

urlpatterns = [
    path("", views.history_list, name="history_list"),
]
