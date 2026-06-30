"""Подсказка «Вы искали…» (исправление опечаток) на pg_trgm.

Словарь словоформ корпуса (documents.SearchVocab) наполняется командой
build_search_vocab. При нулевом результате поиска suggest_query() ищет
ближайшее по написанию слово только для незнакомых корпусу токенов.
"""

import re

# Нормализация совпадает с поисковой (search.lemmas._normalize): lowercase + ё→е.
_TOKEN_RE = re.compile(r"[а-яёa-z]+")


def tokenize(text: str) -> list[str]:
    """Слова текста: lowercase, ё→е, в порядке появления."""
    return [m.replace("ё", "е") for m in _TOKEN_RE.findall((text or "").lower())]
