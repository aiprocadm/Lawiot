from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from documents.models import Document
from practice.models import CourtDecision

PAGE_SIZE = 20


@login_required
def practice_list(request):
    """Список опубликованной судебной практики; опц. фильтр по акту (?doc=<slug>)."""
    decisions = CourtDecision.objects.filter(is_published=True).select_related("document")

    doc_slug = request.GET.get("doc", "").strip()
    document = None
    if doc_slug:
        document = get_object_or_404(Document, slug=doc_slug)
        decisions = decisions.filter(document=document)

    page_obj = Paginator(decisions, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "practice/practice_list.html",
        {"page_obj": page_obj, "document": document},
    )
