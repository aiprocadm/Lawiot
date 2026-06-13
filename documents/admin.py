from django.contrib import admin, messages
from django.urls import path

from documents.admin_views import (
    manual_import_view,
    redaction_diff_view,
    review_queue_view,
)
from documents.models import Article, Document, Link, Redaction
from ingestion.services import (
    PublishedRedactionExists,
    ReparseYieldedNothing,
    reparse_redaction,
)


class ArticleInline(admin.TabularInline):
    model = Article
    extra = 0
    fields = ("kind", "number", "title", "order", "parent", "anchor")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "doc_type", "official_number", "status", "auto_ingest", "auto_publish")
    list_filter = ("doc_type", "status", "auto_ingest", "auto_publish")
    list_editable = ("auto_ingest", "auto_publish")
    search_fields = ("title", "official_number")
    prepopulated_fields = {"slug": ("official_number",)}


@admin.register(Redaction)
class RedactionAdmin(admin.ModelAdmin):
    list_display = ("document", "redaction_date", "review_status", "is_current")
    list_filter = ("review_status", "is_current")
    change_list_template = "admin/documents/redaction/change_list.html"
    inlines = [ArticleInline]
    actions = ["publish_selected", "reparse_from_raw"]

    @admin.action(description="Опубликовать выбранные редакции")
    def publish_selected(self, request, queryset):
        count = queryset.count()
        for redaction in queryset:
            redaction.publish()
        self.message_user(request, f"Опубликовано: {count}")

    @admin.action(description="Переразобрать из RawSource")
    def reparse_from_raw(self, request, queryset):
        done = skipped = 0
        for redaction in queryset:
            if redaction.review_status != Redaction.ReviewStatus.DRAFT:
                skipped += 1
                continue
            try:
                reparse_redaction(redaction)
                done += 1
            except (ReparseYieldedNothing, PublishedRedactionExists, ValueError) as exc:
                self.message_user(request, f"{redaction}: {exc}", level=messages.WARNING)
        self.message_user(request, f"Переразобрано: {done}; пропущено (не черновик): {skipped}")

    def get_urls(self):
        custom = [
            path(
                "review-queue/",
                self.admin_site.admin_view(review_queue_view),
                name="documents_redaction_review_queue",
            ),
            path(
                "<int:pk>/diff/",
                self.admin_site.admin_view(redaction_diff_view),
                name="documents_redaction_diff",
            ),
            path(
                "import/",
                self.admin_site.admin_view(manual_import_view),
                name="documents_redaction_manual_import",
            ),
        ]
        return custom + super().get_urls()


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("from_document", "link_type", "to_document", "status", "origin")
    list_filter = ("link_type", "status", "origin")
    actions = ["confirm_selected"]

    @admin.action(description="Подтвердить выбранные связи")
    def confirm_selected(self, request, queryset):
        updated = queryset.update(status=Link.Status.CONFIRMED)
        self.message_user(request, f"Подтверждено: {updated}")
