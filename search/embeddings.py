"""Эмбеддинги для семантического поиска (AI-срез 4).

Локальная модель `intfloat/multilingual-e5-small` (384-dim) через
sentence-transformers. Бэкенд ленив и инъектируем: тесты подменяют его
детерминированной функцией (`set_backend`), реальная модель/torch не нужны.

Грациозная деградация: нет пакета/модели → `embed_query` возвращает None
(поиск падает обратно в чистый FTS). Бэкфилл (`embed_passages`) — явная
операция, поэтому при отсутствии бэкенда поднимает понятную ошибку.

e5-модели требуют префиксы инструкций: «query: …» для запросов и
«passage: …» для индексируемых текстов — без них качество заметно падает.
"""

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

EMBED_DIM = 384
MODEL_NAME = "intfloat/multilingual-e5-small"

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "

# Инъекция для тестов: callable(list[str]) -> list[list[float]]. None → реальный
# ленивый бэкенд sentence-transformers.
_backend = None


def set_backend(fn):
    """Подменить бэкенд эмбеддингов (тесты). `fn(list[str]) -> list[list[float]]`."""
    global _backend
    _backend = fn


def reset_backend():
    set_backend(None)


def _real_backend(texts):
    """Ленивая загрузка sentence-transformers (кэшируется на процесс)."""
    model = _load_model()
    # normalize_embeddings=True → косинус сводится к скалярному произведению.
    return [list(v) for v in model.encode(texts, normalize_embeddings=True)]


@lru_cache(maxsize=1)
def _load_model():
    """Загрузить модель один раз на процесс (кэш на уровне модуля)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def _encode(texts):
    backend = _backend if _backend is not None else _real_backend
    return backend(list(texts))


def embed_passages(texts):
    """Векторы для индексируемых текстов (бэкфилл). Поднимает при отсутствии бэкенда."""
    prefixed = [_PASSAGE_PREFIX + (t or "") for t in texts]
    return _encode(prefixed)


def embed_query(text):
    """Вектор запроса или None при любой ошибке/отсутствии бэкенда (деградация)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        vectors = _encode([_QUERY_PREFIX + text])
        return vectors[0] if vectors else None
    except Exception as exc:  # noqa: BLE001 — нет модели/ошибка → чистый FTS
        logger.warning("query embedding failed: %s", exc)
        return None
