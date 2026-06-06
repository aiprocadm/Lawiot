from django.db import models, transaction
from django.utils.text import slugify


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


class Redaction(models.Model):
    class ReviewStatus(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликовано"

    document = models.ForeignKey(
        Document, related_name="redactions", on_delete=models.CASCADE
    )
    redaction_date = models.DateField(help_text="Действует с")
    full_text = models.TextField(blank=True)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.DRAFT
    )
    is_current = models.BooleanField(default=False)
    ingested_at = models.DateTimeField(null=True, blank=True)
    parser_version = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-redaction_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "redaction_date"],
                name="uniq_document_redaction_date",
            ),
            models.UniqueConstraint(
                fields=["document"],
                condition=models.Q(is_current=True),
                name="uniq_current_redaction_per_document",
            ),
        ]

    def __str__(self):
        return f"{self.document} — ред. от {self.redaction_date}"

    def publish(self):
        with transaction.atomic():
            Redaction.objects.filter(
                document=self.document, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
            self.review_status = self.ReviewStatus.PUBLISHED
            self.is_current = True
            self.save(update_fields=["review_status", "is_current"])


class Article(models.Model):
    class Kind(models.TextChoices):
        SECTION = "section", "Раздел"
        CHAPTER = "chapter", "Глава"
        ARTICLE = "article", "Статья"

    redaction = models.ForeignKey(
        Redaction, related_name="articles", on_delete=models.CASCADE
    )
    kind = models.CharField(
        max_length=20, choices=Kind.choices, default=Kind.ARTICLE
    )
    number = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=500, blank=True)
    text = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
    )
    anchor = models.SlugField(max_length=100, blank=True)

    _ANCHOR_PREFIX = {"section": "razdel", "chapter": "glava", "article": "st"}

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):
        if not self.anchor and self.number:
            prefix = self._ANCHOR_PREFIX.get(self.kind, "p")
            self.anchor = f"{prefix}-{slugify(self.number)}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}".strip()
