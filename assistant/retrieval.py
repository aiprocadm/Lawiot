"""RAG-извлечение: вопрос → релевантные статьи корпуса (цитируемые единицы).

Переиспользует поисковый сервис (FTS + лемматизация + синонимы), не строит
отдельный индекс. Возвращает чистые dataclass'ы — без сети, без LLM.
"""

from dataclasses import dataclass

from django.urls import reverse

from documents.models import Article, Redaction
from search.services import search_documents, search_in_document


@dataclass
class RetrievedArticle:
    document_title: str
    article_label: str
    anchor: str
    url: str
    text: str
    rank: float


def retrieve(question, *, document=None, limit=8):
    """Топ-`limit` статей, релевантных вопросу.

    Если задан `document` — поиск ОГРАНИЧЕН этим актом («спросить об этом акте»,
    переиспользует search_in_document). Иначе — по всему корпусу. Берём только хиты
    на уровне статьи; тексты достаём по текущим опубликованным редакциям.
    """
    question = (question or "").strip()
    if not question:
        return []

    if document is not None:
        return _retrieve_in_document(question, document, limit)

    results = [r for r in search_documents(question) if r.article_anchor][:limit]
    if not results:
        return []

    doc_ids = {r.document.id for r in results}
    anchors = {r.article_anchor for r in results}
    rows = Article.objects.filter(
        redaction__document_id__in=doc_ids,
        redaction__is_current=True,
        redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        anchor__in=anchors,
    ).values_list("redaction__document_id", "anchor", "text")
    text_by_key = {(doc_id, anchor): text for doc_id, anchor, text in rows}

    out = []
    for r in results:
        text = text_by_key.get((r.document.id, r.article_anchor))
        if not text:
            continue
        out.append(
            RetrievedArticle(
                document_title=r.document.title,
                article_label=r.article_label or "",
                anchor=r.article_anchor,
                url=reverse("document_detail", args=[r.document.slug]) + f"#{r.article_anchor}",
                text=text,
                rank=r.rank,
            )
        )
    return out


def _retrieve_in_document(question, document, limit):
    """Извлечение в пределах одного акта (search_in_document → тексты статей)."""
    hits = search_in_document(document, question, limit=limit)
    if not hits:
        return []
    anchors = [h.anchor for h in hits]
    text_by_anchor = dict(
        Article.objects.filter(
            redaction__document=document,
            redaction__is_current=True,
            redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
            anchor__in=anchors,
        ).values_list("anchor", "text")
    )
    base_url = reverse("document_detail", args=[document.slug])
    out = []
    for h in hits:
        text = text_by_anchor.get(h.anchor)
        if not text:
            continue
        out.append(
            RetrievedArticle(
                document_title=document.title,
                article_label=h.label,
                anchor=h.anchor,
                url=f"{base_url}#{h.anchor}",
                text=text,
                rank=h.rank,
            )
        )
    return out
