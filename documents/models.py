from django.db import models


class Document(models.Model):
    class DocType(models.TextChoices):
        CODE = "code", "Кодекс"
        FEDERAL_LAW = "federal_law", "Федеральный закон"
        DECREE = "decree", "Постановление"
        ORDER = "order", "Приказ"
        OTHER = "other", "Иное"

    class Status(models.TextChoices):
        IN_FORCE = "in_force", "Действует"
        REPEALED = "repealed", "Утратил силу"
        NOT_IN_FORCE = "not_in_force", "Не вступил в силу"

    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    title = models.TextField()
    official_number = models.CharField(max_length=100, blank=True)
    sign_date = models.DateField(null=True, blank=True)
    issuing_body = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IN_FORCE
    )
    source_url = models.URLField(blank=True)
    official_pub_date = models.DateField(null=True, blank=True)
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return f"{self.get_doc_type_display()} {self.official_number}: {self.title[:60]}"
