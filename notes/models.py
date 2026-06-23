from django.conf import settings
from django.db import models


class Note(models.Model):
    """Личная заметка пользователя к акту (необязательно к конкретной статье)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    document = models.ForeignKey(
        "documents.Document", on_delete=models.CASCADE, related_name="notes"
    )
    article_number = models.CharField("Статья", max_length=50, blank=True)
    text = models.TextField("Заметка")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user} → {self.document}: {self.text[:40]}"
