from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q, Value
from django.utils import timezone
from django.utils.text import slugify
from pgvector.django import HnswIndex, VectorField

# Размерность эмбеддингов = intfloat/multilingual-e5-small (см. search.embeddings).
EMBEDDING_DIM = 384


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

    class SourceStatus(models.TextChoices):
        OFFICIAL = "official", "Официальный источник"
        UNOFFICIAL = "unofficial", "Неофициальный источник"

    class Level(models.TextChoices):
        FEDERAL = "federal", "Федеральный"
        REGIONAL = "regional", "Региональный"
        MUNICIPAL = "municipal", "Муниципальный"

    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    title = models.TextField()
    official_number = models.CharField(max_length=100, blank=True)
    sign_date = models.DateField(null=True, blank=True)
    issuing_body = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_FORCE)
    source_status = models.CharField(
        max_length=20, choices=SourceStatus.choices, default=SourceStatus.OFFICIAL
    )
    level = models.CharField(
        max_length=20,
        choices=Level.choices,
        default=Level.FEDERAL,
        help_text="Уровень нормативки (Р2). Региональный/муниципальный — на будущее.",
    )
    region_code = models.CharField(
        max_length=10, blank=True, help_text="Код субъекта РФ; пусто на федеральном уровне."
    )
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

    @property
    def reference_label(self) -> str:
        """Человекочитаемая подпись акта для панелей связей: название плюс номер
        в скобках, когда номер задан; только название иначе. Так текст ссылки
        никогда не пуст (раньше выводился голый official_number, blank=True)."""
        if self.official_number:
            return f"{self.title} ({self.official_number})"
        return self.title


class RedactionQuerySet(models.QuerySet):
    """Семантические фильтры по жизненному циклу редакции.

    Цепляемые методы вместо россыпи `filter(is_current=True, review_status=…)`
    по вьюхам и сервисам: правило «что считать опубликованным/текущим» живёт
    в одном месте.
    """

    def published(self):
        return self.filter(review_status=self.model.ReviewStatus.PUBLISHED)

    def current_published(self):
        return self.filter(
            is_current=True, review_status=self.model.ReviewStatus.PUBLISHED
        )


class Redaction(models.Model):
    class ReviewStatus(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликовано"

    class TextStatus(models.TextChoices):
        OFFICIAL = "official", "Официальная редакция"
        RECONSTRUCTION = "reconstruction", "Автоматическая реконструкция"

    document = models.ForeignKey(Document, related_name="redactions", on_delete=models.CASCADE)
    redaction_date = models.DateField(help_text="Действует с")
    full_text = models.TextField(blank=True)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.DRAFT
    )
    text_status = models.CharField(
        max_length=20,
        choices=TextStatus.choices,
        default=TextStatus.OFFICIAL,
        help_text=(
            "Происхождение текста (Р1): official — из официального сводного раздела ИПС; "
            "reconstruction — собрано движком/куратором. Ортогонально review_status."
        ),
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

    objects = RedactionQuerySet.as_manager()

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
        POINT = "point", "Пункт"
        APPENDIX = "appendix", "Приложение"

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
    # Семантический эмбеддинг (AI-срез 4). null до бэкфилла `embed_articles`;
    # генерируется вне request-пути. См. search.embeddings / search.services.
    embedding = VectorField(dimensions=EMBEDDING_DIM, null=True, blank=True, editable=False)

    _ANCHOR_PREFIX = {
        "section": "razdel",
        "chapter": "glava",
        "article": "st",
        "point": "p",
        "appendix": "pril",
    }

    class Meta:
        ordering = ["order"]
        indexes = [
            GinIndex(fields=["search_vector"], name="article_search_gin"),
            HnswIndex(
                name="article_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]
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
            # Прямой доступ: новый вид без префикса упадёт KeyError явно,
            # а не получит молча якорь пункта (раньше дефолт был "p").
            prefix = self._ANCHOR_PREFIX[self.kind]
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


class PendingAct(models.Model):
    """Акт, который мы хотим в корпусе, но которого пока нет в доступном источнике
    (напр. 565-ФЗ: в ИПС нет консолидированного текста). Напоминание куратору —
    список виден в admin; «разрешён» выводится из состояния корпуса."""

    class Source(models.TextChoices):
        AUTO = "auto", "Авто"
        MANUAL = "manual", "Вручную"

    class ResolutionStatus(models.TextChoices):
        NEW = "new", "Новый"
        CANDIDATE = "candidate", "Есть кандидат"
        BOUND = "bound", "Привязан"
        DISMISSED = "dismissed", "Отклонён"

    slug = models.SlugField(max_length=255, unique=True)
    title = models.TextField()
    official_number = models.CharField(max_length=100, blank=True)
    doc_type = models.CharField(max_length=20, choices=Document.DocType.choices)
    note = models.TextField(blank=True, help_text="Почему ждём / где искать.")
    ips_search_url = models.URLField(blank=True, help_text="Ссылка на поиск ИПС (браузер).")
    added_at = models.DateTimeField(auto_now_add=True)
    # --- автообнаружение (publication.pravo.gov.ru) ---
    eo_number = models.CharField(
        max_length=40, blank=True, help_text="Номер ЭО портала опубликования (пусто у ручных)."
    )
    publication_url = models.URLField(blank=True, help_text="Ссылка на акт/PDF на портале.")
    document_date = models.DateField(null=True, blank=True)
    issuing_body = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    ips_nd = models.CharField(
        max_length=40, blank=True, help_text="Привязанный nd ИПС (резолвер/куратор)."
    )
    resolution_status = models.CharField(
        max_length=12, choices=ResolutionStatus.choices, default=ResolutionStatus.NEW
    )

    class Meta:
        ordering = ["added_at"]
        verbose_name = "ожидаемый акт"
        verbose_name_plural = "ожидаемые акты"
        constraints = [
            models.UniqueConstraint(
                fields=["eo_number"],
                condition=~models.Q(eo_number=""),
                name="uniq_pendingact_eo",
            ),
        ]

    def __str__(self):
        return f"{self.official_number}: {self.title[:60]} (ожидается)"

    @property
    def is_resolved(self) -> bool:
        """True, когда акт уже заведён: есть Document с теми же (official_number,
        doc_type) и опубликованной текущей редакцией.

        Пустой official_number нельзя сопоставить по номеру: иначе ЛЮБОЙ
        ожидаемый акт без номера «разрешался» первым же опубликованным
        документом без номера того же типа и молча удалялся в seed_corpus.
        """
        if not self.official_number:
            return False
        return Document.objects.filter(
            official_number=self.official_number,
            doc_type=self.doc_type,
            redactions__is_current=True,
            redactions__review_status=Redaction.ReviewStatus.PUBLISHED,
        ).exists()
