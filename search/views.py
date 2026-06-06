from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from search.forms import SearchForm
from search.services import search_documents


@login_required
def search_view(request):
    form = SearchForm(request.GET or None)
    results = []
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
    return render(
        request,
        "search/search.html",
        {"form": form, "results": results, "query": request.GET.get("q", "")},
    )
