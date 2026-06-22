"""Пост-проверка цитат: какие «Статья N» в ответе модели НЕ входят в набор
переданных статей. Это структурный страховочный слой поверх промпта (промпт —
не гарантия): юр-продукт не должен молча цитировать нормы вне корпуса.

Высокая точность важнее полноты: ловим только явный формат «Статья N», чтобы
не давать ложных срабатываний на свободном тексте.
"""

import re

# «Статья 127», «статьёй 81», «ст. 264» (+ дробные номера 312.1).
_CITE_RE = re.compile(r"(?:стать[а-яё]*|ст\.?)\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
_NUM_RE = re.compile(r"(\d+(?:\.\d+)*)")


def cited_article_numbers(text):
    """Номера статей, упомянутых в тексте в формате «Статья N» / «ст. N»."""
    return set(_CITE_RE.findall(text or ""))


def allowed_article_numbers(articles):
    """Номера статей из переданного набора (по меткам «Статья N»)."""
    allowed = set()
    for a in articles:
        label = a.article_label or ""
        if label.lower().startswith("стат"):
            m = _NUM_RE.search(label)
            if m:
                allowed.add(m.group(1))
    return allowed


def unverified_citations(text, articles):
    """Отсортированные номера статей из ответа, которых НЕТ в наборе-основании."""
    return sorted(cited_article_numbers(text) - allowed_article_numbers(articles))
