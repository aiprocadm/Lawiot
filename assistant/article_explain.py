"""AI-разъяснение отдельной статьи «простыми словами».

Понижает барьер к плотному юридическому тексту: по тексту ОДНОЙ статьи Claude
даёт короткий пересказ на простом языке. Заземление строго на текст статьи —
это пересказ переданного, а не генерация норм (низкий риск галлюцинаций), но
guardrails и дисклеймер сохраняются.

Изящная деградация: без `ANTHROPIC_API_KEY`/пакета anthropic или при любой ошибке
API — режим `unavailable` (исходный текст статьи остаётся виден). Клиент
инъектируем — тесты не ходят в сеть.
"""

import logging
from dataclasses import dataclass

from assistant.services import (
    EFFORT,
    MAX_TOKENS,
    MODEL,
    REQUEST_TIMEOUT,
    _default_client,
    _log_usage,
    _response_text,
)

logger = logging.getLogger(__name__)

MODE_EXPLAINED = "explained"
MODE_UNAVAILABLE = "unavailable"

SYSTEM_PROMPT = (
    "Ты — справочный ассистент по трудовому праву Российской Федерации. Тебе дают "
    "текст одной статьи нормативного акта. Перескажи её СУТЬ простыми словами для "
    "неюриста: что она означает на практике для работника и работодателя. "
    "Опирайся СТРОГО на приведённый текст статьи и НИЧЕГО не домысливай: не "
    "добавляй норм, которых в тексте нет. Пиши по-русски, кратко, без канцелярита. "
    "Это справочная информация, а не юридическая консультация."
)


@dataclass
class ArticleExplanation:
    mode: str = MODE_UNAVAILABLE
    text: str | None = None
    error: str | None = None


def explain_article(article_text, *, client=None):
    """Пересказ статьи простыми словами. Пустой текст → unavailable (без вызова модели)."""
    article_text = (article_text or "").strip()
    if not article_text:
        return ArticleExplanation(mode=MODE_UNAVAILABLE)

    if client is None:
        client = _default_client()
    if client is None:
        return ArticleExplanation(mode=MODE_UNAVAILABLE)

    user_content = (
        f"Текст статьи:\n\n{article_text}\n\n"
        "Перескажи суть этой статьи простыми словами, опираясь только на её текст."
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — любая ошибка API → деградация, не падение
        logger.warning("article explanation failed: %s", exc, exc_info=True)
        return ArticleExplanation(mode=MODE_UNAVAILABLE, error=str(exc))

    _log_usage(resp, "article")

    if getattr(resp, "stop_reason", None) == "refusal":
        return ArticleExplanation(mode=MODE_UNAVAILABLE, error="refusal")

    text = _response_text(resp)
    if not text:
        return ArticleExplanation(mode=MODE_UNAVAILABLE, error="empty")

    return ArticleExplanation(mode=MODE_EXPLAINED, text=text)
