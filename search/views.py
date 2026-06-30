from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from search.forms import SearchForm
from search.services import search_documents
from search.suggest import suggest_query

PAGE_SIZE = 20


@login_required
def search_view(request):
    form = SearchForm(request.GET or None)
    results = []
    suggestion = None
    suggestion_qs = ""
    query = request.GET.get("q", "")
    if form.is_valid() and form.cleaned_data.get("q"):
        cd = form.cleaned_data
        filters = dict(
            doc_type=cd["doc_type"],
            status=cd["status"],
            issuing_body=cd["issuing_body"],
            date_from=cd["date_from"],
            date_to=cd["date_to"],
        )
        results = search_documents(cd["q"], **filters)
        if cd.get("sort") == "date":
            # Новые первыми по дате подписания; акты без даты — в конце.
            results = sorted(
                results,
                key=lambda r: (r.document.sign_date is not None, r.document.sign_date),
                reverse=True,
            )
        if not results:
            # Did-you-mean: только при нуле и только если исправление даёт результаты.
            candidate = suggest_query(cd["q"])
            if candidate and search_documents(candidate, **filters):
                suggestion = candidate
                sug_params = request.GET.copy()
                sug_params["q"] = candidate
                sug_params.pop("page", None)
                suggestion_qs = sug_params.urlencode()

    page_obj = Paginator(results, PAGE_SIZE).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "form": form,
        "page_obj": page_obj,
        "query": query,
        "base_qs": params.urlencode(),
        "suggestion": suggestion,
        "suggestion_qs": suggestion_qs,
    }

    template = "search/_results.html" if request.headers.get("HX-Request") else "search/search.html"
    return render(request, template, context)
