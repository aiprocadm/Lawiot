from dataclasses import dataclass

import httpx

from documents.models import Document
from ingestion.fetching import DEFAULT_TIMEOUT, MAX_RETRIES
from ingestion.models import IngestionJob
from ingestion.services import IngestionTarget, ingest_target


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


@dataclass
class SweepSummary:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0

    def __str__(self):
        return (
            f"всего={self.total} успех={self.success} "
            f"пропущено={self.skipped} ошибок={self.failed}"
        )


_STATUS_FIELD = {
    IngestionJob.Status.SUCCESS: "success",
    IngestionJob.Status.SKIPPED: "skipped",
    IngestionJob.Status.FAILED: "failed",
}


def _new_client():
    # Один клиент на весь обход: переиспользование соединений (вежливость к источнику).
    # Параметры совпадают с ingestion.fetching.fetch; User-Agent добавляет сам fetch.
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        transport=httpx.HTTPTransport(retries=MAX_RETRIES),
        follow_redirects=True,
    )


def sweep_targets(*, client=None) -> SweepSummary:
    """Обойти все цели авто-приёма, для каждой вызвать ingest_target.

    Изоляция двойная: ingest_target сам ловит сетевые/парсинговые ошибки в FAILED-job,
    а внешний try/except ловит сбои уровня БД, чтобы один проблемный документ не оборвал
    весь обход. Возвращает агрегированную сводку.
    """
    summary = SweepSummary()
    owns_client = client is None
    client = client or _new_client()
    try:
        for target in iter_targets():
            summary.total += 1
            try:
                job = ingest_target(target, client=client)
                field = _STATUS_FIELD.get(job.status, "failed")
            except Exception:  # намеренная сетка: один сбойный документ не должен оборвать обход
                field = "failed"
            setattr(summary, field, getattr(summary, field) + 1)
    finally:
        if owns_client:
            client.close()
    return summary


def run_sweep() -> str:
    """Точка входа для планировщика django-q2 (func='ingestion.scheduling.run_sweep').

    Возвращает строку-сводку — django-q2 сохранит её в результате задачи (виден в admin).
    """
    return str(sweep_targets())
