from django.db import models


class CourtDecision(models.Model):
    """Судебное решение/разъяснение (курируется вручную).

    Ниша трудового права: ключевые Постановления Пленума ВС РФ и обзоры практики —
    конечный, кураторски-вводимый набор (не нужен внешний API). Связь с актом по
    `document` + `article_number` (стабильный идентификатор статьи, не FK на
    волатильный Article конкретной редакции). Публикуется куратором.
    """

    court = models.CharField("Суд / орган", max_length=300)
    decision_date = models.DateField("Дата")
    case_number = models.CharField("Номер дела/постановления", max_length=100, blank=True)
    title = models.CharField("Заголовок", max_length=500)
    summary = models.TextField("Суть / правовая позиция", blank=True)
    source_url = models.URLField("Источник", blank=True)
    document = models.ForeignKey(
        "documents.Document",
        verbose_name="Акт",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="court_decisions",
    )
    article_number = models.CharField("Статья акта", max_length=50, blank=True)
    is_published = models.BooleanField("Опубликовано", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-decision_date", "-id"]
        verbose_name = "Судебное решение"
        verbose_name_plural = "Судебная практика"

    def __str__(self):
        return f"{self.court} {self.case_number} — {self.title[:60]}".strip()
