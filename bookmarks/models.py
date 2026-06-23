from django.conf import settings
from django.db import models


class Bookmark(models.Model):
    """Личная закладка пользователя на акт («Избранное»)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks"
    )
    document = models.ForeignKey(
        "documents.Document", on_delete=models.CASCADE, related_name="bookmarked_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "document"], name="uniq_user_document_bookmark")
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} → {self.document}"
