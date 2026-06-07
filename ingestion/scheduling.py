from documents.models import Document
from ingestion.services import IngestionTarget


def iter_targets():
    """Цели авто-приёма: документы с флагом auto_ingest и непустым source_url.

    target_key = slug — та же конвенция, что у команды ingest_url, поэтому история
    обнаружения изменений (RawSource по target_key) общая для авто- и ручного приёма.
    """
    qs = Document.objects.filter(auto_ingest=True).exclude(source_url="")
    for document in qs.iterator():
        yield IngestionTarget(
            document=document,
            url=document.source_url,
            target_key=document.slug,
        )
