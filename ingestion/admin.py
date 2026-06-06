from django.contrib import admin

from ingestion.models import IngestionJob, RawSource


@admin.register(RawSource)
class RawSourceAdmin(admin.ModelAdmin):
    list_display = ("target_key", "content_type", "content_hash", "fetched_at")
    list_filter = ("content_type",)
    search_fields = ("target_key", "source_url")
    readonly_fields = (
        "target_key",
        "content_type",
        "content_hash",
        "source_url",
        "fetched_at",
    )
    exclude = ("content",)  # сырые байты не показываем в форме


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display = (
        "target_key",
        "status",
        "started_at",
        "finished_at",
        "produced_redaction",
    )
    list_filter = ("status",)
    search_fields = ("target_key",)
    readonly_fields = (
        "target_key",
        "status",
        "started_at",
        "finished_at",
        "log",
        "error",
        "raw_source",
        "produced_redaction",
    )
