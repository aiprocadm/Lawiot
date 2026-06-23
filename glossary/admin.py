from django.contrib import admin

from glossary.models import Term


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("term", "document", "article_number", "is_published")
    list_filter = ("is_published", "document")
    search_fields = ("term", "definition", "article_number")
    list_editable = ("is_published",)
