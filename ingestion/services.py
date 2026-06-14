import hashlib
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from documents.models import Article, Document, Redaction
from ingestion.fetching import fetch
from ingestion.links import extract_links_for_redaction
from ingestion.models import IngestionJob, RawSource
from ingestion.parsing import PARSER_VERSION, html_to_text, parse_document, parse_text

# Минимальная доля статей новой редакции от текущей при авто-публикации.
# Резкое падение = вероятно обрезанный/ошибочный ответ источника — не публикуем.
AUTOPUBLISH_MIN_RATIO = 0.8


class PublishedRedactionExists(Exception):
    """Поднимается, когда приём попытался бы перезаписать опубликованную редакцию."""


class ReparseYieldedNothing(Exception):
    """Переразбор дал 0 статей там, где они были — черновик не затираем."""


@dataclass
class IngestionTarget:
    document: Document
    url: str
    target_key: str


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def text_digest(text: str) -> str:
    """SHA-256 нормализованного текста. Триггер «новая редакция» (стабилен к дребезгу разметки)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_text_hash(content: bytes, content_type: str = "text/html") -> str:
    """SHA-256 нормализованного текста содержимого (стабильный триггер изменения редакции)."""
    return text_digest(html_to_text(content, content_type))


def store_raw_source(target_key, content, content_type="", source_url="", text_hash=None):
    return RawSource.objects.create(
        target_key=target_key,
        content=content,
        content_hash=compute_hash(content),
        text_hash=text_hash if text_hash is not None else compute_text_hash(content, content_type),
        content_type=content_type,
        source_url=source_url,
    )


def text_changed(target_key, text_hash) -> bool:
    """True, если для цели ещё нет сырья или хэш нормализованного текста отличается."""
    latest = RawSource.objects.filter(target_key=target_key).order_by("-fetched_at").first()
    return latest is None or latest.text_hash != text_hash


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
        order_to_article = {}
        for parsed_article in parsed.articles:
            parent = (
                order_to_article.get(parsed_article.parent_order)
                if parsed_article.parent_order is not None
                else None
            )
            obj = Article.objects.create(
                redaction=redaction,
                kind=parsed_article.kind,
                number=parsed_article.number,
                title=parsed_article.title,
                text=parsed_article.text,
                order=parsed_article.order,
                parent=parent,
            )
            order_to_article[parsed_article.order] = obj
    return redaction


def _finish(job, log_lines):
    job.log = "\n".join(log_lines)
    job.finished_at = timezone.now()
    job.save()
    return job


def _article_count(redaction):
    return redaction.articles.filter(kind=Article.Kind.ARTICLE).count()


def _is_safe_to_publish(new_redaction, current_redaction):
    """True, если новую редакцию безопасно авто-публиковать (см. spec §4.3).
    Защита от обрезанного/ошибочного ответа источника: 0 статей и пустой текст,
    либо резкое падение числа статей против текущей опубликованной редакции."""
    new_count = _article_count(new_redaction)
    has_text = bool((new_redaction.full_text or "").strip())
    if new_count == 0 and not has_text:
        return False
    if current_redaction is None:
        return new_count >= 1 or has_text
    current_count = _article_count(current_redaction)
    if current_count == 0:
        return True
    return new_count >= AUTOPUBLISH_MIN_RATIO * current_count


def ingest_target(target, *, client=None):
    """Конвейер по одной цели: скачать → сохранить сырьё → обнаружить изменение →
    разобрать → создать черновик → (если auto_publish и безопасно) опубликовать.
    Сбой изолирован (FAILED-job), сырьё сохраняется (карантин)."""
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
        text = html_to_text(result.content, result.content_type)
        text_hash = text_digest(text)
        if not text_changed(target.target_key, text_hash):
            job.status = IngestionJob.Status.SKIPPED
            log_lines.append("Нормализованный текст не изменился — пропуск.")
            return _finish(job, log_lines)
        raw = store_raw_source(
            target.target_key,
            result.content,
            result.content_type,
            result.source_url,
            text_hash=text_hash,
        )
        job.raw_source = raw
        parsed = parse_text(text)
        n_articles = sum(1 for a in parsed.articles if a.kind == "article")
        log_lines.append(
            f"Разобрано узлов структуры: {len(parsed.articles)} (статей: {n_articles})."
        )
        # текущую опубликованную редакцию фиксируем ДО создания черновика (для гейта)
        current = Redaction.objects.filter(document=target.document, is_current=True).first()
        try:
            redaction = create_draft_from_parsed(
                target.document,
                parsed,
                raw_source=raw,
                redaction_date=parsed.detected_redaction_date,
            )
        except PublishedRedactionExists as exc:
            # Редакция на эту дату уже опубликована — обновлять нечего, это не ошибка.
            job.status = IngestionJob.Status.SKIPPED
            log_lines.append(str(exc))
            return _finish(job, log_lines)
        job.produced_redaction = redaction
        job.status = IngestionJob.Status.SUCCESS
        log_lines.append(f"Создан черновик редакции #{redaction.pk}.")
        try:
            n_links = extract_links_for_redaction(redaction)
            log_lines.append(f"Предложено связей: {n_links}.")
        except Exception as link_exc:  # извлечение связей вторично — не валит приём
            log_lines.append(f"Извлечение связей не удалось: {link_exc}")
        # авто-публикация (§17): только при флаге, извлечённой дате и пройденном гейте
        if target.document.auto_publish:
            if parsed.detected_redaction_date is None:
                log_lines.append("Авто-публикация пропущена: не извлечена дата редакции.")
            elif not _is_safe_to_publish(redaction, current):
                log_lines.append(
                    "Авто-публикация пропущена: гейт безопасности не пройден "
                    "(0 статей или резкое падение против текущей)."
                )
            else:
                redaction.publish()
                log_lines.append(f"Авто-опубликована редакция #{redaction.pk}.")
                try:
                    extract_links_for_redaction(redaction)  # после публикации: самоссылки
                except Exception as link_exc:
                    log_lines.append(f"Переизвлечение связей не удалось: {link_exc}")
    except Exception as exc:  # изоляция: сбой одной цели не валит пакет
        job.status = IngestionJob.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"
        log_lines.append("ОШИБКА — см. поле error.")
    return _finish(job, log_lines)


def import_manual(
    document, *, content, content_type="text/plain", source_url="", redaction_date=None
):
    """Запасной путь: куратор подаёт байты/текст напрямую → черновик редакции + предложенные связи."""
    raw = store_raw_source(f"manual:{document.slug}", content, content_type, source_url)
    parsed = parse_document(content, content_type)
    redaction = create_draft_from_parsed(
        document, parsed, raw_source=raw, redaction_date=redaction_date
    )
    try:
        extract_links_for_redaction(redaction)
    except (
        Exception
    ):  # извлечение связей вторично: черновик сохранён, связи можно переизвлечь командой
        pass
    return redaction


def reparse_redaction(redaction):
    """Переразобрать ЧЕРНОВИК из сохранённого RawSource (без повторного скачивания).
    Защита (#1281): если новый разбор даёт 0 статей, а у черновика статьи есть —
    отменяем, чтобы смена формата источника молча не стёрла данные куратора."""
    raw = redaction.raw_source
    if raw is None:
        raise ValueError("У редакции нет сохранённого RawSource — нечего переразбирать.")
    parsed = parse_document(bytes(raw.content), raw.content_type)
    if not parsed.articles and redaction.articles.exists():
        raise ReparseYieldedNothing(
            "Новый разбор дал 0 статей при наличии прежних — операция отменена."
        )
    return create_draft_from_parsed(
        redaction.document,
        parsed,
        raw_source=raw,
        redaction_date=redaction.redaction_date,
    )
