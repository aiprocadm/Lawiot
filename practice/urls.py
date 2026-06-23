from django.urls import path

from practice import views

urlpatterns = [
    path("", views.practice_list, name="practice_list"),
]
