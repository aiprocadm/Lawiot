from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from documents.models import Document, Link, Redaction


@login_required
def document_list(request):
    current = Redaction.objects.filter(
        document=OuterRef("pk"),
        is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    documents = Document.objects.filter(Exists(current))
    return render(
        request, "documents/document_list.html", {"documents": documents}
    )


@login_required
def document_detail(request, slug):
    document = get_object_or_404(Document, slug=slug)
    redaction = document.redactions.filter(
        is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
    ).first()
    if redaction is None:
        raise Http404("Нет опубликованной редакции")

    articles = redaction.articles.select_related("parent").all()
    outgoing = document.outgoing_links.filter(
        status=Link.Status.CONFIRMED
    ).select_related("to_document")
    incoming = document.incoming_links.filter(
        status=Link.Status.CONFIRMED
    ).select_related("from_document")
    published_redactions = document.redactions.filter(
        review_status=Redaction.ReviewStatus.PUBLISHED
    )

    return render(
        request,
        "documents/document_detail.html",
        {
            "document": document,
            "redaction": redaction,
            "articles": articles,
            "outgoing": outgoing,
            "incoming": incoming,
            "published_redactions": published_redactions,
        },
    )
