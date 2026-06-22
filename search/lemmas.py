"""Морфологическое расширение поискового запроса (pymorphy3).

Snowball-стеммер конфига ``russian`` не знает супплетивов и беглых
гласных: «ребёнок» (стем ``ребенок``) не находит «ребёнка» (стем
``ребенк``), «мать» (стем ``мат``) — «матери» (стем ``матер``), поэтому
такие запросы дают ноль результатов. Вместо переиндексации расширяем
сам запрос: для каждого слова собираем словоформы его лексем pymorphy3
и склеиваем в raw-tsquery вида ``(ф1|ф2|…) & (ф1|…)`` — она OR-ится с
базовым websearch-запросом в ``search_documents`` и добавляет recall,
не меняя семантику операторов websearch.
"""

import re
from functools import lru_cache

# Мини-словарь синонимов предметной области. Ключ — лемма (нормальная
# форма pymorphy3, после ё→е) или само слово запроса; значение — фразы,
# добавляемые в группу слова как AND-подгруппы (их слова достеммит сам
# Postgres). Включаем синоним, только если стем разговорного слова не
# совпадает со стемом юридической формулировки (иначе snowball уже
# находит её) — каждая фраза проверена на присутствие в тексте ТК РФ
# (см. note 2026-06-11-pymorphy-spike: синонимы — класс промахов, который
# морфология не закрывает в принципе).
SYNONYMS: dict[str, tuple[str, ...]] = {
    "зарплата": ("заработная плата",),
    "декрет": ("отпуск по беременности и родам",),
    "декретный": ("отпуск по беременности и родам",),
    "мрот": ("минимальный размер оплаты труда",),
    "увольнение": ("уволить",),
    "уволить": ("увольнение",),
    "больничный": ("временной нетрудоспособности",),
    "отгул": ("день отдыха",),
    "удаленка": ("дистанционная работа",),
    "удаленный": ("дистанционная работа",),
    "вахта": ("вахтовый метод",),
    "контракт": ("трудовой договор",),
    "испытательный": ("испытание",),
    "переработка": ("сверхурочная работа",),
    "подработка": ("совместительство",),
    "отпускной": ("оплата отпуска",),
    "полставка": ("неполное рабочее время",),
    "профзаболевание": ("профессионального заболевания",),
}

# Токен, безопасный для raw-tsquery: кириллица (после ё→е), дефисы
# допустимы только внутри слова — краевой «-» прочитался бы как
# NOT-оператор синтаксиса to_tsquery.
_CYRILLIC_TOKEN = re.compile(r"^[а-я]+(?:-[а-я]+)*$")
_NUMERIC_TOKEN = re.compile(r"^[0-9]+$")
_EDGE_PUNCT = re.compile(r"^\W+|\W+$")

# Операторы websearch_to_tsquery: фраза в кавычках, минус-исключение,
# OR (регистронезависимо — Postgres понимает и «or»). При их наличии
# расширение не применяется, чтобы OR-ветка не обошла исключения.
_WEBSEARCH_OPERATORS = re.compile(r'"|(?:^|\s)-\S|\b[oO][rR]\b')

# Порог по score разборов: именной разбор «простой» имеет score 0.065
# и не входит в топ-3 — поэтому фильтруем по score среди топ-6.
_MIN_SCORE = 0.03
_MAX_PARSES = 6


@lru_cache(maxsize=1)
def _morph():
    # Инициализация ~0.7 с — строго один раз на процесс, не на запрос.
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


def _normalize(word: str) -> str:
    return word.lower().replace("ё", "е")


def has_websearch_operators(query_text: str) -> bool:
    return bool(_WEBSEARCH_OPERATORS.search(query_text))


def _parses(word: str):
    return [p for p in _morph().parse(word)[:_MAX_PARSES] if p.score >= _MIN_SCORE]


def expand_word(word: str) -> list[str]:
    """Словоформы лексем слова (lowercase, ё→е), включая само слово.

    Формы, не проходящие фильтр безопасного токена (латиница, цифры,
    краевые дефисы), отбрасываются; слово без единого разбора с
    кириллическими формами остаётся как есть.
    """
    word = _normalize(word)
    forms = {word} if _CYRILLIC_TOKEN.match(word) else set()
    for parse in _parses(word):
        for item in parse.lexeme:
            form = _normalize(item.word)
            if _CYRILLIC_TOKEN.match(form):
                forms.add(form)
    return sorted(forms)


def _synonym_phrases(word: str) -> list[str]:
    keys = {word}
    keys.update(_normalize(p.normal_form) for p in _parses(word))
    phrases: list[str] = []
    for key in sorted(keys):
        phrases.extend(SYNONYMS.get(key, ()))
    return phrases


def _word_group(word: str) -> str:
    """OR-группа raw-tsquery для одного (нормализованного) слова запроса."""
    alternatives = expand_word(word) or [word]
    for phrase in _synonym_phrases(word):
        words = [_normalize(w) for w in phrase.split() if _CYRILLIC_TOKEN.match(_normalize(w))]
        if words:
            alternatives.append("(" + " & ".join(words) + ")")
    return "(" + " | ".join(alternatives) + ")"


def build_expanded_tsquery(query_text: str) -> str | None:
    """Raw-tsquery с расширением словоформ или None, если оно неприменимо.

    None возвращается, когда в запросе есть операторы websearch (guard)
    или небезопасный для raw-синтаксиса токен — тогда вызывающий код
    оставляет только базовый websearch-запрос.
    """
    if has_websearch_operators(query_text):
        return None

    groups: list[str] = []
    expanded_any = False
    for raw_token in query_text.split():
        token = _normalize(_EDGE_PUNCT.sub("", raw_token))
        if not token:
            continue
        if _CYRILLIC_TOKEN.match(token):
            groups.append(_word_group(token))
            expanded_any = True
        elif _NUMERIC_TOKEN.match(token):
            groups.append(token)
        else:
            return None
    if not expanded_any:
        return None
    return " & ".join(groups)
