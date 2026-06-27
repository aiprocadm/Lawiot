from django.contrib import admin, messages
from django.db.models import Exists, OuterRef
from django.urls import path

from documents.admin_views import (
    manual_import_view,
    redaction_diff_view,
    review_queue_view,
)
from documents.models import Article, Document, Link, PendingAct, Redaction
from ingestion.services import (
    PublishedRedactionExists,
    ReparseYieldedNothing,
    reparse_redaction,
)


class ArticleInline(admin.TabularInline):
    model = Article
    extra = 0
    fields = ("kind", "number", "title", "order", "parent", "anchor")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "doc_type",
        "official_number",
        "status",
        "level",
        "source_status",
        "auto_ingest",
        "auto_publish",
    )
    list_filter = ("doc_type", "status", "level", "source_status", "auto_ingest", "auto_publish")
    list_editable = ("auto_ingest", "auto_publish")
    search_fields = ("title", "official_number")
    prepopulated_fields = {"slug": ("official_number",)}


@admin.register(Redaction)
class RedactionAdmin(admin.ModelAdmin):
    list_display = ("document", "redaction_date", "review_status", "text_status", "is_current")
    list_filter = ("review_status", "text_status", "is_current")
    change_list_template = "admin/documents/redaction/change_list.html"
    inlines = [ArticleInline]
    actions = ["publish_selected", "reparse_from_raw"]

    @admin.action(description="Опубликовать выбранные редакции")
    def publish_selected(self, request, queryset):
        count = queryset.count()
        for redaction in queryset:
            redaction.publish()
        self.message_user(request, f"Опубликовано: {count}")

    @admin.action(description="Переразобрать из RawSource")
    def reparse_from_raw(self, request, queryset):
        done = skipped = 0
        for redaction in queryset:
            if redaction.review_status != Redaction.ReviewStatus.DRAFT:
                skipped += 1
                continue
            try:
                reparse_redaction(redaction)
                done += 1
            except (ReparseYieldedNothing, PublishedRedactionExists, ValueError) as exc:
                self.message_user(request, f"{redaction}: {exc}", level=messages.WARNING)
        self.message_user(request, f"Переразобрано: {done}; пропущено (не черновик): {skipped}")

    def get_urls(self):
        custom = [
            path(
                "review-queue/",
                self.admin_site.admin_view(review_queue_view),
                name="documents_redaction_review_queue",
            ),
            path(
                "<int:pk>/diff/",
                self.admin_site.admin_view(redaction_diff_view),
                name="documents_redaction_diff",
            ),
            path(
                "import/",
                self.admin_site.admin_view(manual_import_view),
                name="documents_redaction_manual_import",
            ),
        ]
        return custom + super().get_urls()


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("from_document", "link_type", "to_document", "status", "origin")
    list_filter = ("link_type", "status", "origin")
    actions = ["confirm_selected"]

    @admin.action(description="Подтвердить выбранные связи")
    def confirm_selected(self, request, queryset):
        updated = queryset.update(status=Link.Status.CONFIRMED)
        self.message_user(request, f"Подтверждено: {updated}")


class PendingActResolvedFilter(admin.SimpleListFilter):
    title = "в корпусе"
    parameter_name = "resolved"

    def lookups(self, request, model_admin):
        return [("yes", "Да"), ("no", "Нет")]

    def queryset(self, request, queryset):
        value = self.value()
        if value not in {"yes", "no"}:
            return queryset
        # Одним SQL-запросом вместо .exists() на каждый акт (N+1).
        # Зеркалит PendingAct.is_resolved на уровне БД.
        resolved = Document.objects.filter(
            official_number=OuterRef("official_number"),
            doc_type=OuterRef("doc_type"),
            redactions__is_current=True,
            redactions__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        annotated = queryset.annotate(_is_resolved=Exists(resolved))
        return annotated.filter(_is_resolved=(value == "yes"))


@admin.action(description="Подобрать nd из ИПС (best-effort)")
def suggest_nd_candidates(modeladmin, request, queryset):
    """Прогнать best-effort резолвер ИПС по выбранным актам. Найденные кандидаты
    пишем в note, первый проставляем в пустой ips_nd, статус → «Есть кандидат».
    Поиск ИПС нестабилен headless — пустой результат штатен (куратор введёт вручную)."""
    from ingestion.ips_resolve import resolve_nd

    found = 0
    for act in queryset:
        result = resolve_nd(act)
        if not result.candidates:
            continue
        if not act.ips_nd:
            act.ips_nd = result.candidates[0]
        act.resolution_status = PendingAct.ResolutionStatus.CANDIDATE
        prefix = f"{act.note}\n" if act.note else ""
        act.note = f"{prefix}ИПС-кандидаты: {', '.join(result.candidates)}"
        act.save(update_fields=["ips_nd", "resolution_status", "note"])
        found += 1
    if request is not None:
        modeladmin.message_user(request, f"Найдены кандидаты для актов: {found}.")


@admin.action(description="Привязать к ИПС и включить авто-ингест")
def bind_to_ips(modeladmin, request, queryset):
    """Из ips_nd строим ИПС-источник и заводим Document с авто-ингестом.

    Новый документ создаётся с auto_publish=False (лестница доверия). Если документ
    с таким slug УЖЕ есть (повторная привязка или ручная курация) — НЕ перетираем
    его реквизиты и НЕ трогаем auto_publish (куратор мог поднять промо); только
    включаем auto_ingest и обновляем источник."""
    bound = 0
    for act in queryset:
        nd = (act.ips_nd or "").strip()
        if not nd:
            continue
        source_url = f"http://pravo.gov.ru/proxy/ips/?doc_itself=&nd={nd}&print=1"
        doc, created = Document.objects.get_or_create(
            slug=act.slug,
            defaults={
                "title": act.title,
                "official_number": act.official_number,
                "doc_type": act.doc_type,
                "issuing_body": act.issuing_body,
                "source_url": source_url,
                "auto_ingest": True,
                "auto_publish": False,
            },
        )
        if not created:
            doc.source_url = source_url
            doc.auto_ingest = True
            doc.save(update_fields=["source_url", "auto_ingest"])
        act.resolution_status = PendingAct.ResolutionStatus.BOUND
        act.save(update_fields=["resolution_status"])
        bound += 1
    if request is not None:
        msg = (
            f"Привязано актов: {bound}."
            if bound
            else "Ни один акт не имеет ips_nd — действие не выполнено."
        )
        modeladmin.message_user(request, msg)


@admin.register(PendingAct)
class PendingActAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "official_number",
        "doc_type",
        "source",
        "resolution_status",
        "document_date",
        "resolved",
        "added_at",
    )
    list_filter = (PendingActResolvedFilter, "doc_type", "source", "resolution_status")
    search_fields = ("title", "official_number", "eo_number")
    readonly_fields = ("ingest_hint", "added_at", "eo_number", "publication_url")
    actions = [suggest_nd_candidates, bind_to_ips]

    @admin.display(boolean=True, description="В корпусе")
    def resolved(self, obj):
        return obj.is_resolved

    @admin.display(description="Как завести")
    def ingest_hint(self, obj):
        return (
            f"Заполните ips_nd и примените действие «Привязать к ИПС». "
            f"Либо вручную: python manage.py ingest_url --slug {obj.slug} "
            f'--url "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=<ND>&print=1"'
        )
