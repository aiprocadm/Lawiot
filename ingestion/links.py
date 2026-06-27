import re
from dataclasses import dataclass

from documents.models import Document, Link

# Номер НПА вида «197-ФЗ», «400-ФЗ», «1-ФКЗ» — самый надёжный якорь цитаты.
CITATION_RE = re.compile(r"\b(\d{1,4}-(?:ФКЗ|ФЗ))\b")
CONTEXT_WINDOW = 60

# Реестр кодексов РФ: (regex по склонениям имени, каноническое имя, фильтр по Document.title).
# Стем-паттерны терпимы к падежам: «Трудов-ой/-ого/-ым кодекс-∅/-а/-ом». Резолв
# «только-в-корпусе» (см. extract_links_for_redaction) делает лишние записи безвредными —
# резолвятся лишь те кодексы, что реально в корпусе. КоАП — особый («кодекс» спереди).
CODEX_PATTERNS = [
    (re.compile(r"\bтрудов\w+\s+кодекс\w*", re.I), "Трудовой кодекс",
     {"title__istartswith": "Трудовой кодекс"}),
    (re.compile(r"\bгражданск\w+\s+кодекс\w*", re.I), "Гражданский кодекс",
     {"title__istartswith": "Гражданский кодекс"}),
    (re.compile(r"\bналогов\w+\s+кодекс\w*", re.I), "Налоговый кодекс",
     {"title__istartswith": "Налоговый кодекс"}),
    (re.compile(r"\bуголовн\w+\s+кодекс\w*", re.I), "Уголовный кодекс",
     {"title__istartswith": "Уголовный кодекс"}),
    (re.compile(r"\bземельн\w+\s+кодекс\w*", re.I), "Земельный кодекс",
     {"title__istartswith": "Земельный кодекс"}),
    (re.compile(r"\bжилищн\w+\s+кодекс\w*", re.I), "Жилищный кодекс",
     {"title__istartswith": "Жилищный кодекс"}),
    (re.compile(r"\bсемейн\w+\s+кодекс\w*", re.I), "Семейный кодекс",
     {"title__istartswith": "Семейный кодекс"}),
    (re.compile(r"\bбюджетн\w+\s+кодекс\w*", re.I), "Бюджетный кодекс",
     {"title__istartswith": "Бюджетный кодекс"}),
    (re.compile(
        r"\bкодекс\w*\s+(?:российской\s+федерации\s+)?об\s+административных\s+правонарушениях",
        re.I,
    ), "Кодекс об административных правонарушениях",
     {"title__icontains": "об административных правонарушениях"}),
]

# Каноническое имя → фильтр резолвинга по Document.title (единый источник — CODEX_PATTERNS).
_CODEX_TITLE_FILTERS = {name: title_filter for _, name, title_filter in CODEX_PATTERNS}


@dataclass(frozen=True)
class NamedCitation:
    name: str  # каноническое имя кодекса, напр. «Трудовой кодекс»
    context: str  # очищенный фрагмент текста вокруг первого вхождения


def find_named_citations(text):
    """Найти упоминания кодексов по имени (во всех падежах). Чистая функция (без БД/сети).
    По одной NamedCitation на уникальное каноническое имя — с контекстом первого вхождения."""
    text = text or ""
    found: list[NamedCitation] = []
    for regex, name, _ in CODEX_PATTERNS:
        match = regex.search(text)
        if match is None:
            continue
        start = max(0, match.start() - CONTEXT_WINDOW)
        end = min(len(text), match.end() + CONTEXT_WINDOW)
        snippet = " ".join(text[start:end].split())
        found.append(NamedCitation(name=name, context=snippet))
    return found


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


def _create_reference_link(document, target, context):
    """Создать авто-предложенную (suggested) связь-ссылку document → target."""
    Link.objects.create(
        from_document=document,
        to_document=target,
        link_type=Link.LinkType.REFERENCES,
        origin=Link.Origin.AUTO,
        status=Link.Status.SUGGESTED,
        context=context,
    )


def extract_links_for_redaction(redaction):
    """Извлечь цитаты из текста редакции и создать предложенные (suggested) авто-связи.
    Идемпотентно: прежние auto+suggested связи документа пересоздаются; подтверждённые
    куратором связи не трогаются и не дублируются. Возвращает число созданных связей."""
    document = redaction.document
    parts = [redaction.full_text or ""]
    parts.extend(article.text for article in redaction.articles.all())
    text = "\n".join(parts)

    citations = find_citations(text)
    named_citations = find_named_citations(text)

    # сбросить прежние авто-предложения этого документа (подтверждённые не трогаем)
    Link.objects.filter(
        from_document=document,
        origin=Link.Origin.AUTO,
        status=Link.Status.SUGGESTED,
    ).delete()

    # Предзагрузка целей одним запросом вместо .first() на каждую цитату (N+1).
    # Порядок по Document.Meta.ordering (title) сохраняет семантику .first():
    # для совпадающих номеров берём первый по title.
    numbers = {c.number for c in citations}
    targets_by_number = {}
    if numbers:
        for doc in Document.objects.filter(official_number__in=numbers).exclude(pk=document.pk):
            targets_by_number.setdefault(doc.official_number, doc)

    # Цели именных цитат: по одному запросу на различимый кодекс (их единицы),
    # а не на каждую цитату.
    targets_by_name = {}
    for name in {c.name for c in named_citations}:
        targets_by_name[name] = (
            Document.objects.filter(**_CODEX_TITLE_FILTERS[name])
            .exclude(pk=document.pk)
            .first()
        )

    # Снимок выживших связей для дедупа в памяти (вместо .exists() на цитату).
    # Множества обновляются по ходу — так дедуп ловит и связи, созданные в этом
    # же прогоне (например, номерная + именная цитата одной цели → одна связь).
    surviving = Link.objects.filter(from_document=document)
    linked_target_ids = set(
        surviving.filter(link_type=Link.LinkType.REFERENCES, to_document__isnull=False)
        .values_list("to_document_id", flat=True)
    )
    linked_raw = set(
        surviving.exclude(raw_citation="").values_list("raw_citation", flat=True)
    )

    created = 0
    for citation in citations:
        target = targets_by_number.get(citation.number)
        if target is not None:
            if target.pk in linked_target_ids:
                continue
            _create_reference_link(document, target, citation.context)
            linked_target_ids.add(target.pk)
        else:
            if citation.number == document.official_number:
                continue  # самоцитата без внешней цели
            # raw_citation = сам номер (точный дедуп; «25-ФЗ» не путать со «125-ФЗ»),
            # а человекочитаемый фрагмент кладём в context (спека §5).
            if citation.number in linked_raw:
                continue
            Link.objects.create(
                from_document=document,
                raw_citation=citation.number,
                link_type=Link.LinkType.REFERENCES,
                origin=Link.Origin.AUTO,
                status=Link.Status.SUGGESTED,
                context=citation.context,
            )
            linked_raw.add(citation.number)
        created += 1

    # Именные цитаты кодексов: резолвим по Document.title, только если кодекс в корпусе.
    for citation in named_citations:
        target = targets_by_name.get(citation.name)
        if target is None:
            continue  # кодекса нет в корпусе → связь не создаём
        if target.pk in linked_target_ids:
            continue  # дедуп: номерная цитата уже создала связь к этой цели
        _create_reference_link(document, target, citation.context)
        linked_target_ids.add(target.pk)
        created += 1
    return created
