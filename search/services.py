from dataclasses import dataclass

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import F
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from documents.models import Article, Document, Redaction


@dataclass
class SearchResult:
    document: Document
    rank: float
    snippet: str
    article_anchor: str | None = None
    article_label: str | None = None


# Сентинелы-маркеры подсветки: ts_headline вставит их в НЕэкранированный текст,
# мы экранируем всё целиком, затем вернём <mark> только вокруг маркеров.
_HL_START = "@@LAWIOT_HL_START@@"
_HL_STOP = "@@LAWIOT_HL_STOP@@"

# Максимальное число строк, возвращаемых из БД для каждого источника (SQL LIMIT).
_MAX_HITS_PER_SOURCE = 100


def _headline(field, query):
    return SearchHeadline(
        field, query, config="russian", start_sel=_HL_START, stop_sel=_HL_STOP
    )


def _safe_snippet(raw) -> SafeString:
    return mark_safe(
        escape(raw or "").replace(_HL_START, "<mark>").replace(_HL_STOP, "</mark>")
    )


def search_documents(
    query_text,
    *,
    doc_type="",
    status="",
    issuing_body="",
    date_from=None,
    date_to=None,
):
    query_text = (query_text or "").strip()
    if not query_text:
        return []

    query = SearchQuery(query_text, config="russian", search_type="websearch")

    def apply_doc_filters(qs, prefix):
        if doc_type:
            qs = qs.filter(**{f"{prefix}doc_type": doc_type})
        if status:
            qs = qs.filter(**{f"{prefix}status": status})
        if issuing_body:
            qs = qs.filter(**{f"{prefix}issuing_body__icontains": issuing_body})
        if date_from:
            qs = qs.filter(**{f"{prefix}sign_date__gte": date_from})
        if date_to:
            qs = qs.filter(**{f"{prefix}sign_date__lte": date_to})
        return qs

    redaction_hits = apply_doc_filters(
        Redaction.objects.filter(
            is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .annotate(snippet=_headline("full_text", query))
        .select_related("document"),
        "document__",
    ).order_by("-rank")[:_MAX_HITS_PER_SOURCE]

    article_hits = apply_doc_filters(
        Article.objects.filter(
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .annotate(snippet=_headline("text", query))
        .select_related("redaction__document"),
        "redaction__document__",
    ).order_by("-rank")[:_MAX_HITS_PER_SOURCE]

    best: dict[int, SearchResult] = {}
    for r in redaction_hits:
        existing = best.get(r.document_id)
        if existing is None or r.rank > existing.rank:
            best[r.document_id] = SearchResult(
                document=r.document, rank=r.rank, snippet=_safe_snippet(r.snippet)
            )
    for a in article_hits:
        doc = a.redaction.document
        existing = best.get(doc.id)
        if existing is None or a.rank > existing.rank:
            best[doc.id] = SearchResult(
                document=doc,
                rank=a.rank,
                snippet=_safe_snippet(a.snippet),
                article_anchor=a.anchor,
                article_label=f"{a.get_kind_display()} {a.number}",
            )

    return sorted(best.values(), key=lambda x: x.rank, reverse=True)
