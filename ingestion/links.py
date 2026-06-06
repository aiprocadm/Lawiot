import re
from dataclasses import dataclass

# Номер НПА вида «197-ФЗ», «400-ФЗ», «1-ФКЗ» — самый надёжный якорь цитаты.
CITATION_RE = re.compile(r"\b(\d{1,4}-(?:ФКЗ|ФЗ))\b")
CONTEXT_WINDOW = 60


@dataclass(frozen=True)
class Citation:
    number: str   # «197-ФЗ»
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
