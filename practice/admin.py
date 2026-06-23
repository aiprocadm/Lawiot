from django.contrib import admin

from practice.models import CourtDecision


@admin.register(CourtDecision)
class CourtDecisionAdmin(admin.ModelAdmin):
    list_display = ("decision_date", "court", "case_number", "title", "document", "is_published")
    list_filter = ("is_published", "court", "document")
    search_fields = ("title", "summary", "case_number", "article_number")
    list_editable = ("is_published",)
