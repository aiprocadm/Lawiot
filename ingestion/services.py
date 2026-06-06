import hashlib
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from documents.models import Article, Document, Redaction
from ingestion.fetching import fetch
from ingestion.links import extract_links_for_redaction
from ingestion.models import IngestionJob, RawSource
from ingestion.parsing import PARSER_VERSION, parse_document


class PublishedRedactionExists(Exception):
    """Поднимается, когда приём попытался бы перезаписать опубликованную редакцию."""


@dataclass
class IngestionTarget:
    document: Document
    url: str
    target_key: str


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_raw_source(target_key, content, content_type="", source_url=""):
    return RawSource.objects.create(
        target_key=target_key,
        content=content,
        content_hash=compute_hash(content),
        content_type=content_type,
        source_url=source_url,
    )


def content_changed(target_key, content_hash):
    """True, если для цели ещё нет сырья или хэш отличается от последнего."""
    latest = (
        RawSource.objects.filter(target_key=target_key).order_by("-fetched_at").first()
    )
    return latest is None or latest.content_hash != content_hash


def create_draft_from_parsed(document, parsed, *, raw_source=None, redaction_date=None):
    """Создать/обновить ЧЕРНОВИК редакции из разобранного содержимого.
    Идемпотентно по (document, redaction_date). Опубликованную редакцию НИКОГДА не трогает."""
    redaction_date = redaction_date or timezone.now().date()
    with transaction.atomic():
        # select_for_update: при будущем параллельном приёме (План 3c) блокирует строку,
        # чтобы две задачи не создали черновик одновременно на одну (document, redaction_date).
        existing = (
            Redaction.objects.select_for_update()
            .filter(document=document, redaction_date=redaction_date)
            .first()
        )
        if existing and existing.review_status == Redaction.ReviewStatus.PUBLISHED:
            raise PublishedRedactionExists(
                f"Опубликованная редакция от {redaction_date} не перезаписывается автоматически."
            )
        if existing:
            redaction = existing
            redaction.articles.all().delete()
        else:
            redaction = Redaction(document=document, redaction_date=redaction_date)
        redaction.full_text = parsed.full_text
        redaction.review_status = Redaction.ReviewStatus.DRAFT
        redaction.is_current = False
        redaction.ingested_at = timezone.now()
        redaction.parser_version = PARSER_VERSION
        redaction.raw_source = raw_source
        redaction.save()
        for parsed_article in parsed.articles:
            Article.objects.create(
                redaction=redaction,
                kind=Article.Kind.ARTICLE,
                number=parsed_article.number,
                title=parsed_article.title,
                text=parsed_article.text,
                order=parsed_article.order,
            )
    return redaction


def _finish(job, log_lines):
    job.log = "\n".join(log_lines)
    job.finished_at = timezone.now()
    job.save()
    return job


def ingest_target(target, *, client=None):
    """Конвейер по одной цели: скачать → сохранить сырьё → обнаружить изменение →
    разобрать → создать черновик. Сбой изолирован (FAILED-job), сырьё сохраняется (карантин)."""
    # Пессимистичный старт: пока конвейер не завершился успешно, запись считается FAILED.
    # Так прерванный/упавший процесс не оставляет ложного «success» в аудите.
    job = IngestionJob.objects.create(
        target_key=target.target_key,
        status=IngestionJob.Status.FAILED,
        started_at=timezone.now(),
    )
    log_lines = []
    try:
        result = fetch(target.url, client=client)
        log_lines.append(f"Скачано {len(result.content)} байт с {result.source_url}.")
        content_hash = compute_hash(result.content)
        if not content_changed(target.target_key, content_hash):
            job.status = IngestionJob.Status.SKIPPED
            log_lines.append("Содержимое не изменилось — пропуск.")
            return _finish(job, log_lines)
        raw = store_raw_source(
            target.target_key, result.content, result.content_type, result.source_url
        )
        job.raw_source = raw
        parsed = parse_document(result.content, result.content_type)
        log_lines.append(f"Разобрано статей: {len(parsed.articles)}.")
        redaction = create_draft_from_parsed(target.document, parsed, raw_source=raw)
        job.produced_redaction = redaction
        job.status = IngestionJob.Status.SUCCESS
        log_lines.append(f"Создан черновик редакции #{redaction.pk}.")
        try:
            n_links = extract_links_for_redaction(redaction)
            log_lines.append(f"Предложено связей: {n_links}.")
        except Exception as link_exc:  # извлечение связей вторично — не валит приём
            log_lines.append(f"Извлечение связей не удалось: {link_exc}")
    except Exception as exc:  # изоляция: сбой одной цели не валит пакет
        job.status = IngestionJob.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"
        log_lines.append("ОШИБКА — см. поле error.")
    return _finish(job, log_lines)


def import_manual(document, *, content, content_type="text/plain", source_url="", redaction_date=None):
    """Запасной путь: куратор подаёт байты/текст напрямую → черновик редакции + предложенные связи."""
    raw = store_raw_source(f"manual:{document.slug}", content, content_type, source_url)
    parsed = parse_document(content, content_type)
    redaction = create_draft_from_parsed(
        document, parsed, raw_source=raw, redaction_date=redaction_date
    )
    try:
        extract_links_for_redaction(redaction)
    except Exception:  # извлечение связей вторично: черновик сохранён, связи можно переизвлечь командой
        pass
    return redaction
