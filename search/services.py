from dataclasses import dataclass

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import F
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from documents.models import Article, Document, Redaction
from search.lemmas import build_expanded_tsquery


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
    return SearchHeadline(field, query, config="russian", start_sel=_HL_START, stop_sel=_HL_STOP)


def _snippets_by_pk(manager, field, pks, query):
    """Вторая фаза поиска: ts_headline только для строк-победителей.

    ts_headline парсит весь текст строки (для кодекса — сотни КБ), поэтому
    его нельзя вешать на каждый найденный хит: считаем по первичным ключам
    уже после схлопывания результатов по документам.
    """
    if not pks:
        return {}
    return dict(
        manager.filter(pk__in=pks)
        .annotate(snippet=_headline(field, query))
        .values_list("pk", "snippet")
    )


def _safe_snippet(raw) -> SafeString:
    return mark_safe(escape(raw or "").replace(_HL_START, "<mark>").replace(_HL_STOP, "</mark>"))


def _build_query(query_text) -> SearchQuery:
    """Websearch-запрос, при возможности расширенный словоформами pymorphy3.

    Расширение (см. search.lemmas) добавляется OR-веткой: операторы
    websearch сохраняются, ranking остаётся ts_rank (это смягчает шум
    омонимии), а супплетивы и беглые гласные («ребенок» → «ребенка»,
    «мать» → «матери») начинают находиться. Если расширение неприменимо
    (операторы websearch, небезопасные токены) — только базовый запрос.
    """
    base = SearchQuery(query_text, config="russian", search_type="websearch")
    expanded = build_expanded_tsquery(query_text)
    if expanded is None:
        return base
    return base | SearchQuery(expanded, config="russian", search_type="raw")


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

    query = _build_query(query_text)

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

    # Фаза 1: только хиты и ранги. Тяжёлые колонки (full_text редакции —
    # сотни КБ для кодекса — и tsvector'ы) не выкачиваем: на живых данных
    # их трансфер для каждой строки-хита стоил секунды на запрос.
    redaction_hits = apply_doc_filters(
        Redaction.objects.filter(is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED)
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .select_related("document")
        .defer("full_text", "search_vector"),
        "document__",
    ).order_by("-rank")[:_MAX_HITS_PER_SOURCE]

    article_hits = apply_doc_filters(
        Article.objects.filter(
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .select_related("redaction__document")
        .defer(
            "text",
            "search_vector",
            "redaction__full_text",
            "redaction__search_vector",
        ),
        "redaction__document__",
    ).order_by("-rank")[:_MAX_HITS_PER_SOURCE]

    # Схлопывание: на документ остаётся один лучший хит (приоритет по рангу,
    # при равенстве — хит по редакции, как и раньше).
    best: dict[int, Redaction | Article] = {}
    for r in redaction_hits:
        existing = best.get(r.document_id)
        if existing is None or r.rank > existing.rank:
            best[r.document_id] = r
    for a in article_hits:
        doc_id = a.redaction.document_id
        existing = best.get(doc_id)
        if existing is None or a.rank > existing.rank:
            best[doc_id] = a

    # Фаза 2: сниппеты считаем только победителям схлопывания.
    winners = best.values()
    red_snippets = _snippets_by_pk(
        Redaction.objects,
        "full_text",
        [w.pk for w in winners if isinstance(w, Redaction)],
        query,
    )
    art_snippets = _snippets_by_pk(
        Article.objects,
        "text",
        [w.pk for w in winners if isinstance(w, Article)],
        query,
    )

    results = []
    for w in winners:
        if isinstance(w, Redaction):
            results.append(
                SearchResult(
                    document=w.document,
                    rank=w.rank,
                    snippet=_safe_snippet(red_snippets.get(w.pk)),
                )
            )
        else:
            results.append(
                SearchResult(
                    document=w.redaction.document,
                    rank=w.rank,
                    snippet=_safe_snippet(art_snippets.get(w.pk)),
                    article_anchor=w.anchor,
                    article_label=f"{w.get_kind_display()} {w.number}",
                )
            )

    return sorted(results, key=lambda x: x.rank, reverse=True)
