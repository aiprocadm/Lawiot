from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from assistant.services import answer_question
from documents.models import Document


@login_required
def assistant_view(request):
    question = request.GET.get("q", "").strip()
    doc_slug = request.GET.get("doc", "").strip()
    document = get_object_or_404(Document, slug=doc_slug) if doc_slug else None
    answer = answer_question(question, document=document) if question else None
    context = {"question": question, "answer": answer, "document": document}
    template = (
        "assistant/_answer.html"
        if request.headers.get("HX-Request")
        else "assistant/assistant.html"
    )
    return render(request, template, context)
