"""Подсказка «Вы искали…» (исправление опечаток) на pg_trgm.

Словарь словоформ корпуса (documents.SearchVocab) наполняется командой
build_search_vocab. При нулевом результате поиска suggest_query() ищет
ближайшее по написанию слово только для незнакомых корпусу токенов.
"""

import logging
import re

from django.contrib.postgres.search import TrigramSimilarity

logger = logging.getLogger("search")

# Дефолтный порог сходства pg_trgm: ниже него кандидат считается несвязанным.
SIMILARITY_THRESHOLD = 0.3

# Нормализация совпадает с поисковой (search.lemmas._normalize): lowercase + ё→е.
_TOKEN_RE = re.compile(r"[а-яёa-z]+")


def tokenize(text: str) -> list[str]:
    """Слова текста: lowercase, ё→е, в порядке появления."""
    return [m.replace("ё", "е") for m in _TOKEN_RE.findall((text or "").lower())]


def suggest_query(query_text: str) -> str | None:
    """Исправленный запрос или None.

    Возвращает строку, только если заменён хотя бы один незнакомый корпусу
    токен на ближайшее по триграммному сходству слово словаря. Известные
    корпусу слова не трогает. Любая ошибка/пустой словарь → None (деградация).
    """
    from documents.models import SearchVocab

    tokens = tokenize(query_text)
    if not tokens:
        return None
    try:
        known = set(
            SearchVocab.objects.filter(word__in=tokens).values_list("word", flat=True)
        )
        replaced = False
        out: list[str] = []
        for token in tokens:
            if token in known:
                out.append(token)
                continue
            nearest = (
                SearchVocab.objects.annotate(sim=TrigramSimilarity("word", token))
                .filter(sim__gte=SIMILARITY_THRESHOLD)
                .order_by("-sim", "-frequency")
                .first()
            )
            if nearest is not None:
                out.append(nearest.word)
                replaced = True
            else:
                out.append(token)
        return " ".join(out) if replaced else None
    except Exception:  # noqa: BLE001 — подсказка не критична: деградируем тихо
        logger.exception("suggest_query failed")
        return None
