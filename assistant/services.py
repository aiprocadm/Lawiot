"""Оркестрация ассистента: retrieve → (опц.) grounded-синтез через Claude API.

Изящная деградация: без `ANTHROPIC_API_KEY` (или без пакета anthropic) фича
работает в режиме retrieval_only — показывает релевантные статьи, без синтеза.
Клиент параметризуем — тесты инъектируют фейк, реальная сеть/ключ не нужны.
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings

from assistant.citations import unverified_citations
from assistant.prompts import SYSTEM_PROMPT, build_user_content
from assistant.retrieval import retrieve

try:  # пакет необязателен: без него доступен только retrieval_only
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
# Потолок выходных токенов ВКЛЮЧАЕТ токены мышления (adaptive). Для короткого
# grounded-ответа 16000 с запасом (non-streaming, без риска таймаута), а
# effort=medium ограничивает глубину мышления — чтобы бюджет не съело мышление,
# оставив пустой ответ.
MAX_TOKENS = 16000
EFFORT = "medium"

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
    # Номера статей, упомянутых в ответе, но отсутствующих в найденном наборе
    # (сигнал возможной галлюцинации — показываем пользователю предупреждение).
    unverified_citations: list = field(default_factory=list)


def _default_client():
    key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not key or anthropic is None:
        return None
    return anthropic.Anthropic(api_key=key)


def _build_messages(question, articles, history):
    """Сообщения для модели: история диалога + текущий вопрос со статьями."""
    messages = [{"role": turn["role"], "content": turn["content"]} for turn in (history or [])]
    messages.append({"role": "user", "content": build_user_content(question, articles)})
    return messages


def answer_question(question, *, document=None, history=None, client=None):
    """Ответ ассистента на вопрос пользователя.

    Если задан `document` — извлечение ограничено этим актом («спросить об этом
    акте»). `history` — список прошлых ходов диалога ({"role","content"}); даёт
    модели контекст для уточняющих вопросов (многоходовой диалог). Извлечение —
    всегда по ТЕКУЩЕМУ вопросу; проверка цитат — по текущим статьям. Синтезирует
    ответ только при наличии клиента; иначе — retrieval_only. Ошибка API/refusal
    → откат в retrieval_only.
    """
    question = (question or "").strip()
    articles = retrieve(question, document=document)
    if not articles:
        return AssistantAnswer(question=question, articles=[], mode=MODE_NO_RESULTS)

    if client is None:
        client = _default_client()
    if client is None:
        return AssistantAnswer(question=question, articles=articles, mode=MODE_RETRIEVAL_ONLY)

    messages = _build_messages(question, articles, history)

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            system=SYSTEM_PROMPT,
            messages=messages,
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

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    # Пустой ответ (напр. бюджет съело мышление → stop_reason=max_tokens) →
    # не показываем пустой «синтез», откатываемся к статьям.
    if not text:
        return AssistantAnswer(
            question=question, articles=articles, mode=MODE_RETRIEVAL_ONLY, error="empty"
        )

    return AssistantAnswer(
        question=question,
        articles=articles,
        answer_text=text,
        mode=MODE_SYNTHESIZED,
        unverified_citations=unverified_citations(text, articles),
    )


def stream_answer(question, *, document=None, history=None, client=None):
    """Стриминг grounded-ответа (AI-срез 2).

    Возвращает кортеж `(articles, deltas)`:
    - `articles` — статьи-основания (готовы сразу, до стрима: для немедленной
      отрисовки и для проверки цитат в финале);
    - `deltas` — генератор текстовых дельт ответа (str).

    `deltas` пуст, если нет статей (no_results) или нет клиента (retrieval_only).
    Исключение по ходу стрима → лог + аккуратное завершение (что успело
    стримнуться, остаётся; вью не падает). Финал считает вызывающий код через
    `finalize_answer` по накопленному тексту.
    """
    question = (question or "").strip()
    articles = retrieve(question, document=document)
    if not articles:
        return [], iter(())

    if client is None:
        client = _default_client()
    if client is None:
        return articles, iter(())

    messages = _build_messages(question, articles, history)

    def _deltas():
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={"effort": EFFORT},
                system=SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                yield from stream.text_stream
        except Exception as exc:  # noqa: BLE001 — деградация, не падение вью
            logger.warning("assistant stream failed: %s", exc)

    return articles, _deltas()


def finalize_answer(question, articles, text):
    """Собрать `AssistantAnswer` из накопленного по стриму текста.

    Зеркалит ветвление `answer_question`: нет статей → no_results; пустой текст →
    retrieval_only; иначе synthesized с проверкой цитат.
    """
    question = (question or "").strip()
    text = (text or "").strip()
    if not articles:
        return AssistantAnswer(question=question, articles=[], mode=MODE_NO_RESULTS)
    if not text:
        return AssistantAnswer(
            question=question, articles=articles, mode=MODE_RETRIEVAL_ONLY, error="empty"
        )
    return AssistantAnswer(
        question=question,
        articles=articles,
        answer_text=text,
        mode=MODE_SYNTHESIZED,
        unverified_citations=unverified_citations(text, articles),
    )
