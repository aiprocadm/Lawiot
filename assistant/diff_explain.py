"""AI-объяснение изменений между редакциями акта (AI-срез 5).

Берёт уже посчитанный diff статей («что изменилось») и просит Claude объяснить
суть и практический смысл изменений ПО ТЕКСТУ ДО/ПОСЛЕ — не выдумывая норм. Это
суммаризация переданного diff, а не генерация права (низкий риск галлюцинаций),
но guardrails и дисклеймер сохраняются.

Изящная деградация: без `ANTHROPIC_API_KEY`/пакета anthropic или при любой ошибке
API — режим `unavailable` (сам diff остаётся виден читателю). Клиент инъектируем —
тесты не ходят в сеть.
"""

import logging
from dataclasses import dataclass

from assistant.prompts import cap_text
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
MODE_NO_CHANGES = "no_changes"
MODE_UNAVAILABLE = "unavailable"

_STATUS_RU = {"changed": "изменена", "added": "добавлена", "removed": "удалена"}

SYSTEM_PROMPT = (
    "Ты — справочный ассистент по трудовому праву Российской Федерации. Тебе дают "
    "изменения между двумя редакциями нормативного акта: для каждой затронутой "
    "статьи — её прежний и новый текст. Объясни по-русски, кратко и по делу, ЧТО "
    "именно изменилось и какой у этого практический смысл для работника и "
    "работодателя. Опирайся СТРОГО на приведённый текст «до/после» и НИЧЕГО не "
    "домысливай: не ссылайся на нормы, которых нет в переданных фрагментах. Это "
    "справочная информация, а не юридическая консультация."
)


@dataclass
class DiffExplanation:
    mode: str = MODE_UNAVAILABLE
    text: str | None = None
    error: str | None = None


def build_diff_prompt(changes):
    """Собирает пользовательское сообщение из списка изменений статей.

    `changes` — список dict'ов {number, status, old_text, new_text}.
    """
    blocks = []
    for ch in changes:
        status_ru = _STATUS_RU.get(ch["status"], ch["status"])
        block = [f"Статья {ch['number']} — {status_ru}."]
        if ch.get("old_text"):
            block.append(f"Было:\n{cap_text(ch['old_text'])}")
        if ch.get("new_text"):
            block.append(f"Стало:\n{cap_text(ch['new_text'])}")
        blocks.append("\n".join(block))
    body = "\n\n".join(blocks)
    return (
        "Изменения между редакциями:\n\n"
        f"{body}\n\n"
        "Объясни суть и практический смысл этих изменений, опираясь только на "
        "приведённый текст."
    )


def explain_diff(changes, *, client=None):
    """Объяснение изменений редакции. Пустой список → no_changes (без вызова модели)."""
    if not changes:
        return DiffExplanation(mode=MODE_NO_CHANGES)

    if client is None:
        client = _default_client()
    if client is None:
        return DiffExplanation(mode=MODE_UNAVAILABLE)

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_diff_prompt(changes)}],
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — любая ошибка API → деградация, не падение
        logger.warning("diff explanation failed: %s", exc, exc_info=True)
        return DiffExplanation(mode=MODE_UNAVAILABLE, error=str(exc))

    _log_usage(resp, "diff")

    if getattr(resp, "stop_reason", None) == "refusal":
        return DiffExplanation(mode=MODE_UNAVAILABLE, error="refusal")

    text = _response_text(resp)
    if not text:
        return DiffExplanation(mode=MODE_UNAVAILABLE, error="empty")

    return DiffExplanation(mode=MODE_EXPLAINED, text=text)
