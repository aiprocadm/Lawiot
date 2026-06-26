from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from bookmarks.models import Bookmark
from documents.models import Document


def _safe_next(request, fallback="document_list"):
    """URL из `next`, только если он ведёт на этот же сайт.

    `next` приходит из формы (данные пользователя): без проверки redirect()
    охотно уводит на любой внешний адрес (open redirect — вектор фишинга).
    Сверяем хост и схему штатным хелпером Django; чужой/битый next → fallback.
    """
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return fallback


@login_required
def bookmark_list(request):
    bookmarks = (
        Bookmark.objects.filter(user=request.user).select_related("document").order_by("-created_at")
    )
    return render(request, "bookmarks/bookmark_list.html", {"bookmarks": bookmarks})


@login_required
@require_POST
def bookmark_toggle(request, slug):
    document = get_object_or_404(Document, slug=slug)
    bookmark, created = Bookmark.objects.get_or_create(user=request.user, document=document)
    if not created:
        bookmark.delete()
    return redirect(_safe_next(request))
