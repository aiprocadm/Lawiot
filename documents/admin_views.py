"""Кастомные admin-страницы курирования (diff / очередь / импорт).
Регистрируются через RedactionAdmin.get_urls и оборачиваются admin_site.admin_view."""
from django.contrib import messages
from django.contrib.admin import site as admin_site
from django.shortcuts import get_object_or_404, redirect, render

from documents.diffing import diff_articles
from documents.models import Redaction
from ingestion.models import IngestionJob


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
    if draft.review_status != Redaction.ReviewStatus.DRAFT:
        messages.warning(request, "Редакция уже опубликована.")
    else:
        if draft.ingested_at and draft.redaction_date == draft.ingested_at.date():
            messages.warning(
                request, "Дата «Действует с» совпадает с датой приёма — проверьте её."
            )
        draft.publish()
        messages.success(request, "Опубликовано.")
    return redirect("admin:documents_redaction_change", draft.pk)


def review_queue_view(request):
    drafts = (
        Redaction.objects.filter(review_status=Redaction.ReviewStatus.DRAFT)
        .select_related("document")
        .order_by("-ingested_at")
    )
    failed = IngestionJob.objects.filter(
        status=IngestionJob.Status.FAILED
    ).order_by("-started_at")[:50]
    context = {
        **admin_site.each_context(request),
        "title": "Очередь ревью",
        "drafts": drafts,
        "failed_jobs": failed,
        "draft_count": drafts.count(),
        "failed_count": IngestionJob.objects.filter(
            status=IngestionJob.Status.FAILED
        ).count(),
    }
    return render(request, "admin/documents/redaction/review_queue.html", context)
