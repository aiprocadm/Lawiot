from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from history.models import ViewHistory

PAGE_SIZE = 30


@login_required
def history_list(request):
    """Недавно просмотренные акты текущего пользователя (свежие сверху)."""
    entries = ViewHistory.objects.filter(user=request.user).select_related("document")
    page_obj = Paginator(entries, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "history/history_list.html", {"page_obj": page_obj})
