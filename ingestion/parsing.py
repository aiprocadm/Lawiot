import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

PARSER_VERSION = "1.0"

# Заголовок статьи: «Статья 81. Расторжение…» / «Статья 312.1. …»
ARTICLE_RE = re.compile(r"^Статья\s+(\d+(?:\.\d+)?)\.?\s*(.*)$")
# Раздел римской цифрой: «Раздел I. Общие положения»
SECTION_RE = re.compile(r"^Раздел\s+([IVXLCDM]+)\.?\s*(.*)$", re.IGNORECASE)
# Глава арабской цифрой: «Глава 1. Основные начала» / «Глава 12.1. …»
CHAPTER_RE = re.compile(r"^Глава\s+(\d+(?:\.\d+)?)\.?\s*(.*)$", re.IGNORECASE)

# Реквизиты НПА: номер вида «197-ФЗ» / «1-ФКЗ» и дата «ДД.ММ.ГГГГ»
NUMBER_HINT_RE = re.compile(r"\b(\d{1,4}-(?:ФЗ|ФКЗ))\b")
DATE_HINT_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")

# Ключевые слова в наименовании НПА — приоритетные кандидаты в заголовок.
TITLE_KEYWORDS = ("кодекс", "федеральный закон", "постановление", "приказ", "закон")
_TITLE_SKIP = {"главная", "поиск", "официальный интернет-портал"}


@dataclass
class ParsedArticle:
    number: str
    title: str
    text: str
    order: int
    kind: str = "article"            # "section" | "chapter" | "article"
    parent_order: int | None = None  # order of the nearest enclosing parent node


@dataclass
class ParsedDocument:
    full_text: str
    title: str = ""
    articles: list[ParsedArticle] = field(default_factory=list)
    detected_number: str = ""
    detected_date: str = ""


def html_to_text(content: bytes, content_type: str = "text/html") -> str:
    """Извлечь читаемый текст. HTML → текст без тегов (script/style/head удаляются);
    нехтмл — декодируется как UTF-8. Результат нормализуется (без пустых строк)."""
    if "html" in (content_type or "").lower():
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
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
        line for line in text.splitlines()
        if line and not ARTICLE_RE.match(line)
        and not SECTION_RE.match(line) and not CHAPTER_RE.match(line)
    ]
    for line in candidates:
        low = line.lower()
        if any(k in low for k in TITLE_KEYWORDS):
            return line
    for line in candidates:
        if len(line) > 10 and line.lower() not in _TITLE_SKIP:
            return line
    return candidates[0] if candidates else ""


def parse_document(content: bytes, content_type: str = "text/html") -> ParsedDocument:
    """Полный разбор: текст + список статей + заголовок-эвристика + реквизиты."""
    text = html_to_text(content, content_type)
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
    )


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
            nodes.append(ParsedArticle(sec.group(1), sec.group(2).strip(), "", order, "section", None))
            current_section, current_chapter = order, None
        elif chap:
            flush_article()
            order += 1
            nodes.append(ParsedArticle(chap.group(1), chap.group(2).strip(), "", order, "chapter", current_section))
            current_chapter = order
        elif art:
            flush_article()
            order += 1
            parent = current_chapter if current_chapter is not None else current_section
            current_article = ParsedArticle(art.group(1), art.group(2).strip(), "", order, "article", parent)
            nodes.append(current_article)
            body = []
        elif current_article is not None:
            body.append(line)
    flush_article()
    return nodes
