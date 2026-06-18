from dataclasses import dataclass
from datetime import date

import httpx
from django.utils.text import slugify

from documents.models import PendingAct
from ingestion.publication import FEDERAL_MINTRUD_ID, PublicationDoc, iter_documents

# Органы, которые обходим по умолчанию (стартуем с федерального Минтруда).
DISCOVERY_AUTHORITIES = [FEDERAL_MINTRUD_ID]


@dataclass
class DiscoverySummary:
    total: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0

    def __str__(self):
        return (
            f"всего={self.total} создано={self.created} "
            f"пропущено={self.skipped} ошибок={self.failed}"
        )


def _slug_for(doc: PublicationDoc) -> str:
    base = slugify(f"{doc.doc_type}-{doc.number}-{doc.eo_number}")
    return base or f"act-{doc.eo_number}"


def _upsert(doc: PublicationDoc) -> str:
    """Создать/пропустить PendingAct по eo_number. Возвращает 'created'|'skipped'."""
    existing = PendingAct.objects.filter(eo_number=doc.eo_number).first()
    if existing is not None:
        return "skipped"
    pending = PendingAct(
        slug=_slug_for(doc),
        title=doc.name or doc.complex_name,
        official_number=doc.number,
        doc_type=doc.doc_type,  # "order"/"decree"/"other" — значения Document.DocType
        eo_number=doc.eo_number,
        publication_url=doc.pdf_url,
        document_date=doc.document_date,
        source=PendingAct.Source.AUTO,
    )
    # уже в корпусе — не плодим напоминание. NB: один Document-запрос на каждый
    # новый акт; при росте корпуса заменить на предзагрузку set (official_number,
    # doc_type) в discover() (преждевременно сейчас — watchlist мал).
    if pending.is_resolved:
        return "skipped"
    pending.save()
    return "created"


def discover(
    authority_ids: list[str] | None = None,
    *,
    client: httpx.Client | None = None,
    since_date: date | None = None,
    max_pages: int | None = None,
) -> DiscoverySummary:
    """Обойти органы, завести PendingAct для новых актов. Идемпотентно по eo_number.
    Изоляция двойная (как в scheduling.sweep_targets): внутренний try/except — сбой
    одного документа (напр. гонка IntegrityError) не валит остальные акты органа;
    внешний — сбой обхода/сети органа не валит остальные органы."""
    summary = DiscoverySummary()
    authority_ids = authority_ids or DISCOVERY_AUTHORITIES
    for authority_id in authority_ids:
        try:
            for doc in iter_documents(
                authority_id, client=client, since_date=since_date, max_pages=max_pages
            ):
                summary.total += 1
                try:
                    result = _upsert(doc)
                except Exception:  # один сбойный документ не должен оборвать орган
                    summary.failed += 1
                    continue
                setattr(summary, result, getattr(summary, result) + 1)
        except Exception:  # сбой обхода/сети органа не обрывает остальные органы
            summary.failed += 1
    return summary


def run_discovery() -> str:
    """Точка входа django-q2 (func='ingestion.discovery.run_discovery')."""
    return str(discover())
