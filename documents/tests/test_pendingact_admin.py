import pytest

from documents.admin import (
    PendingActResolvedFilter,
    bind_to_ips,
    suggest_nd_candidates,
)
from documents.models import Document, PendingAct, Redaction
from documents.tests.factories import make_document, make_redaction


def _make_resolved_act(i):
    doc = make_document(
        slug=f"doc-{i}",
        official_number=f"{i}-ФЗ",
        doc_type=Document.DocType.ORDER,
    )
    make_redaction(
        document=doc,
        is_current=True,
        review_status=Redaction.ReviewStatus.PUBLISHED,
    )
    return PendingAct.objects.create(
        slug=f"act-{i}",
        title=f"Акт {i}",
        official_number=f"{i}-ФЗ",
        doc_type=Document.DocType.ORDER,
    )


@pytest.mark.django_db
def test_resolved_filter_uses_constant_queries(django_assert_max_num_queries):
    """Фильтр «в корпусе» не должен делать запрос на каждый акт (N+1).
    Число актов растёт — число запросов остаётся ограниченным."""
    for i in range(6):
        _make_resolved_act(i)
        PendingAct.objects.create(
            slug=f"un-{i}",
            title=f"Не в корпусе {i}",
            official_number=f"u{i}",
            doc_type=Document.DocType.ORDER,
        )

    flt = PendingActResolvedFilter(
        request=None,
        params={"resolved": ["yes"]},
        model=PendingAct,
        model_admin=None,
    )
    assert flt.value() == "yes"

    with django_assert_max_num_queries(3):
        result = list(flt.queryset(None, PendingAct.objects.all()))

    assert len(result) == 6
    assert all(act.is_resolved for act in result)


@pytest.mark.django_db
def test_bind_to_ips_creates_auto_ingest_document():
    act = PendingAct.objects.create(
        slug="prikaz-320n-eo1",
        title="Об утверждении формы трудовых книжек",
        official_number="320н",
        doc_type=Document.DocType.ORDER,
        eo_number="0001202106020001",
        ips_nd="102074279",
        issuing_body="Минтруд России",
    )
    bind_to_ips(None, None, PendingAct.objects.filter(pk=act.pk))
    doc = Document.objects.get(slug="prikaz-320n-eo1")
    assert doc.doc_type == Document.DocType.ORDER
    assert doc.official_number == "320н"
    assert doc.auto_ingest is True
    assert doc.auto_publish is False
    assert "nd=102074279" in doc.source_url
    act.refresh_from_db()
    assert act.resolution_status == PendingAct.ResolutionStatus.BOUND


@pytest.mark.django_db
def test_bind_to_ips_skips_without_nd():
    act = PendingAct.objects.create(
        slug="no-nd", title="Без nd", doc_type=Document.DocType.ORDER
    )
    bind_to_ips(None, None, PendingAct.objects.filter(pk=act.pk))
    assert not Document.objects.filter(slug="no-nd").exists()
    act.refresh_from_db()
    assert act.resolution_status == PendingAct.ResolutionStatus.NEW


@pytest.mark.django_db
def test_bind_to_ips_preserves_existing_document_promotion_and_requisites():
    # Документ с тем же slug уже выверен куратором и поднят по лестнице доверия
    # (auto_publish=True). Повторная привязка НЕ должна сбросить промо или
    # перетереть реквизиты — только обновить источник и включить авто-ингест.
    Document.objects.create(
        slug="prikaz-dup",
        title="Выверенный куратором заголовок",
        official_number="999н",
        doc_type=Document.DocType.ORDER,
        source_url="http://old",
        auto_ingest=False,
        auto_publish=True,
    )
    act = PendingAct.objects.create(
        slug="prikaz-dup",
        title="Сырой заголовок из находки",
        official_number="320н",
        doc_type=Document.DocType.ORDER,
        ips_nd="102074279",
    )
    bind_to_ips(None, None, PendingAct.objects.filter(pk=act.pk))
    doc = Document.objects.get(slug="prikaz-dup")
    assert doc.auto_publish is True  # промо НЕ сброшено
    assert doc.title == "Выверенный куратором заголовок"  # реквизиты НЕ перетёрты
    assert doc.official_number == "999н"
    assert doc.auto_ingest is True  # включён
    assert "nd=102074279" in doc.source_url  # источник обновлён
    assert Document.objects.filter(slug="prikaz-dup").count() == 1  # не задвоился


@pytest.mark.django_db
def test_suggest_nd_candidates_writes_candidate(monkeypatch):
    import ingestion.ips_resolve as ipsr

    monkeypatch.setattr(
        ipsr, "resolve_nd", lambda act, **kw: ipsr.ResolveResult(candidates=["102074279"])
    )
    act = PendingAct.objects.create(
        slug="cand-1", title="Об утверждении", doc_type=Document.DocType.ORDER
    )
    suggest_nd_candidates(None, None, PendingAct.objects.filter(pk=act.pk))
    act.refresh_from_db()
    assert act.ips_nd == "102074279"
    assert act.resolution_status == PendingAct.ResolutionStatus.CANDIDATE
    assert "102074279" in act.note


@pytest.mark.django_db
def test_suggest_nd_candidates_noop_when_empty(monkeypatch):
    import ingestion.ips_resolve as ipsr

    monkeypatch.setattr(
        ipsr, "resolve_nd", lambda act, **kw: ipsr.ResolveResult(candidates=[], note="нет")
    )
    act = PendingAct.objects.create(slug="cand-2", title="X", doc_type=Document.DocType.ORDER)
    suggest_nd_candidates(None, None, PendingAct.objects.filter(pk=act.pk))
    act.refresh_from_db()
    assert act.ips_nd == ""
    assert act.resolution_status == PendingAct.ResolutionStatus.NEW
