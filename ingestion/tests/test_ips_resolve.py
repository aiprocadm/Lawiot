import httpx
import pytest

from documents.models import Document, PendingAct
from ingestion.ips_resolve import ResolveResult, resolve_nd


def _client_returning(html, status=200):
    def handler(request):
        return httpx.Response(status, content=html.encode("cp1251"))

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_resolve_extracts_nd_candidates():
    act = PendingAct(slug="x", title="Об утверждении формы", doc_type=Document.DocType.ORDER)
    html = '<a href="?doc_itself=&nd=102074279">Приказ ...</a>'
    res = resolve_nd(act, client=_client_returning(html))
    assert isinstance(res, ResolveResult)
    assert "102074279" in res.candidates


@pytest.mark.django_db
def test_resolve_soft_empty_on_server_error():
    act = PendingAct(slug="y", title="Что-то", doc_type=Document.DocType.ORDER)
    res = resolve_nd(act, client=_client_returning("500", status=500))
    assert res.candidates == []
    assert res.note  # пояснение, не исключение
