from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, render

from assistant.services import answer_question, finalize_answer, stream_answer
from documents.models import Document

SESSION_KEY = "assistant_conv"
MAX_TURNS = 10  # ограничиваем рост сессии


def _history_from(conversation):
    """Прошлые ходы диалога → сообщения для модели (без блоков статей)."""
    history = []
    for turn in conversation:
        history.append({"role": "user", "content": turn["q"]})
        if turn.get("a"):
            history.append({"role": "assistant", "content": turn["a"]})
    return history


def _turn_from_answer(question, answer):
    """Ход диалога для сохранения в сессию и отрисовки."""
    return {
        "q": question,
        "a": answer.answer_text,
        "mode": answer.mode,
        "unverified": list(answer.unverified_citations),
        "articles": [
            {"url": a.url, "label": a.article_label, "title": a.document_title}
            for a in answer.articles
        ],
    }


def _document_from(request):
    doc_slug = request.GET.get("doc", "").strip()
    return get_object_or_404(Document, slug=doc_slug) if doc_slug else None


@login_required
def assistant_view(request):
    """Блокирующий путь (fallback без JS): полный ответ за один запрос."""
    document = _document_from(request)

    conversation = request.session.get(SESSION_KEY, [])
    if request.GET.get("reset"):
        conversation = []
        request.session[SESSION_KEY] = conversation

    question = request.GET.get("q", "").strip()
    if question:
        answer = answer_question(question, document=document, history=_history_from(conversation))
        conversation = (conversation + [_turn_from_answer(question, answer)])[-MAX_TURNS:]
        request.session[SESSION_KEY] = conversation

    context = {"conversation": conversation, "document": document}
    template = (
        "assistant/_conversation.html"
        if request.headers.get("HX-Request")
        else "assistant/assistant.html"
    )
    return render(request, template, context)


@login_required
def assistant_stream(request):
    """Стриминг-путь (AI-срез 2): текстовые дельты ответа по мере генерации.

    Ход диалога персистится в сессию в финализаторе генератора —
    `SessionMiddleware` уже отработал к моменту стрима тела, поэтому сохраняем
    стор явно (`session.save()`).
    """
    document = _document_from(request)
    question = request.GET.get("q", "").strip()
    conversation = request.session.get(SESSION_KEY, [])

    if not question:
        return StreamingHttpResponse(iter(()), content_type="text/plain; charset=utf-8")

    articles, deltas = stream_answer(
        question, document=document, history=_history_from(conversation)
    )

    def body():
        acc = []
        for chunk in deltas:
            acc.append(chunk)
            yield chunk
        answer = finalize_answer(question, articles, "".join(acc))
        convo = request.session.get(SESSION_KEY, [])
        convo = (convo + [_turn_from_answer(question, answer)])[-MAX_TURNS:]
        request.session[SESSION_KEY] = convo
        request.session.save()

    response = StreamingHttpResponse(body(), content_type="text/plain; charset=utf-8")
    response["X-Accel-Buffering"] = "no"
    response["Cache-Control"] = "no-cache"
    return response
