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


def _anchor_for(num):
    return f"st-{slugify(num.replace('.', '-'))}"


def _link_refs(escaped_text, anchors):
    def repl(m):
        anchor = _anchor_for(m.group(3))
        if anchor in anchors:
            return f'<a href="#{anchor}">{m.group(0)}</a>'
        return m.group(0)

    return _REF_RE.sub(repl, escaped_text)


def linkify_internal_refs(text, anchors):
    """Экранированный текст с абзацами (как Django linebreaks) + гиперссылки на
    статьи этого же акта. Возвращает safe HTML."""
    anchors = set(anchors or ())
    paragraphs = re.split(r"\n{2,}", (text or "").strip())
    blocks = []
    for para in paragraphs:
        if not para:
            continue
        html = _link_refs(escape(para), anchors).replace("\n", "<br>")
        blocks.append(f"<p>{html}</p>")
    return mark_safe("\n".join(blocks))
