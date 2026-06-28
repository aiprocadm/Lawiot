import re
from dataclasses import dataclass, field
from datetime import date

from bs4 import BeautifulSoup

PARSER_VERSION = "1.0"

# Заголовок статьи: «Статья 81. Расторжение…» / «Статья 312.1. …» /
# «Статья 123.20-1. …» — суффикс «-N» обязателен: ГК (личный фонд, 123.20-1..8) и
# ТК (заёмный труд, 341.1-1..) реально так нумеруют. Без него статьи схлопывались
# в один номер → дубли якорей → 500 на странице разъяснения.
ARTICLE_RE = re.compile(r"^Статья\s+(\d+(?:\.\d+)?(?:-\d+)?)\.?\s*(.*)$")
# Раздел римской цифрой: «Раздел I. Общие положения»
SECTION_RE = re.compile(r"^Раздел\s+([IVXLCDM]+)\.?\s*(.*)$", re.IGNORECASE)
# Глава арабской цифрой («Глава 1. Основные начала» / «Глава 12.1. …») ИЛИ
# римской («Глава I. Общие положения» — так размечены, напр., 10-ФЗ о профсоюзах).
CHAPTER_RE = re.compile(r"^Глава\s+(\d+(?:\.\d+)?|[IVXLCDM]+)\.?\s*(.*)$", re.IGNORECASE)

# Подзаконные акты разбираются по doc_type (см. parse_text).
# ВАЖНО: строки должны совпадать со значениями Document.DocType (DECREE/ORDER).
# Держим литералы здесь, а не импорт модели, чтобы парсер не зависел от Django.
POINT_DOC_TYPES = ("decree", "order")
# Заголовок приложения: «Приложение N …» / штамп утверждения «УТВЕРЖДЕНО…».
# Штамп — только формы причастия (УТВЕРЖДЁН/УТВЕРЖДЕН/-А/-О/-Ы по роду документа),
# НЕ существительное «утверждение» и НЕ глагол «утверждать» (иначе ловили бы прозу).
# group(1) — номер (может отсутствовать), group(2) — остаток строки (для заголовка).
APPENDIX_RE = re.compile(
    r"^(?:Приложени\w*|УТВЕРЖДЁН|УТВЕРЖДЕН[АОЫ]?)\b\s*(?:(?:N|№)\s*)?(\d+)?[.:]?\s*(.*)$",
    re.IGNORECASE,
)
# Пункт подзаконного акта: дроблёный номер В НАЧАЛЕ строки + текст: «1.», «1.1.», «12.3.».
# Требуем пробел и непустой текст после точки — чтобы «2.5 ставки» в прозе не считалось пунктом.
POINT_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")

# Реквизиты НПА: номер вида «197-ФЗ» / «1-ФКЗ» и дата «ДД.ММ.ГГГГ»
NUMBER_HINT_RE = re.compile(r"\b(\d{1,4}-(?:ФЗ|ФКЗ))\b")
DATE_HINT_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")

# Дата инкорпорированной поправки: «… от ДД.ММ.ГГГГ № NNN-ФЗ» (или -ФКЗ).
# Максимум таких дат = дата последней поправки = дата редакции (см. spec §4.1).
# \xa0 — неразрывный пробел в тексте ИПС, поэтому разделители — [ \xa0]+ вместо \s+.
REDACTION_DATE_RE = re.compile(
    r"от[ \xa0]+(\d{2})\.(\d{2})\.(\d{4})[ \xa0]*(?:№|N)[ \xa0]*\d+-(?:ФКЗ|ФЗ)",
    re.IGNORECASE,
)

# Ключевые слова в наименовании НПА — приоритетные кандидаты в заголовок.
TITLE_KEYWORDS = ("кодекс", "федеральный закон", "постановление", "приказ", "закон")
_TITLE_SKIP = {"главная", "поиск", "официальный интернет-портал"}
# Строка-«тип акта» без названия (шапка ИПС): заголовок ищем на следующей строке.
_BARE_ACT_TYPES = {"федеральный закон", "федеральный конституционный закон", "закон"}


@dataclass
class ParsedArticle:
    number: str
    title: str
    text: str
    order: int
    kind: str = "article"  # "section" | "chapter" | "article"
    parent_order: int | None = None  # order of the nearest enclosing parent node


@dataclass
class ParsedDocument:
    full_text: str
    title: str = ""
    articles: list[ParsedArticle] = field(default_factory=list)
    detected_number: str = ""
    detected_date: str = ""
    detected_redaction_date: date | None = None


def html_to_text(content: bytes, content_type: str = "text/html") -> str:
    """Извлечь читаемый текст. HTML → текст без тегов (script/style/head удаляются);
    нехтмл — декодируется как UTF-8. Результат нормализуется (без пустых строк)."""
    if "html" in (content_type or "").lower():
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
        # ИПС (pravo.gov.ru) размечает дробные номера надстрочным индексом:
        # «Статья 312<span class="W9">1</span>.» означает «Статья 312.1.».
        # Без склейки get_text("\n") разорвал бы такой заголовок на три строки.
        for sup in soup.find_all("span", class_="W9"):
            inner = sup.get_text(strip=True)
            sup.replace_with(f".{inner}" if inner else "")
        soup.smooth()
        raw = soup.get_text("\n")
    else:
        raw = content.decode("utf-8", errors="replace")
    lines = [line.strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_articles(text: str) -> list[ParsedArticle]:
    """Разбить нормализованный текст на статьи по заголовкам «Статья N.»."""
    articles: list[ParsedArticle] = []
    current: ParsedArticle | None = None
    body: list[str] = []
    order = 0
    for line in text.splitlines():
        match = ARTICLE_RE.match(line)
        if match:
            if current is not None:
                current.text = "\n".join(body).strip()
                articles.append(current)
            order += 1
            current = ParsedArticle(
                number=match.group(1), title=match.group(2).strip(), text="", order=order
            )
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        current.text = "\n".join(body).strip()
        articles.append(current)
    return articles


def detect_title(text: str) -> str:
    """Заголовок акта: первая строка с ключевым словом НПА; иначе — первая
    осмысленная нестатейная строка (не навигация, длиннее 10 символов)."""
    candidates = [
        line
        for line in text.splitlines()
        if line
        and not ARTICLE_RE.match(line)
        and not SECTION_RE.match(line)
        and not CHAPTER_RE.match(line)
    ]
    for i, line in enumerate(candidates):
        low = line.lower()
        if any(k in low for k in TITLE_KEYWORDS):
            if low.strip(' .«»"') in _BARE_ACT_TYPES and i + 1 < len(candidates):
                return candidates[i + 1]
            return line
    for line in candidates:
        if len(line) > 10 and line.lower() not in _TITLE_SKIP:
            return line
    return candidates[0] if candidates else ""


def detect_redaction_date(text: str) -> date | None:
    """Дата редакции = максимум дат из цитат поправок «… от ДД.ММ.ГГГГ № NNN-ФЗ».
    None, если ни одной цитаты-закона нет (тогда авто-публикация не сработает)."""
    dates = [
        date(int(y), int(m), int(d))
        for d, m, y in REDACTION_DATE_RE.findall(text or "")
    ]
    return max(dates) if dates else None


def parse_text(text: str, doc_type: str | None = None) -> ParsedDocument:
    """Разбор УЖЕ нормализованного текста (результат html_to_text):
    структура + заголовок-эвристика + реквизиты. Для подзаконных типов
    (decree/order) — разбор по пунктам/приложениям, иначе — кодексовый."""
    if doc_type in POINT_DOC_TYPES:
        articles = parse_points(text)
    else:
        articles = parse_structure(text)
    title = detect_title(text)
    num = NUMBER_HINT_RE.search(text)
    dt = DATE_HINT_RE.search(text)
    return ParsedDocument(
        full_text=text,
        title=title,
        articles=articles,
        detected_number=num.group(1) if num else "",
        detected_date=dt.group(1) if dt else "",
        detected_redaction_date=detect_redaction_date(text),
    )


def parse_document(
    content: bytes, content_type: str = "text/html", doc_type: str | None = None
) -> ParsedDocument:
    """Полный разбор: нормализовать содержимое и разобрать (тонкая обёртка над parse_text)."""
    return parse_text(html_to_text(content, content_type), doc_type)


def parse_points(text: str) -> list[ParsedArticle]:
    """Иерархический разбор подзаконного акта (постановление/приказ):
    приложения, разделы/главы (переиспользуя кодексовые SECTION_RE/CHAPTER_RE)
    и пункты «N.N.N». Вложенность пунктов — по дроблёному номеру (1.1 — потомок 1);
    верхнеуровневые пункты крепятся к ближайшему контейнеру (глава/раздел/приложение)."""
    nodes: list[ParsedArticle] = []
    order = 0
    current_appendix: int | None = None
    current_section: int | None = None
    current_chapter: int | None = None
    current_point: ParsedArticle | None = None
    point_by_number: dict[str, ParsedArticle] = {}
    body: list[str] = []

    def flush_point() -> None:
        nonlocal current_point
        if current_point is not None:
            current_point.text = "\n".join(body).strip()
            current_point = None
            body.clear()  # защита: исключить накопление чужих строк после флаша

    def container() -> int | None:
        # Ближайший открытый контейнер для верхнеуровневого пункта.
        return current_chapter or current_section or current_appendix

    for line in text.splitlines():
        app = APPENDIX_RE.match(line)
        sec = SECTION_RE.match(line)
        chap = CHAPTER_RE.match(line)
        pt = POINT_RE.match(line)
        if app:
            flush_point()
            order += 1
            nodes.append(
                ParsedArticle(app.group(1) or "", app.group(2).strip(), "", order, "appendix", None)
            )
            current_appendix, current_section, current_chapter = order, None, None
            point_by_number = {}  # нумерация пунктов независима в каждом приложении
        elif sec:
            flush_point()
            order += 1
            nodes.append(
                ParsedArticle(sec.group(1), sec.group(2).strip(), "", order, "section", current_appendix)
            )
            current_section, current_chapter = order, None
        elif chap:
            flush_point()
            order += 1
            nodes.append(
                ParsedArticle(
                    chap.group(1), chap.group(2).strip(), "", order, "chapter",
                    current_section or current_appendix,
                )
            )
            current_chapter = order
        elif pt:
            flush_point()
            order += 1
            number, inline = pt.group(1), pt.group(2).strip()
            if "." in number:
                parent_node = point_by_number.get(number.rsplit(".", 1)[0])
                parent_order = parent_node.order if parent_node else container()
            else:
                parent_order = container()
            current_point = ParsedArticle(number, "", inline, order, "point", parent_order)
            nodes.append(current_point)
            point_by_number[number] = current_point
            body = [inline]
        elif current_point is not None:
            body.append(line)
    flush_point()
    return nodes


def parse_structure(text: str) -> list[ParsedArticle]:
    """Иерархический разбор: разделы/главы/статьи в порядке следования.
    parent_order указывает на order ближайшего раздела (для главы) или главы/раздела (для статьи)."""
    nodes: list[ParsedArticle] = []
    order = 0
    current_section: int | None = None
    current_chapter: int | None = None
    current_article: ParsedArticle | None = None
    body: list[str] = []

    def flush_article() -> None:
        nonlocal current_article
        if current_article is not None:
            current_article.text = "\n".join(body).strip()
            current_article = None

    for line in text.splitlines():
        sec = SECTION_RE.match(line)
        chap = CHAPTER_RE.match(line)
        art = ARTICLE_RE.match(line)
        if sec:
            flush_article()
            order += 1
            nodes.append(
                ParsedArticle(sec.group(1), sec.group(2).strip(), "", order, "section", None)
            )
            current_section, current_chapter = order, None
        elif chap:
            flush_article()
            order += 1
            nodes.append(
                ParsedArticle(
                    chap.group(1), chap.group(2).strip(), "", order, "chapter", current_section
                )
            )
            current_chapter = order
        elif art:
            flush_article()
            order += 1
            parent = current_chapter if current_chapter is not None else current_section
            current_article = ParsedArticle(
                art.group(1), art.group(2).strip(), "", order, "article", parent
            )
            nodes.append(current_article)
            body = []
        elif current_article is not None:
            body.append(line)
    flush_article()
    return nodes
