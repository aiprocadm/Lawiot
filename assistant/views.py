from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from assistant.services import answer_question


@login_required
def assistant_view(request):
    question = request.GET.get("q", "").strip()
    answer = answer_question(question) if question else None
    context = {"question": question, "answer": answer}
    template = (
        "assistant/_answer.html"
        if request.headers.get("HX-Request")
        else "assistant/assistant.html"
    )
    return render(request, template, context)
