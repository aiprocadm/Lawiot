import re
from dataclasses import dataclass

from documents.models import Document, Link

# Номер НПА вида «197-ФЗ», «400-ФЗ», «1-ФКЗ» — самый надёжный якорь цитаты.
CITATION_RE = re.compile(r"\b(\d{1,4}-(?:ФКЗ|ФЗ))\b")
CONTEXT_WINDOW = 60


@dataclass(frozen=True)
class Citation:
    number: str  # «197-ФЗ»
    context: str  # очищенный фрагмент текста вокруг цитаты


def find_citations(text):
    """Найти уникальные цитаты-номера НПА. Чистая функция (без БД/сети).
    По одной Citation на уникальный номер — с контекстом первого вхождения."""
    text = text or ""
    seen: dict[str, Citation] = {}
    for match in CITATION_RE.finditer(text):
        number = match.group(1)
        if number in seen:
            continue
        start = max(0, match.start() - CONTEXT_WINDOW)
        end = min(len(text), match.end() + CONTEXT_WINDOW)
        snippet = " ".join(text[start:end].split())
        seen[number] = Citation(number=number, context=snippet)
    return list(seen.values())


def extract_links_for_redaction(redaction):
    """Извлечь цитаты из текста редакции и создать предложенные (suggested) авто-связи.
    Идемпотентно: прежние auto+suggested связи документа пересоздаются; подтверждённые
    куратором связи не трогаются и не дублируются. Возвращает число созданных связей."""
    document = redaction.document
    parts = [redaction.full_text or ""]
    parts.extend(article.text for article in redaction.articles.all())
    text = "\n".join(parts)

    citations = find_citations(text)

    # сбросить прежние авто-предложения этого документа (подтверждённые не трогаем)
    Link.objects.filter(
        from_document=document,
        origin=Link.Origin.AUTO,
        status=Link.Status.SUGGESTED,
    ).delete()

    created = 0
    for citation in citations:
        target = (
            Document.objects.filter(official_number=citation.number)
            .exclude(pk=document.pk)  # не ссылаемся на самих себя
            .first()
        )
        if target is not None:
            already = Link.objects.filter(
                from_document=document,
                to_document=target,
                link_type=Link.LinkType.REFERENCES,
            ).exists()
            if already:
                continue
            Link.objects.create(
                from_document=document,
                to_document=target,
                link_type=Link.LinkType.REFERENCES,
                origin=Link.Origin.AUTO,
                status=Link.Status.SUGGESTED,
                context=citation.context,
            )
        else:
            if citation.number == document.official_number:
                continue  # самоцитата без внешней цели
            # raw_citation = сам номер (точный дедуп; «25-ФЗ» не путать со «125-ФЗ»),
            # а человекочитаемый фрагмент кладём в context (спека §5).
            already = Link.objects.filter(
                from_document=document,
                raw_citation=citation.number,
            ).exists()
            if already:
                continue
            Link.objects.create(
                from_document=document,
                raw_citation=citation.number,
                link_type=Link.LinkType.REFERENCES,
                origin=Link.Origin.AUTO,
                status=Link.Status.SUGGESTED,
                context=citation.context,
            )
        created += 1
    return created
