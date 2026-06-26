"""Тесты семантического поиска (AI-срез 4)."""

import pytest

from documents.models import Document
from documents.tests.factories import make_article, make_document, make_redaction
from search import embeddings
from search.services import search_documents


def _vec(dim0):
    """384-мерный единичный вектор: dim0=1 → концепт A, иначе dim1=1 → концепт B."""
    v = [0.0] * embeddings.EMBED_DIM
    v[0 if dim0 else 1] = 1.0
    return v


@pytest.fixture
def fake_query_concept_a():
    """Бэкенд эмбеддингов: запрос всегда указывает на концепт A (dim0)."""
    calls = []

    def backend(texts):
        calls.append(list(texts))
        return [_vec(dim0=True) for _ in texts]

    embeddings.set_backend(backend)
    yield calls
    embeddings.reset_backend()


def _publish_article(slug, number, text, *, embedding=None):
    doc = make_document(slug=slug, official_number=number, title=f"Акт {number}")
    red = make_redaction(doc, full_text="")
    art = make_article(red, number=number, title="", text=text)
    red.publish()
    if embedding is not None:
        art.embedding = embedding
        art.save(update_fields=["embedding"])
    return doc, art


@pytest.mark.django_db
def test_semantic_adds_document_fts_missed(fake_query_concept_a):
    # DB найдётся лексически по слову «увольнение».
    db, _ = _publish_article(
        "db", "100", "увольнение по собственному желанию", embedding=_vec(dim0=False)
    )
    # DA лексически не содержит «увольнение», но семантически близка (концепт A).
    da, _ = _publish_article("da", "200", "нечто про марсоход и кратеры", embedding=_vec(dim0=True))

    results = search_documents("увольнение")
    slugs = [r.document.slug for r in results]

    assert "db" in slugs  # лексический хит
    assert "da" in slugs  # добавлен по смыслу
    da_result = next(r for r in results if r.document.slug == "da")
    assert da_result.semantic is True
    # FTS-результаты идут первыми, семантические — после.
    assert slugs.index("db") < slugs.index("da")


@pytest.mark.django_db
def test_no_backend_is_pure_fts(fake_query_concept_a, monkeypatch):
    # Без бэкенда embed_query вернёт None → семантика не добавляется.
    # Патчим имя в МЕСТЕ ВЫЗОВА: services.py связал его через
    # `from search.embeddings import embed_query`, поэтому setattr на модуле
    # embeddings эту копию не затрагивает (и с установленным sentence-transformers
    # реальная модель отработала бы и добавила «da»).
    embeddings.reset_backend()
    monkeypatch.setattr("search.services.embed_query", lambda text: None)
    da, _ = _publish_article("da", "200", "нечто про марсоход", embedding=_vec(True))
    db, _ = _publish_article("db", "100", "увольнение работника", embedding=_vec(False))

    results = search_documents("увольнение")
    slugs = [r.document.slug for r in results]
    assert "db" in slugs
    assert "da" not in slugs  # без эмбеддингов — только FTS


@pytest.mark.django_db
def test_semantic_skips_articles_without_embedding(fake_query_concept_a):
    db, _ = _publish_article("db", "100", "увольнение работника", embedding=_vec(False))
    # DA без эмбеддинга (бэкфилл не запускался) — не должна попасть в семантику.
    da, _ = _publish_article("da", "200", "иной текст", embedding=None)

    results = search_documents("увольнение")
    slugs = [r.document.slug for r in results]
    assert "da" not in slugs


@pytest.mark.django_db
def test_semantic_respects_doc_filters(fake_query_concept_a):
    db, _ = _publish_article("db", "100", "увольнение работника", embedding=_vec(False))
    da, _ = _publish_article("da", "200", "марсоход", embedding=_vec(True))
    Document.objects.filter(slug="da").update(doc_type=Document.DocType.FEDERAL_LAW)

    # Фильтр по типу CODE исключает DA даже из семантики.
    results = search_documents("увольнение", doc_type=Document.DocType.CODE)
    slugs = [r.document.slug for r in results]
    assert "da" not in slugs


# --- Модуль эмбеддингов ---------------------------------------------------


def test_embed_query_applies_query_prefix():
    seen = []

    def backend(texts):
        seen.extend(texts)
        return [_vec(True) for _ in texts]

    embeddings.set_backend(backend)
    try:
        vec = embeddings.embed_query("отпуск")
    finally:
        embeddings.reset_backend()
    assert vec == _vec(True)
    assert seen == ["query: отпуск"]


def test_embed_passages_applies_passage_prefix():
    seen = []

    def backend(texts):
        seen.extend(texts)
        return [_vec(True) for _ in texts]

    embeddings.set_backend(backend)
    try:
        embeddings.embed_passages(["текст статьи"])
    finally:
        embeddings.reset_backend()
    assert seen == ["passage: текст статьи"]


def test_embed_query_degrades_to_none_without_backend(monkeypatch):
    # Сбой реального бэкенда (нет пакета/модели) → embed_query глотает → None.
    # Мокаем явно, чтобы тест не зависел от наличия sentence-transformers в env.
    embeddings.reset_backend()

    def broken(texts):
        raise ImportError("No module named 'sentence_transformers'")

    monkeypatch.setattr(embeddings, "_real_backend", broken)
    assert embeddings.embed_query("отпуск") is None


def test_embed_query_empty_is_none():
    assert embeddings.embed_query("   ") is None


# --- Команда бэкфилла -----------------------------------------------------


@pytest.mark.django_db
def test_embed_articles_backfills(fake_query_concept_a):
    from django.core.management import call_command

    _, art = _publish_article("db", "100", "увольнение работника", embedding=None)
    assert art.embedding is None

    call_command("embed_articles")

    art.refresh_from_db()
    assert art.embedding is not None
    assert len(list(art.embedding)) == embeddings.EMBED_DIM
