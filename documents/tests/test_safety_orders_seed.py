import pytest
from django.core.management import call_command

from documents.models import Document
from documents.seed.labor_safety_orders import (
    SAFETY_ORDER_ACTS,
    SAFETY_PENDING_ACTS,
    _SAFETY_ORDERS,
)


def test_safety_orders_table_well_formed():
    """Чистая проверка без БД: уникальные slug/nd, корректные поля и источник ИПС.
    Все приказы — архив (status=repealed), тип order, источник doc_itself&print=1."""
    assert len(_SAFETY_ORDERS) == 58
    slugs = [a["slug"] for a in SAFETY_ORDER_ACTS]
    nds = [t[4] for t in _SAFETY_ORDERS]
    assert len(set(slugs)) == len(slugs), "дублирующиеся slug"
    assert len(set(nds)) == len(nds), "дублирующиеся nd="
    for act in SAFETY_ORDER_ACTS:
        assert act["doc_type"] == "order", act["slug"]
        assert act["status"] == "repealed", act["slug"]  # все утратили силу на 2026
        assert act["level"] == "federal"
        assert act["source_status"] == "official"
        assert act["official_number"].endswith("н"), act["slug"]
        assert "охране труда" in act["title"].lower(), act["slug"]
        assert "doc_itself" in act["source_url"] and "print=1" in act["source_url"]
        assert "nd=" in act["source_url"]
        assert act["sign_date"] is not None
        assert act["auto_ingest"] is True and act["auto_publish"] is True


def test_safety_pending_acts_well_formed():
    """Реестр ожидаемых: 8 приказов без HTML в ИПС (скан-PDF) + 7 нормативных
    актов/фед. поправок из расширенного списка (nd= ещё не разрешён)."""
    assert len(SAFETY_PENDING_ACTS) == 15
    for p in SAFETY_PENDING_ACTS:
        assert p["doc_type"] in {"order", "decree", "federal_law"}, p["slug"]
        assert p["official_number"].strip(), p["slug"]
        assert p["note"].strip()
        assert p["ips_search_url"].startswith("http")
    # ключевой действующий акт обучения по ОТ присутствует в реестре
    assert any(p["slug"] == "ot-obuchenie-2464-2021" for p in SAFETY_PENDING_ACTS)


@pytest.mark.django_db
def test_seed_corpus_materializes_safety_orders():
    call_command("seed_corpus")
    orders = Document.objects.filter(doc_type="order", slug__startswith="ot-")
    # 58 заведённых архивных приказов (+ возможные иные order вне префикса ot-)
    assert orders.count() >= 58
    sample = Document.objects.get(slug="ot-782n-2020")
    assert sample.status == "repealed"
    assert sample.official_number == "782н"
    assert "работе на высоте" in sample.title
    assert "doc_itself" in sample.source_url
