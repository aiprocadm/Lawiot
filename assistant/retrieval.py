"""RAG-извлечение: вопрос → релевантные статьи корпуса (цитируемые единицы).

Переиспользует поисковый сервис (FTS + лемматизация + синонимы), не строит
отдельный индекс. Возвращает чистые dataclass'ы — без сети, без LLM.
"""

from dataclasses import dataclass

from django.urls import reverse

from documents.models import Article, Redaction
from search.services import search_documents


@dataclass
class RetrievedArticle:
    document_title: str
    article_label: str
    anchor: str
    url: str
    text: str
    rank: float


def retrieve(question, *, limit=8):
    """Топ-`limit` статей корпуса, релевантных вопросу.

    Берём только хиты на уровне статьи (article_anchor задан) — это цитируемая
    единица. Тексты статей достаём одним запросом по текущим опубликованным
    редакциям, сопоставляя по паре (документ, anchor).
    """
    question = (question or "").strip()
    if not question:
        return []

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
