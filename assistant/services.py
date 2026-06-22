"""Оркестрация ассистента: retrieve → (опц.) grounded-синтез через Claude API.

Изящная деградация: без `ANTHROPIC_API_KEY` (или без пакета anthropic) фича
работает в режиме retrieval_only — показывает релевантные статьи, без синтеза.
Клиент параметризуем — тесты инъектируют фейк, реальная сеть/ключ не нужны.
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings

from assistant.prompts import SYSTEM_PROMPT, build_user_content
from assistant.retrieval import retrieve

try:  # пакет необязателен: без него доступен только retrieval_only
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 4000

MODE_SYNTHESIZED = "synthesized"
MODE_RETRIEVAL_ONLY = "retrieval_only"
MODE_NO_RESULTS = "no_results"


@dataclass
class AssistantAnswer:
    question: str
    articles: list = field(default_factory=list)
    answer_text: str | None = None
    mode: str = MODE_RETRIEVAL_ONLY
    error: str | None = None


def _default_client():
    key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not key or anthropic is None:
        return None
    return anthropic.Anthropic(api_key=key)


def answer_question(question, *, client=None):
    """Ответ ассистента на вопрос пользователя.

    Всегда сначала извлекает статьи. Синтезирует ответ только при наличии
    клиента (ключ настроен или клиент передан явно); иначе — retrieval_only.
    Любая ошибка API или refusal → откат в retrieval_only (статьи полезны сами).
    """
    question = (question or "").strip()
    articles = retrieve(question)
    if not articles:
        return AssistantAnswer(question=question, articles=[], mode=MODE_NO_RESULTS)

    if client is None:
        client = _default_client()
    if client is None:
        return AssistantAnswer(question=question, articles=articles, mode=MODE_RETRIEVAL_ONLY)

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_content(question, articles)}],
        )
    except Exception as exc:  # noqa: BLE001 — любая ошибка API → деградация, не падение
        logger.warning("assistant synthesis failed: %s", exc)
        return AssistantAnswer(
            question=question, articles=articles, mode=MODE_RETRIEVAL_ONLY, error=str(exc)
        )

    if getattr(resp, "stop_reason", None) == "refusal":
        return AssistantAnswer(
            question=question, articles=articles, mode=MODE_RETRIEVAL_ONLY, error="refusal"
        )

    text = "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()
    return AssistantAnswer(
        question=question, articles=articles, answer_text=text, mode=MODE_SYNTHESIZED
    )
