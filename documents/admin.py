from django.contrib import admin, messages

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
    list_display = ("title", "doc_type", "official_number", "status", "auto_ingest")
    list_filter = ("doc_type", "status", "auto_ingest")
    list_editable = ("auto_ingest",)
    search_fields = ("title", "official_number")
    prepopulated_fields = {"slug": ("official_number",)}


@admin.register(Redaction)
class RedactionAdmin(admin.ModelAdmin):
    list_display = ("document", "redaction_date", "review_status", "is_current")
    list_filter = ("review_status", "is_current")
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
        self.message_user(
            request, f"Переразобрано: {done}; пропущено (не черновик): {skipped}"
        )


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("from_document", "link_type", "to_document", "status", "origin")
    list_filter = ("link_type", "status", "origin")
    actions = ["confirm_selected"]

    @admin.action(description="Подтвердить выбранные связи")
    def confirm_selected(self, request, queryset):
        updated = queryset.update(status=Link.Status.CONFIRMED)
        self.message_user(request, f"Подтверждено: {updated}")
