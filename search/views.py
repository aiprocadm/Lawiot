from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from search.forms import SearchForm
from search.services import search_documents

PAGE_SIZE = 20


@login_required
def search_view(request):
    form = SearchForm(request.GET or None)
    results = []
    query = request.GET.get("q", "")
    if form.is_valid() and form.cleaned_data.get("q"):
        cd = form.cleaned_data
        results = search_documents(
            cd["q"],
            doc_type=cd["doc_type"],
            status=cd["status"],
            issuing_body=cd["issuing_body"],
            date_from=cd["date_from"],
            date_to=cd["date_to"],
        )

    page_obj = Paginator(results, PAGE_SIZE).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "form": form,
        "page_obj": page_obj,
        "query": query,
        "base_qs": params.urlencode(),
    }

    template = (
        "search/_results.html"
        if request.headers.get("HX-Request")
        else "search/search.html"
    )
    return render(request, template, context)
