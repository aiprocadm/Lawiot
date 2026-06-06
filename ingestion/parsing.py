import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

PARSER_VERSION = "1.0"

# Заголовок статьи: «Статья 81. Расторжение…» / «Статья 312.1. …»
ARTICLE_RE = re.compile(r"^Статья\s+(\d+(?:\.\d+)?)\.?\s*(.*)$")


@dataclass
class ParsedArticle:
    number: str
    title: str
    text: str
    order: int


@dataclass
class ParsedDocument:
    full_text: str
    title: str = ""
    articles: list[ParsedArticle] = field(default_factory=list)


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


def parse_document(content: bytes, content_type: str = "text/html") -> ParsedDocument:
    """Полный разбор: текст + список статей + заголовок-эвристика (первая нестатейная строка)."""
    text = html_to_text(content, content_type)
    articles = parse_articles(text)
    title = ""
    for line in text.splitlines():
        if not ARTICLE_RE.match(line):
            title = line
            break
    return ParsedDocument(full_text=text, title=title, articles=articles)
