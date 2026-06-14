from django.db import models


class RawSource(models.Model):
    """Оригинал скачанного/импортированного материала + хэш для обнаружения изменений."""

    target_key = models.CharField(max_length=255)
    content = models.BinaryField()
    content_hash = models.CharField(max_length=64, db_index=True)
    text_hash = models.CharField(max_length=64, blank=True, db_index=True)
    content_type = models.CharField(max_length=100, blank=True)
    source_url = models.URLField(blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fetched_at"]
        indexes = [models.Index(fields=["target_key", "-fetched_at"])]

    def __str__(self):
        return f"{self.target_key} ({self.content_type or 'raw'})"


class IngestionJob(models.Model):
    """Запись одного запуска конвейера приёма (аудит)."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Успех"
        FAILED = "failed", "Ошибка"
        SKIPPED = "skipped", "Пропущено"

    target_key = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    raw_source = models.ForeignKey(
        RawSource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="jobs",
    )
    produced_redaction = models.ForeignKey(
        "documents.Redaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ingestion_jobs",
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.target_key}: {self.get_status_display()}"
