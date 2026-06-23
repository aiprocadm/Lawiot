from django.db import models


class Term(models.Model):
    """Термин трудового права (курируется вручную).

    Классический раздел СПС: словарь терминов со ссылкой на статью акта, где
    термин определён законом. Содержание вводит куратор (как судебная практика) —
    система не генерирует юридических определений. Связь с актом по `document` +
    `article_number` (стабильный идентификатор статьи, не FK на волатильный
    Article конкретной редакции). Публикуется куратором.
    """

    term = models.CharField("Термин", max_length=200)
    definition = models.TextField("Определение", blank=True)
    document = models.ForeignKey(
        "documents.Document",
        verbose_name="Акт-источник",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="glossary_terms",
    )
    article_number = models.CharField("Статья акта", max_length=50, blank=True)
    is_published = models.BooleanField("Опубликовано", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["term", "id"]
        verbose_name = "Термин"
        verbose_name_plural = "Глоссарий"

    def __str__(self):
        return self.term
