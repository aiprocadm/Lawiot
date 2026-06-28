"""Тесты команды repair_duplicate_anchors — починка исторических дублей
(redaction, anchor) у статей с суффиксным номером (123.20-1, Глава V.1)."""

from io import StringIO

import pytest
from django.core.management import call_command

from documents.tests.factories import make_article, make_document, make_redaction


def _run(*args):
    call_command("repair_duplicate_anchors", *args, stdout=StringIO())


@pytest.mark.django_db
def test_renumbers_verified_dup_and_keeps_canonical():
    doc = make_document(slug="gk", official_number="51-ФЗ")
    red = make_redaction(
        doc,
        full_text=(
            "Статья 123.20. Личный фонд\nбаза\n"
            "Статья 123.20-1. Основные положения о личном фонде\nтекст"
        ),
    )
    base = make_article(red, number="123.20", title="Личный фонд", text="база", order=1)
    dup = make_article(
        red, number="123.20", title="-1. Основные положения о личном фонде", text="текст", order=2
    )
    assert base.anchor == dup.anchor == "st-123-20"  # дефект воспроизведён

    _run("--apply")

    base.refresh_from_db()
    dup.refresh_from_db()
    assert base.number == "123.20" and base.anchor == "st-123-20"  # каноничную не трогаем
    assert dup.number == "123.20-1"
    assert dup.title == "Основные положения о личном фонде"
    assert dup.anchor == "st-123-20-1"


@pytest.mark.django_db
def test_renumbers_roman_chapter_suffix():
    doc = make_document(slug="zk", official_number="136-ФЗ")
    red = make_redaction(doc, full_text="Глава V.1. Предоставление участков\nтекст")
    from documents.models import Article

    make_article(red, kind=Article.Kind.CHAPTER, number="V", title="Базовая", order=1)
    dup = make_article(
        red, kind=Article.Kind.CHAPTER, number="V", title="1. Предоставление участков", order=2
    )
    _run("--apply")
    dup.refresh_from_db()
    assert dup.number == "V.1"
    assert dup.anchor == "glava-v-1"


@pytest.mark.django_db
def test_skips_when_reconstruction_not_in_source():
    doc = make_document(slug="x", official_number="1")
    red = make_redaction(doc, full_text="Статья 5. Базовая\nтекст")  # «5-1» в исходнике нет
    make_article(red, number="5", title="Базовая", order=1)
    dup = make_article(red, number="5", title="-1. Призрак", order=2)
    _run("--apply")
    dup.refresh_from_db()
    assert dup.number == "5"  # не подтверждено источником — пропуск
    assert dup.anchor == "st-5"


@pytest.mark.django_db
def test_dry_run_makes_no_changes():
    doc = make_document(slug="gk2", official_number="51-ФЗ")
    red = make_redaction(doc, full_text="Статья 123.20-1. Основные положения\nтекст")
    make_article(red, number="123.20", title="Базовая", order=1)
    dup = make_article(red, number="123.20", title="-1. Основные положения", order=2)
    _run()  # без --apply
    dup.refresh_from_db()
    assert dup.number == "123.20"  # dry-run: без изменений
    assert dup.anchor == "st-123-20"
