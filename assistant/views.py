from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from assistant.services import answer_question
from documents.models import Document

SESSION_KEY = "assistant_conv"
MAX_TURNS = 10  # ограничиваем рост сессии


@login_required
def assistant_view(request):
    doc_slug = request.GET.get("doc", "").strip()
    document = get_object_or_404(Document, slug=doc_slug) if doc_slug else None

    conversation = request.session.get(SESSION_KEY, [])
    if request.GET.get("reset"):
        conversation = []
        request.session[SESSION_KEY] = conversation

    question = request.GET.get("q", "").strip()
    if question:
        # История диалога для модели: прошлые вопрос/ответ (без блоков статей).
        history = []
        for turn in conversation:
            history.append({"role": "user", "content": turn["q"]})
            if turn.get("a"):
                history.append({"role": "assistant", "content": turn["a"]})

        answer = answer_question(question, document=document, history=history)
        turn = {
            "q": question,
            "a": answer.answer_text,
            "mode": answer.mode,
            "unverified": list(answer.unverified_citations),
            "articles": [
                {"url": a.url, "label": a.article_label, "title": a.document_title}
                for a in answer.articles
            ],
        }
        conversation = (conversation + [turn])[-MAX_TURNS:]
        request.session[SESSION_KEY] = conversation

    context = {"conversation": conversation, "document": document}
    template = (
        "assistant/_conversation.html"
        if request.headers.get("HX-Request")
        else "assistant/assistant.html"
    )
    return render(request, template, context)
