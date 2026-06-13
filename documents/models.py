from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q, Value
from django.utils import timezone
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
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_FORCE)
    source_url = models.URLField(blank=True)
    auto_ingest = models.BooleanField(
        default=False,
        help_text="Включить периодический авто-приём из source_url по расписанию.",
    )
    auto_publish = models.BooleanField(
        default=False,
        help_text="Авто-публиковать свежую редакцию из source_url как текущую, без куратора.",
    )
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

    document = models.ForeignKey(Document, related_name="redactions", on_delete=models.CASCADE)
    redaction_date = models.DateField(help_text="Действует с")
    full_text = models.TextField(blank=True)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.DRAFT
    )
    is_current = models.BooleanField(default=False)
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Когда редакция опубликована в системе (ставится publish()).",
    )
    ingested_at = models.DateTimeField(null=True, blank=True)
    parser_version = models.CharField(max_length=50, blank=True)
    raw_source = models.ForeignKey(
        "ingestion.RawSource",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="redactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    search_vector = SearchVectorField(null=True, editable=False)

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
        indexes = [GinIndex(fields=["search_vector"], name="redaction_search_gin")]

    def __str__(self):
        return f"{self.document} — ред. от {self.redaction_date}"

    def publish(self):
        with transaction.atomic():
            Redaction.objects.filter(document=self.document, is_current=True).exclude(
                pk=self.pk
            ).update(is_current=False)
            self.review_status = self.ReviewStatus.PUBLISHED
            self.is_current = True
            self.published_at = timezone.now()
            self.save(update_fields=["review_status", "is_current", "published_at"])
            self.update_search_index()

    def update_search_index(self):
        Redaction.objects.filter(pk=self.pk).update(
            search_vector=(
                SearchVector(Value(self.document.title), weight="A", config="russian")
                + SearchVector("full_text", weight="B", config="russian")
            )
        )
        Article.objects.filter(redaction=self).update(
            search_vector=(
                SearchVector("number", weight="A", config="russian")
                + SearchVector("title", weight="A", config="russian")
                + SearchVector("text", weight="B", config="russian")
            )
        )


class Article(models.Model):
    class Kind(models.TextChoices):
        SECTION = "section", "Раздел"
        CHAPTER = "chapter", "Глава"
        ARTICLE = "article", "Статья"

    redaction = models.ForeignKey(Redaction, related_name="articles", on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ARTICLE)
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
    search_vector = SearchVectorField(null=True, editable=False)

    _ANCHOR_PREFIX = {"section": "razdel", "chapter": "glava", "article": "st"}

    class Meta:
        ordering = ["order"]
        indexes = [GinIndex(fields=["search_vector"], name="article_search_gin")]
        constraints = [
            # Cheap, DB-enforced guard against the one-row cycle (A is its own
            # parent). Longer cycles (A→B→A) span multiple rows and are caught
            # by clean(); a single-row CHECK cannot see them.
            models.CheckConstraint(
                condition=~Q(parent=F("id")),
                name="article_not_self_parent",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.anchor and self.number:
            prefix = self._ANCHOR_PREFIX.get(self.kind, "p")
            self.anchor = f"{prefix}-{slugify(self.number.replace('.', '-'))}"
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        # Walk the parent chain. If we ever revisit this article, the curator has
        # created a cycle that would make the recursive tree template recurse
        # until RecursionError (HTTP 500 on the detail page). Reject it here so
        # admin full_clean() surfaces a friendly validation error instead.
        seen = {self.pk} if self.pk is not None else set()
        ancestor = self.parent
        while ancestor is not None:
            if ancestor.pk in seen:
                raise ValidationError(
                    {"parent": "Цикл в иерархии статей: статья не может быть потомком самой себя."}
                )
            seen.add(ancestor.pk)
            ancestor = ancestor.parent

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}".strip()


class Link(models.Model):
    class LinkType(models.TextChoices):
        REFERENCES = "references", "Ссылается на"
        AMENDS = "amends", "Изменяет"
        AMENDED_BY = "amended_by", "Изменён"

    class Origin(models.TextChoices):
        AUTO = "auto", "Парсер"
        CURATOR = "curator", "Куратор"

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Предложена"
        CONFIRMED = "confirmed", "Подтверждена"

    from_document = models.ForeignKey(
        Document, related_name="outgoing_links", on_delete=models.CASCADE
    )
    from_article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        related_name="outgoing_links",
        on_delete=models.SET_NULL,
    )
    to_document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        related_name="incoming_links",
        on_delete=models.SET_NULL,
    )
    to_article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        related_name="incoming_links",
        on_delete=models.SET_NULL,
    )
    raw_citation = models.TextField(blank=True)
    link_type = models.CharField(
        max_length=20, choices=LinkType.choices, default=LinkType.REFERENCES
    )
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.CURATOR)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUGGESTED)
    context = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        target = self.to_document or self.raw_citation or "—"
        return f"{self.from_document} — {self.get_link_type_display()} → {target}"
