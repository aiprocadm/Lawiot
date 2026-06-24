from dataclasses import dataclass

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import F
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from pgvector.django import CosineDistance

from documents.models import Article, Document, Redaction
from search.embeddings import embed_query
from search.lemmas import build_expanded_tsquery


@dataclass
class SearchResult:
    document: Document
    rank: float
    snippet: str
    article_anchor: str | None = None
    article_label: str | None = None
    # True — документ найден семантически (перефразировка), не лексическим FTS.
    semantic: bool = False


# Сколько ближайших по смыслу статей тянуть и сколько семантических документов
# максимум добавлять к FTS-результатам.
_SEMANTIC_FETCH = 30
_SEMANTIC_MAX = 10
_SEMANTIC_SNIPPET_CHARS = 200


@dataclass
class ArticleHit:
    """Совпадение статьи при поиске В ПРЕДЕЛАХ одного акта."""

    anchor: str
    label: str
    title: str
    snippet: str
    rank: float


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

    filters = dict(
        doc_type=doc_type,
        status=status,
        issuing_body=issuing_body,
        date_from=date_from,
        date_to=date_to,
    )

    def apply_doc_filters(qs, prefix):
        return _apply_doc_filters(qs, prefix, **filters)

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

    fts_results = sorted(results, key=lambda x: x.rank, reverse=True)
    return _semantic_supplement(query_text, fts_results, **filters)


def _apply_doc_filters(qs, prefix, *, doc_type, status, issuing_body, date_from, date_to):
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


def _plain_snippet(text) -> SafeString:
    """Сниппет для семантического хита: обрез текста статьи (без ts_headline —
    у запроса может не быть общих слов с найденным по смыслу текстом)."""
    text = (text or "").strip()
    if len(text) > _SEMANTIC_SNIPPET_CHARS:
        text = text[:_SEMANTIC_SNIPPET_CHARS].rstrip() + "…"
    return mark_safe(escape(text))


def _semantic_supplement(query_text, fts_results, **filters):
    """Аддитивно дополнить FTS-результаты документами, найденными по смыслу.

    FTS-порядок сохраняется; добавляются ТОЛЬКО документы, которых нет в
    FTS-результатах (перефразировки, которые лексический поиск пропустил).
    Без бэкенда эмбеддингов / при ошибке — возвращает FTS как есть.
    """
    vec = embed_query(query_text)
    if vec is None:
        return fts_results

    qs = (
        Article.objects.filter(
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        .exclude(embedding=None)
        .select_related("redaction__document")
        # Тяжёлые колонки не выкачиваем (как в FTS-фазе): вектор использован для
        # ORDER BY в БД, tsvector не нужен; text оставляем — из него сниппет.
        .defer("search_vector", "embedding", "redaction__full_text", "redaction__search_vector")
    )
    qs = _apply_doc_filters(qs, "redaction__document__", **filters)
    qs = qs.annotate(distance=CosineDistance("embedding", vec)).order_by("distance")[
        :_SEMANTIC_FETCH
    ]

    seen = {r.document.id for r in fts_results}
    extras = []
    for a in qs:
        doc = a.redaction.document
        if doc.id in seen:
            continue
        seen.add(doc.id)  # один лучший (ближайший) хит на документ
        extras.append(
            SearchResult(
                document=doc,
                rank=0.0,
                snippet=_plain_snippet(a.text),
                article_anchor=a.anchor,
                article_label=f"{a.get_kind_display()} {a.number}",
                semantic=True,
            )
        )
        if len(extras) >= _SEMANTIC_MAX:
            break
    return fts_results + extras


def search_in_document(document, query_text, *, limit=50):
    """Поиск статей В ПРЕДЕЛАХ одного акта (текущая опубликованная редакция).

    Без схлопывания по документу (в отличие от search_documents): возвращает все
    совпавшие статьи, ранжированные ts_rank. Переиспользует расширение запроса и
    двухфазную подсветку.
    """
    query_text = (query_text or "").strip()
    if not query_text:
        return []

    query = _build_query(query_text)
    hits = list(
        Article.objects.filter(
            redaction__document=document,
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        .filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .defer("text", "search_vector", "redaction__full_text", "redaction__search_vector")
        .order_by("-rank")[:limit]
    )
    snippets = _snippets_by_pk(Article.objects, "text", [h.pk for h in hits], query)
    return [
        ArticleHit(
            anchor=h.anchor,
            label=f"{h.get_kind_display()} {h.number}".strip(),
            title=h.title,
            snippet=_safe_snippet(snippets.get(h.pk)),
            rank=h.rank,
        )
        for h in hits
    ]
