from documents.models import Document


def make_document(**kwargs):
    defaults = {
        "doc_type": Document.DocType.CODE,
        "title": "Трудовой кодекс Российской Федерации",
        "official_number": "197-ФЗ",
        "issuing_body": "Федеральное Собрание РФ",
        "status": Document.Status.IN_FORCE,
        "slug": "tk-rf",
    }
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


from datetime import date

from documents.models import Redaction


def make_redaction(document=None, **kwargs):
    if document is None:
        document = make_document()
    defaults = {
        "document": document,
        "redaction_date": date(2024, 1, 1),
        "full_text": "Текст редакции.",
        "review_status": Redaction.ReviewStatus.DRAFT,
        "is_current": False,
    }
    defaults.update(kwargs)
    return Redaction.objects.create(**defaults)


from documents.models import Article


def make_article(redaction=None, **kwargs):
    if redaction is None:
        redaction = make_redaction()
    defaults = {
        "redaction": redaction,
        "kind": Article.Kind.ARTICLE,
        "number": "81",
        "title": "Расторжение трудового договора",
        "text": "Трудовой договор может быть расторгнут...",
        "order": 1,
    }
    defaults.update(kwargs)
    return Article.objects.create(**defaults)
