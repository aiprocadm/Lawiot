from django.core.management.base import BaseCommand
from django.db import connection

# Векторы должны 1-в-1 повторять Redaction.update_search_index():
# заголовок документа — вес A, full_text — вес B; для статьи number/title — A, text — B.
_REDACTION_SQL = """
UPDATE documents_redaction r
SET search_vector =
    setweight(to_tsvector('russian', coalesce(d.title, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(r.full_text, '')), 'B')
FROM documents_document d
WHERE r.document_id = d.id AND r.review_status = 'published';
"""

_ARTICLE_SQL = """
UPDATE documents_article a
SET search_vector =
    setweight(to_tsvector('russian', coalesce(a.number, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(a.title, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(a.text, '')), 'B')
FROM documents_redaction r
WHERE a.redaction_id = r.id AND r.review_status = 'published';
"""


class Command(BaseCommand):
    help = "Пересобирает поисковые векторы опубликованных редакций (bulk, 2 запроса)."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(_REDACTION_SQL)
            redactions = cursor.rowcount
            cursor.execute(_ARTICLE_SQL)
            articles = cursor.rowcount
        self.stdout.write(
            self.style.SUCCESS(f"Переиндексировано: редакций {redactions}, статей {articles}")
        )
