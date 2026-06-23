from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from glossary.models import Term

PAGE_SIZE = 50


@login_required
def glossary_list(request):
    """Алфавитный список опубликованных терминов; опц. подстрочный фильтр ?q=."""
    terms = Term.objects.filter(is_published=True).select_related("document")

    query = request.GET.get("q", "").strip()
    if query:
        terms = terms.filter(Q(term__icontains=query) | Q(definition__icontains=query))

    page_obj = Paginator(terms, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "glossary/glossary_list.html",
        {"page_obj": page_obj, "query": query},
    )
