"""Фоновые задачи семантического поиска (django-q).

`Redaction.publish()` ставит `embed_redaction_articles` после коммита
транзакции: статьи новой редакции получают эмбеддинги автоматически и сразу
видимы в семантическом поиске (раньше — только после ручного `embed_articles`).
Модель sentence-transformers грузится в воркере qcluster, не в веб-процессе.
"""

import logging

from django_q.tasks import async_task

logger = logging.getLogger(__name__)

_BATCH = 64

# Строковый путь для django-q: воркер импортирует задачу по нему.
EMBED_TASK = "search.tasks.embed_redaction_articles"


def enqueue_embed_redaction(redaction_id):
    """Поставить задачу эмбеддинга редакции. Сбой брокера не ломает publish():
    публикация важнее очереди, пробел добирается ручным `embed_articles`."""
    try:
        async_task(EMBED_TASK, redaction_id)
    except Exception as exc:  # noqa: BLE001 — деградация до ручного бэкфилла
        logger.warning(
            "не удалось поставить задачу эмбеддинга (redaction=%s): %s", redaction_id, exc
        )


def embed_redaction_articles(redaction_id):
    """Эмбеддит статьи редакции, у которых ещё нет вектора.

    No-op, если редакция не текущая опубликованная (удалена или успела
    смениться, пока задача ждала воркера). Возвращает число заэмбеденных.
    """
    from documents.models import Article, Redaction

    qs = Article.objects.filter(
        redaction_id=redaction_id,
        redaction__is_current=True,
        redaction__review_status=Redaction.ReviewStatus.PUBLISHED,
        embedding__isnull=True,
    ).order_by("pk")
    return embed_queryset(qs)


def embed_queryset(articles_qs):
    """Батчевый бэкфилл эмбеддингов по queryset статей. Возвращает число строк."""
    from documents.models import Article
    from search.embeddings import embed_passages

    total = 0
    batch = []

    def flush():
        nonlocal total
        vectors = embed_passages([a.text for a in batch])
        for article, vector in zip(batch, vectors, strict=True):
            article.embedding = vector
        Article.objects.bulk_update(batch, ["embedding"])
        total += len(batch)
        batch.clear()

    for article in articles_qs.iterator(chunk_size=_BATCH):
        batch.append(article)
        if len(batch) >= _BATCH:
            flush()
    if batch:
        flush()
    return total
