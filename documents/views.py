from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from documents.models import Document, Link, Redaction

PAGE_SIZE = 20


@login_required
def document_list(request):
    current = Redaction.objects.filter(
        document=OuterRef("pk"),
        is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    documents = Document.objects.filter(Exists(current)).order_by("title")
    page_obj = Paginator(documents, PAGE_SIZE).get_page(request.GET.get("page"))

    template = (
        "documents/_list_items.html"
        if request.headers.get("HX-Request")
        else "documents/document_list.html"
    )
    return render(request, template, {"page_obj": page_obj})


@login_required
def document_detail(request, slug):
    document = get_object_or_404(Document, slug=slug)
    redaction = document.redactions.filter(
        is_current=True, review_status=Redaction.ReviewStatus.PUBLISHED
    ).first()
    if redaction is None:
        raise Http404("Нет опубликованной редакции")

    articles = list(redaction.articles.all())
    children_map = defaultdict(list)
    for a in articles:
        children_map[a.parent_id].append(a)
    for a in articles:
        a.child_nodes = children_map[a.id]
    article_tree = children_map[None]
    visible_statuses = [Link.Status.CONFIRMED]
    if request.user.is_staff:
        visible_statuses.append(Link.Status.SUGGESTED)
    outgoing = document.outgoing_links.filter(
        status__in=visible_statuses
    ).select_related("to_document")
    amendments = [
        link for link in outgoing
        if link.link_type in (Link.LinkType.AMENDS, Link.LinkType.AMENDED_BY)
    ]
    references = [
        link for link in outgoing if link.link_type == Link.LinkType.REFERENCES
    ]
    incoming = document.incoming_links.filter(
        status__in=visible_statuses
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
            "article_tree": article_tree,
            "amendments": amendments,
            "references": references,
            "incoming": incoming,
            "is_curator": request.user.is_staff,
            "published_redactions": published_redactions,
        },
    )
