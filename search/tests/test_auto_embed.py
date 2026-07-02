"""Авто-бэкфилл эмбеддингов при публикации редакции (roadmap §6.1).

Публикация ставит django-q задачу `search.tasks.embed_redaction_articles`
(после коммита транзакции); сама задача эмбедит статьи редакции без вектора.
Раньше новые статьи были невидимы в семантическом поиске до ручного
`embed_articles`.
"""

import logging

import pytest

from documents.models import Redaction
from documents.tests.factories import make_article, make_document, make_redaction
from search import embeddings, tasks


def _vec(dim0=True):
    v = [0.0] * embeddings.EMBED_DIM
    v[0 if dim0 else 1] = 1.0
    return v


@pytest.fixture
def fake_backend():
    """Детерминированный бэкенд: каждый текст → концепт A (dim0=1)."""
    calls = []

    def backend(texts):
        calls.append(list(texts))
        return [_vec() for _ in texts]

    embeddings.set_backend(backend)
    yield calls
    embeddings.reset_backend()


def _make_published(slug="doc-a", n_articles=1):
    doc = make_document(slug=slug, official_number=slug, title=f"Акт {slug}")
    red = make_redaction(doc, full_text="текст")
    for i in range(n_articles):
        make_article(red, number=str(i + 1), title="", text=f"текст статьи {i + 1}")
    red.publish()
    return red


@pytest.mark.django_db
def test_publish_enqueues_embedding_task(django_capture_on_commit_callbacks, monkeypatch):
    enqueued = []
    monkeypatch.setattr(
        "search.tasks.async_task", lambda func, *args, **kwargs: enqueued.append((func, args))
    )
    doc = make_document(slug="doc-q", official_number="1-q", title="Акт")
    red = make_redaction(doc, full_text="текст")

    with django_capture_on_commit_callbacks(execute=True):
        red.publish()

    assert enqueued == [("search.tasks.embed_redaction_articles", (red.pk,))]


@pytest.mark.django_db
def test_enqueue_failure_does_not_break_publish(
    django_capture_on_commit_callbacks, monkeypatch, caplog
):
    def boom(*args, **kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr("search.tasks.async_task", boom)
    doc = make_document(slug="doc-f", official_number="1-f", title="Акт")
    red = make_redaction(doc, full_text="текст")

    # Логгер search настроен с propagate=False — подключаем caplog напрямую.
    task_logger = logging.getLogger("search.tasks")
    task_logger.addHandler(caplog.handler)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            red.publish()  # не должен поднять исключение
    finally:
        task_logger.removeHandler(caplog.handler)

    red.refresh_from_db()
    assert red.review_status == Redaction.ReviewStatus.PUBLISHED
    assert "broker down" in caplog.text


@pytest.mark.django_db
def test_task_embeds_only_articles_without_vector(fake_backend):
    red = _make_published(n_articles=2)
    art_done, art_todo = red.articles.order_by("pk")
    preexisting = _vec(dim0=False)
    art_done.embedding = preexisting
    art_done.save(update_fields=["embedding"])

    n = tasks.embed_redaction_articles(red.pk)

    assert n == 1
    art_done.refresh_from_db()
    art_todo.refresh_from_db()
    assert art_todo.embedding is not None
    assert list(art_done.embedding) == preexisting  # существующий вектор не тронут


@pytest.mark.django_db
def test_task_noop_for_draft_or_missing_redaction(fake_backend):
    doc = make_document(slug="doc-d", official_number="1-d", title="Акт")
    draft = make_redaction(doc, full_text="текст")
    make_article(draft, number="1", title="", text="текст")

    assert tasks.embed_redaction_articles(draft.pk) == 0
    assert tasks.embed_redaction_articles(draft.pk + 10_000) == 0
    assert draft.articles.filter(embedding__isnull=False).count() == 0
