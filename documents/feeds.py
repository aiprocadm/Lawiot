"""Atom-лента изменений — машиночитаемая версия страницы /changes/.

Мост к сценарию «мониторинг» (§17): читатель подписывается в любой
RSS/Atom-читалке и получает свежие опубликованные редакции без захода в
интерфейс. Инфраструктуры не требует (встроенный django.contrib.syndication,
без SMTP/брокера); лента отдаёт те же записи, что и `changes_feed`, в том же
порядке (новые сверху). За тем же `@login_required`, что и весь просмотрщик
(внутренний инструмент, §10) — навешивается в urls.
"""

from collections import defaultdict

from django.contrib.syndication.views import Feed
from django.db.models import F
from django.urls import reverse
from django.utils.feedgenerator import Atom1Feed

from documents.models import Redaction

# Лента не пагинируется — отдаём последние N опубликованных редакций.
MAX_ITEMS = 50


class ChangesFeed(Feed):
    feed_type = Atom1Feed
    title = "Lawiot — лента изменений"
    link = "/changes/"
    subtitle = "Недавно опубликованные редакции актов трудового права."
    author_name = "Lawiot"

    def items(self) -> list[Redaction]:
        published = Redaction.objects.filter(review_status=Redaction.ReviewStatus.PUBLISHED)
        feed = list(
            published.select_related("document").order_by(
                F("published_at").desc(nulls_last=True), "-redaction_date"
            )[:MAX_ITEMS]
        )
        # prev_pk — предыдущая опубликованная редакция того же документа
        # (для diff-ссылки «что изменилось»). Зеркалит логику changes_feed:
        # один доп. запрос по документам ленты вместо N+1.
        doc_ids = {r.document_id for r in feed}
        history = defaultdict(list)
        for doc_id, red_date, pk in (
            published.filter(document_id__in=doc_ids)
            .order_by("redaction_date")
            .values_list("document_id", "redaction_date", "pk")
        ):
            history[doc_id].append((red_date, pk))
        for r in feed:
            r.prev_pk = next(
                (pk for red_date, pk in reversed(history[r.document_id]) if red_date < r.redaction_date),
                None,
            )
        return feed

    def item_title(self, item: Redaction) -> str:
        return f"{item.document.title} — редакция от {item.redaction_date:%d.%m.%Y}"

    def item_description(self, item: Redaction) -> str:
        parts = [f"Действует с {item.redaction_date:%d.%m.%Y}."]
        if item.published_at:
            parts.append(f"Опубликовано {item.published_at:%d.%m.%Y}.")
        if item.prev_pk:
            parts.append("Доступно сравнение с предыдущей редакцией.")
        return " ".join(parts)

    def item_link(self, item: Redaction) -> str:
        # При наличии предыдущей редакции ведём сразу на diff «что изменилось»,
        # иначе — на сам документ.
        if item.prev_pk:
            return reverse("redaction_diff", args=[item.document.slug, item.prev_pk])
        return reverse("document_detail", args=[item.document.slug])

    # Стабильный уникальный id записи: pk редакции, не URL (URL текущей
    # редакции совпадал бы у записей одного документа).
    item_guid_is_permalink = False

    def item_guid(self, item: Redaction) -> str:
        return f"redaction-{item.pk}"

    def item_pubdate(self, item: Redaction):
        return item.published_at

    def item_updateddate(self, item: Redaction):
        return item.published_at
