from django.conf import settings
from django.db import models
from django.utils import timezone


class ViewHistory(models.Model):
    """Последний просмотр акта пользователем (одна строка на пару, обновляется)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="view_history"
    )
    document = models.ForeignKey(
        "documents.Document", on_delete=models.CASCADE, related_name="view_history"
    )
    # default: модель самодостаточна (создание вне middleware — admin, будущий код —
    # не упадёт NOT NULL). На практике middleware всегда задаёт явный timezone.now().
    viewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "document"], name="uniq_user_doc_view")
        ]
        ordering = ["-viewed_at"]

    def __str__(self):
        return f"{self.user} → {self.document} @ {self.viewed_at:%Y-%m-%d %H:%M}"
