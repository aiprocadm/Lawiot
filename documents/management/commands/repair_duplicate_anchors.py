"""Чинит исторические дубли (redaction, anchor) у статей — последствие дефекта
парсера, который не захватывал дефисный/суффиксный номер заголовка.

Старый `ARTICLE_RE` ронял суффикс: «Статья 123.20-1» парсилась как номер
«123.20» + заголовок «-1. …», а «Глава V.1» — как «V» + «1. …». В итоге
несколько статей одной редакции делили якорь → 500 на странице разъяснения и
битые диплинки. Парсер исправлен (новые импорты корректны); эта команда чинит
УЖЕ загруженные данные.

БЕЗОПАСНОСТЬ — переименовываем строку, только если реконструированный заголовок
(«Статья 123.20-1» / «Глава V.1») реально встречается в исходном `full_text`
редакции. Иначе — пропуск (двусмысленные/структурные случаи остаются куратору).
Идемпотентна; pk не меняется (эмбеддинги/search_vector/FK сохраняются) — меняются
только number/title/anchor. По умолчанию dry-run, запись — с `--apply`.
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from documents.models import Article, Redaction

# Ключевое слово заголовка по виду статьи — для проверки в исходном тексте.
_HEADER = {
    Article.Kind.ARTICLE: "Статья",
    Article.Kind.SECTION: "Раздел",
    Article.Kind.CHAPTER: "Глава",
    Article.Kind.POINT: "Статья",
    Article.Kind.APPENDIX: "Приложение",
}
# «-1. Заголовок» → суффикс через дефис (статьи: 123.20-1); «1. Заголовок» →
# суффикс через точку (римские главы/разделы: Глава V.1).
_HYPHEN_RE = re.compile(r"^-(\d+)\.?\s*(.*)$")
_DOT_RE = re.compile(r"^(\d+)\.?\s*(.*)$")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " "))


def _reconstruct(row):
    """(new_number, new_title) из текущего заголовка-артефакта, либо None."""
    m = _HYPHEN_RE.match(row.title)
    if m:
        return f"{row.number}-{m.group(1)}", m.group(2).strip()
    m = _DOT_RE.match(row.title)
    if m:
        return f"{row.number}.{m.group(1)}", m.group(2).strip()
    return None


class Command(BaseCommand):
    help = "Чинит дубли (redaction, anchor): восстанавливает суффиксные номера статей по исходному тексту."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Записать изменения (по умолчанию — только показать, что было бы сделано).",
        )

    def handle(self, *args, **options):
        w = self.stdout.write
        apply = options["apply"]

        dup_groups = list(
            Article.objects.exclude(anchor="")
            .values("redaction", "anchor")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        if not dup_groups:
            w(self.style.SUCCESS("Дублей (redaction, anchor) нет — чинить нечего."))
            return

        ft_cache: dict[int, str] = {}

        def source(rid: int) -> str:
            if rid not in ft_cache:
                ft_cache[rid] = _normalize(Redaction.objects.get(pk=rid).full_text)
            return ft_cache[rid]

        fixed = skipped = 0
        skipped_detail: list[str] = []
        with transaction.atomic():
            for g in dup_groups:
                rid, anchor = g["redaction"], g["anchor"]
                rows = list(
                    Article.objects.filter(redaction_id=rid, anchor=anchor).order_by("order")
                )
                # Первую (каноничную по order) не трогаем — это и есть базовый номер.
                for row in rows[1:]:
                    cand = _reconstruct(row)
                    if cand is None:
                        skipped += 1
                        skipped_detail.append(f"red={rid} {anchor} num={row.number!r} (нет паттерна)")
                        continue
                    new_number, new_title = cand
                    needle = f"{_HEADER.get(row.kind, 'Статья')} {new_number}"
                    if needle not in source(rid):
                        skipped += 1
                        skipped_detail.append(
                            f"red={rid} {anchor} → {new_number!r} (нет в исходнике)"
                        )
                        continue
                    fixed += 1
                    w(f"  red={rid} {row.anchor} → number={new_number!r} title={new_title[:40]!r}")
                    if apply:
                        row.number = new_number
                        row.title = new_title
                        row.anchor = ""  # save() перегенерит якорь из нового номера
                        row.save()
            if not apply:
                transaction.set_rollback(True)

        w("")
        verb = "Исправлено" if apply else "Будет исправлено"
        w(self.style.SUCCESS(f"{verb} строк: {fixed}. Пропущено (куратору): {skipped}."))
        for d in skipped_detail:
            w(self.style.WARNING(f"  ПРОПУСК {d}"))
        if not apply:
            w(self.style.NOTICE("Это dry-run. Запуск с --apply внесёт изменения."))
