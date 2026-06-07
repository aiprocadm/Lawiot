"""Кастомные admin-страницы курирования (diff / очередь / импорт).
Регистрируются через RedactionAdmin.get_urls и оборачиваются admin_site.admin_view."""
from django.contrib.admin import site as admin_site
from django.shortcuts import get_object_or_404, redirect, render

from documents.diffing import diff_articles
from documents.models import Redaction


def redaction_diff_view(request, pk):
    draft = get_object_or_404(Redaction, pk=pk)
    current = (
        Redaction.objects.filter(document=draft.document, is_current=True)
        .exclude(pk=draft.pk)
        .first()
    )
    if request.method == "POST":
        return _publish_from_diff(request, draft)  # реализуется в Task 6
    current_articles = list(current.articles.all()) if current else []
    diffs = diff_articles(current_articles, list(draft.articles.all()))
    context = {
        **admin_site.each_context(request),
        "title": f"Diff: {draft}",
        "draft": draft,
        "current": current,
        "diffs": diffs,
        "date_looks_placeholder": bool(
            draft.ingested_at and draft.redaction_date == draft.ingested_at.date()
        ),
    }
    return render(request, "admin/documents/redaction/diff.html", context)


def _publish_from_diff(request, draft):
    return redirect("admin:documents_redaction_change", draft.pk)
