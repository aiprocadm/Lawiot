import pytest
from django.core.management import call_command

from documents.models import Document
from documents.seed.labor_law import PENDING_ACTS, SEED_ACTS, _RF_CODES

# Акты трудового права (не кодексы), добавленные после приёмки живым fetch+parse.
_NEW_LABOR_ACTS = {
    "nesch-125-fz": "125-ФЗ",
    "sever-4520-1": "4520-1",
    "socstrah-165-fz": "165-ФЗ",
    "posobiya-deti-81-fz": "81-ФЗ",
    "rtk-92-fz": "92-ФЗ",
}
# Акты, которых хотим в корпусе, но nd= источника пока не найден (PendingAct).
_EXPECTED_PENDING_SLUGS = {
    "zanyatost-565-fz", "obyed-rabotodateley-156-fz", "vnim-255-fz",
}

# Все 23 действующих федеральных кодекса РФ (ТК РФ заведён отдельной записью выше).
_EXPECTED_CODE_SLUGS = {
    "gk-1-rf", "gk-2-rf", "gk-3-rf", "gk-4-rf", "nk-1-rf", "nk-2-rf", "koap-rf",
    "kas-rf", "gradostroit-rf", "gpk-rf", "apk-rf", "uk-rf", "upk-rf", "uik-rf",
    "zemelny-rf", "zhilishchny-rf", "semejny-rf", "vodny-rf", "lesnoy-rf",
    "vozdushny-rf", "byudzhetny-rf", "kvvt-rf", "ktm-rf",
}


def test_rf_codes_table_is_well_formed():
    """Чистая проверка без БД: уникальность slug/nd, корректные URL и заголовки."""
    assert len(_RF_CODES) == 23
    slugs = [c[0] for c in _RF_CODES]
    nds = [c[4] for c in _RF_CODES]
    assert set(slugs) == _EXPECTED_CODE_SLUGS
    assert len(set(slugs)) == len(slugs), "дублирующиеся slug"
    assert len(set(nds)) == len(nds), "дублирующиеся nd="
    for slug, title, number, sign_date, nd in _RF_CODES:
        assert "кодекс" in title.lower(), slug
        assert number.endswith("-ФЗ"), slug
        assert nd.isdigit(), slug
        # дата подписания правдоподобна (после принятия Конституции 1993 г.)
        assert sign_date[0] >= 1993, slug


def test_seed_acts_has_no_duplicate_slugs():
    slugs = [a["slug"] for a in SEED_ACTS]
    assert len(set(slugs)) == len(slugs), "дублирующиеся slug в SEED_ACTS"


def test_new_labor_law_acts_well_formed():
    """Чистая проверка без БД: новые ФЗ трудового права присутствуют, поля
    корректны, источник — консолидированный текст ИПС (print=1). Приёмка
    парсера — живым fetch+parse (см. комментарии в seed/labor_law.py)."""
    by_slug = {a["slug"]: a for a in SEED_ACTS}
    for slug, number in _NEW_LABOR_ACTS.items():
        act = by_slug[slug]
        assert act["official_number"] == number, slug
        assert act["doc_type"] == "federal_law", slug
        assert act["level"] == "federal", slug
        assert act["source_status"] == "official", slug
        assert act["auto_ingest"] is True, slug
        # Консервативно: новые ФЗ не авто-публикуются — только черновики куратору.
        assert act.get("auto_publish", False) is False, slug
        assert "doc_itself" in act["source_url"], slug
        assert "print=1" in act["source_url"], slug
        assert "nd=" in act["source_url"], slug
        assert act["sign_date"] is not None, slug


def test_pending_acts_table_is_well_formed():
    """Реестр ожидаемых актов содержит ожидаемые slug; каждая запись с источником-
    подсказкой для куратора (ips_search_url) и пояснением (note)."""
    slugs = {p["slug"] for p in PENDING_ACTS}
    assert _EXPECTED_PENDING_SLUGS <= slugs
    for p in PENDING_ACTS:
        assert p["official_number"].strip(), p["slug"]
        assert p["note"].strip(), p["slug"]
        assert p["ips_search_url"].startswith("http"), p["slug"]


@pytest.mark.django_db
def test_seed_corpus_loads_all_rf_codes():
    call_command("seed_corpus")
    codes = Document.objects.filter(slug__in=_EXPECTED_CODE_SLUGS)
    assert codes.count() == 23
    for doc in codes:
        assert doc.doc_type == "code", doc.slug
        assert doc.level == "federal"
        assert doc.status == "in_force"
        assert doc.source_status == "official"
        assert doc.auto_ingest is True
        assert doc.auto_publish is True
        # источник — консолидированный текст ИПС (print=1 против обрезки)
        assert "doc_itself" in doc.source_url and "print=1" in doc.source_url
        assert "nd=" in doc.source_url
        assert doc.sign_date is not None


@pytest.mark.django_db
def test_seed_corpus_is_idempotent():
    call_command("seed_corpus")
    first = Document.objects.count()
    assert Document.objects.filter(slug="tk-rf").exists()
    assert Document.objects.filter(slug="sout-426-fz", official_number="426-ФЗ").exists()
    call_command("seed_corpus")  # повтор не плодит дубликаты и не падает
    assert Document.objects.count() == first


@pytest.mark.django_db
def test_seed_corpus_does_not_publish_anything():
    call_command("seed_corpus")
    doc = Document.objects.get(slug="tk-rf")
    assert not doc.redactions.exists()
