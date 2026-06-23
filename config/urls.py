from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path

from documents import views
from documents.feeds import ChangesFeed
from search import views as search_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", views.document_list, name="document_list"),
    path("search/", search_views.search_view, name="search"),
    path("assistant/", include("assistant.urls")),
    path("changes/", views.changes_feed, name="changes_feed"),
    path("changes/feed/", login_required(ChangesFeed()), name="changes_feed_atom"),
    path("doc/<slug:slug>/", views.document_detail, name="document_detail"),
    path("doc/<slug:slug>/find/", views.document_search, name="document_search"),
    path("doc/<slug:slug>/print/", views.document_print, name="document_print"),
    path("doc/<slug:slug>/export.docx", views.document_export_docx, name="document_export_docx"),
    path(
        "doc/<slug:slug>/diff/<int:from_pk>/",
        views.redaction_diff,
        name="redaction_diff",
    ),
]
