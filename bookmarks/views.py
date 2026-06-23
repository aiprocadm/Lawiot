from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from bookmarks.models import Bookmark
from documents.models import Document


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
    return redirect(request.POST.get("next") or "document_list")
