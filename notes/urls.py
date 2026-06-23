from django.urls import path

from notes import views

urlpatterns = [
    path("", views.note_list, name="note_list"),
    path("<int:pk>/delete/", views.note_delete, name="note_delete"),
]
