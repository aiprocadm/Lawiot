from django.contrib import admin
from django.urls import include, path

from documents import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", views.document_list, name="document_list"),
    path("doc/<slug:slug>/", views.document_detail, name="document_detail"),
]
