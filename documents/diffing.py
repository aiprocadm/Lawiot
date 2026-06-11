"""Чистая логика текстового diff «черновик ↔ текущая» по статьям.
Без обращения к БД — на вход последовательности объектов с .number и .text."""

import difflib
from dataclasses import dataclass, field


@dataclass
class ArticleDiff:
    number: str
    status: str  # "added" | "removed" | "changed" | "same"
    lines: list = field(
        default_factory=list
    )  # list[tuple[str, str]]: (tag, text), tag ∈ {"+","-"," "}


def _line_diff(old_text, new_text):
    old = (old_text or "").splitlines()
    new = (new_text or "").splitlines()
    out = []
    for line in difflib.ndiff(old, new):
        tag = line[:1]
        if tag in ("+", "-", " "):
            out.append((tag, line[2:]))
    return out


def diff_articles(current_articles, draft_articles):
    """Выравнивание по `number`. Порядок результата — статьи черновика, затем удалённые."""
    current_by_num = {a.number: a for a in current_articles}
    draft_nums = {a.number for a in draft_articles}
    result = []
    for a in draft_articles:
        cur = current_by_num.get(a.number)
        if cur is None:
            result.append(ArticleDiff(a.number, "added", _line_diff("", a.text)))
        elif (cur.text or "") == (a.text or ""):
            result.append(ArticleDiff(a.number, "same"))
        else:
            result.append(ArticleDiff(a.number, "changed", _line_diff(cur.text, a.text)))
    for a in current_articles:
        if a.number not in draft_nums:
            result.append(ArticleDiff(a.number, "removed", _line_diff(a.text, "")))
    return result
