import pytest

from documents.models import Link
from documents.tests.factories import make_article, make_document, make_redaction
from ingestion.links import extract_links_for_redaction, find_citations


def test_finds_fz_and_fkz_numbers():
    text = "В соответствии с Федеральным законом от 28.12.2013 № 400-ФЗ и 1-ФКЗ."
    numbers = {c.number for c in find_citations(text)}
    assert numbers == {"400-ФЗ", "1-ФКЗ"}


def test_dedups_repeated_numbers():
    text = "См. 197-ФЗ. Также 197-ФЗ применяется здесь."
    cites = find_citations(text)
    assert [c.number for c in cites] == ["197-ФЗ"]


def test_ignores_plain_numbers_and_dates():
    text = "Пункт 5 от 28.12.2013 года, страница 400."
    assert find_citations(text) == []


def test_captures_context_around_citation():
    text = "Изменения внесены Федеральным законом № 125-ФЗ о страховании."
    (cite,) = find_citations(text)
    assert cite.number == "125-ФЗ"
    assert "125-ФЗ" in cite.context
    assert "страховании" in cite.context


@pytest.mark.django_db
def test_creates_suggested_in_corpus_link():
    src = make_document(slug="src", official_number="197-ФЗ")
    target = make_document(slug="tgt", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Регулируется Федеральным законом № 125-ФЗ.")
    n = extract_links_for_redaction(red)
    assert n == 1
    link = Link.objects.get(from_document=src)
    assert link.to_document == target
    assert link.link_type == Link.LinkType.REFERENCES
    assert link.origin == Link.Origin.AUTO
    assert link.status == Link.Status.SUGGESTED
    assert "125-ФЗ" in link.context


@pytest.mark.django_db
def test_external_citation_becomes_raw():
    src = make_document(slug="src2", official_number="197-ФЗ")
    red = make_redaction(src, full_text="Упоминается 999-ФЗ, которого нет в корпусе.")
    extract_links_for_redaction(red)
    link = Link.objects.get(from_document=src)
    assert link.to_document is None
    assert "999-ФЗ" in link.raw_citation


@pytest.mark.django_db
def test_distinct_numbers_with_substring_are_not_merged():
    # «25-ФЗ» — подстрока «125-ФЗ»: дедуп не должен схлопывать их в одну связь.
    src = make_document(slug="sub", official_number="197-ФЗ")
    red = make_redaction(src, full_text="Применяются 125-ФЗ и 25-ФЗ одновременно.")
    extract_links_for_redaction(red)
    raws = set(
        Link.objects.filter(from_document=src).values_list("raw_citation", flat=True)
    )
    assert raws == {"125-ФЗ", "25-ФЗ"}


@pytest.mark.django_db
def test_skips_self_citation():
    src = make_document(slug="self", official_number="197-ФЗ")
    red = make_redaction(src, full_text="Настоящий 197-ФЗ регулирует отношения.")
    assert extract_links_for_redaction(red) == 0
    assert Link.objects.filter(from_document=src).count() == 0


@pytest.mark.django_db
def test_scans_article_text_too():
    src = make_document(slug="arts", official_number="197-ФЗ")
    target = make_document(slug="tgt2", official_number="125-ФЗ")
    red = make_redaction(src, full_text="")
    make_article(red, number="1", title="Сфера", text="См. также 125-ФЗ.")
    extract_links_for_redaction(red)
    assert Link.objects.filter(from_document=src, to_document=target).exists()


@pytest.mark.django_db
def test_reextraction_is_idempotent():
    src = make_document(slug="idem", official_number="197-ФЗ")
    make_document(slug="t3", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Ссылка на 125-ФЗ.")
    extract_links_for_redaction(red)
    extract_links_for_redaction(red)
    assert Link.objects.filter(from_document=src).count() == 1


@pytest.mark.django_db
def test_reextraction_preserves_and_does_not_duplicate_confirmed():
    src = make_document(slug="conf", official_number="197-ФЗ")
    target = make_document(slug="t4", official_number="125-ФЗ")
    red = make_redaction(src, full_text="Ссылка на 125-ФЗ.")
    # куратор уже подтвердил связь
    Link.objects.create(
        from_document=src, to_document=target,
        link_type=Link.LinkType.REFERENCES,
        origin=Link.Origin.AUTO, status=Link.Status.CONFIRMED,
    )
    extract_links_for_redaction(red)
    links = Link.objects.filter(from_document=src, to_document=target)
    assert links.count() == 1                       # дубль не создан
    assert links.first().status == Link.Status.CONFIRMED  # подтверждение сохранено
