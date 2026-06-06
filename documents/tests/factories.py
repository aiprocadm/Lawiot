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
