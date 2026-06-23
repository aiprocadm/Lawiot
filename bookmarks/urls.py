from django.urls import path

from bookmarks import views

urlpatterns = [
    path("", views.bookmark_list, name="bookmark_list"),
    path("toggle/<slug:slug>/", views.bookmark_toggle, name="bookmark_toggle"),
]
