"""Внутри-документные гиперссылки: «статья N» / «ст. N» в тексте статьи →
ссылка на #st-N, но ТОЛЬКО если такая статья есть в этом же акте (anchors).

Высокая точность важнее полноты: линкуем лишь явные ссылки с префиксом
«стать…/ст.» на существующий в акте якорь. XSS-безопасно: экранируем ДО линковки.
"""

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.text import slugify

# «статьёй 72», «статья 127», «статей 81», «ст. 312.1», «ст 5».
_REF_RE = re.compile(r"(\bстать[а-яё]+|\bст\.?)(\s+)(\d+(?:\.\d+)*)", re.IGNORECASE)
# Номер НПА в тексте: «197-ФЗ», «10-ФЗ», «1-ФКЗ» (для межактовых ссылок).
_FZ_RE = re.compile(r"\b\d{1,4}-(?:ФКЗ|ФЗ)\b")


def _anchor_for(num):
    return f"st-{slugify(num.replace('.', '-'))}"


def _link_refs(escaped_text, anchors):
    def repl(m):
        anchor = _anchor_for(m.group(3))
        if anchor in anchors:
            return f'<a href="#{anchor}">{m.group(0)}</a>'
        return m.group(0)

    return _REF_RE.sub(repl, escaped_text)


def _link_external(escaped_text, numbers, codices):
    """Линкует «N-ФЗ» и кодексы по имени на страницы актов корпуса.

    numbers: {«197-ФЗ»: url}; codices: [(скомпилированный regex, url)]. Резолвятся
    только присутствующие в корпусе акты — нерезолвленное остаётся текстом.
    """

    def fz_repl(m):
        url = numbers.get(m.group(0))
        return f'<a href="{url}">{m.group(0)}</a>' if url else m.group(0)

    out = _FZ_RE.sub(fz_repl, escaped_text)
    for regex, url in codices:
        out = regex.sub(lambda m, u=url: f'<a href="{u}">{m.group(0)}</a>', out)
    return out


def linkify_internal_refs(text, links=None):
    """Экранированный текст с абзацами (как Django linebreaks) + гиперссылки.

    links — dict с ключами anchors (якоря статей этого акта, #49), numbers
    («N-ФЗ»→url) и codices ([(regex, url)]) для межактовых ссылок. Для обратной
    совместимости принимает и просто набор якорей. Возвращает safe HTML.
    """
    if isinstance(links, dict):
        anchors = set(links.get("anchors") or ())
        numbers = links.get("numbers") or {}
        codices = links.get("codices") or ()
    else:
        anchors, numbers, codices = set(links or ()), {}, ()

    paragraphs = re.split(r"\n{2,}", (text or "").strip())
    blocks = []
    for para in paragraphs:
        if not para:
            continue
        html = _link_refs(escape(para), anchors)  # внутренние «ст. N» (#49)
        html = _link_external(html, numbers, codices)  # межактовые «N-ФЗ» / кодексы
        blocks.append(f"<p>{html.replace(chr(10), '<br>')}</p>")
    return mark_safe("\n".join(blocks))


def build_corpus_links(exclude_slug=None):
    """Резолвер межактовых ссылок из корпуса: номера ФЗ и кодексы → URL акта.

    Только акты с текущей опубликованной редакцией; текущий акт исключается
    (self-link не нужен). lazy-import CODEX_PATTERNS — documents→ingestion лишь
    в рантайме, без циклической загрузки модулей.
    """
    from django.urls import reverse

    from documents.models import Document, Redaction
    from ingestion.links import CODEX_PATTERNS

    docs = list(
        Document.objects.filter(
            redactions__is_current=True,
            redactions__review_status=Redaction.ReviewStatus.PUBLISHED,
        )
        .exclude(slug=exclude_slug or "")
        .distinct()
    )
    numbers = {}
    for d in docs:
        if d.official_number:
            numbers.setdefault(d.official_number, reverse("document_detail", args=[d.slug]))

    codices = []
    for regex, _name, title_filter in CODEX_PATTERNS:
        key, val = next(iter(title_filter.items()))
        val = val.lower()
        for d in docs:
            title = d.title.lower()
            hit = title.startswith(val) if key.endswith("istartswith") else val in title
            if hit:
                codices.append((regex, reverse("document_detail", args=[d.slug])))
                break

    return {"numbers": numbers, "codices": codices}
