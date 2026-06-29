"""Тесты команды repair_duplicate_anchors.

С появлением БД-ограничения uniq_redaction_anchor (миграция 0018) создать дубль
(redaction, anchor) в тест-БД больше нельзя — поэтому интеграционный путь
(перенумерация реальных дублей) проверить нечем. Тестируем чистую логику
реконструкции номера и то, что на БД без дублей команда отрабатывает вхолостую.
Сама перенумерация выполнена разово на dev-БД до навешивания ограничения.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from documents.management.commands.repair_duplicate_anchors import _reconstruct
from documents.models import Article


def _row(number, title, kind=Article.Kind.ARTICLE):
    # Несохранённый экземпляр — БД не трогаем, _reconstruct читает только поля.
    return Article(number=number, title=title, kind=kind)


def test_reconstruct_article_hyphen_suffix():
    assert _reconstruct(_row("123.20", "-1. Основные положения о личном фонде")) == (
        "123.20-1",
        "Основные положения о личном фонде",
    )


def test_reconstruct_roman_chapter_dot_suffix():
    assert _reconstruct(_row("V", "1. Предоставление участков", Article.Kind.CHAPTER)) == (
        "V.1",
        "Предоставление участков",
    )


def test_reconstruct_returns_none_for_normal_title():
    assert _reconstruct(_row("81", "Расторжение трудового договора")) is None


@pytest.mark.django_db
def test_command_no_dups_is_noop():
    out = StringIO()
    call_command("repair_duplicate_anchors", stdout=out)
    assert "чинить нечего" in out.getvalue()
