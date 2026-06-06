import httpx
import pytest

from ingestion.fetching import USER_AGENT, fetch


def test_fetch_returns_content_type_and_final_url():
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<h1>hi</h1>"
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch("https://example.test/doc", client=client)
    assert result.content == b"<h1>hi</h1>"
    assert "html" in result.content_type
    assert result.source_url.endswith("/doc")
    assert result.fetched_at is not None


def test_fetch_sends_polite_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, content=b"ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch("https://example.test/", client=client)
    assert seen["ua"] == USER_AGENT


def test_fetch_raises_on_server_error():
    def handler(request):
        return httpx.Response(500, content=b"boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        fetch("https://example.test/", client=client)
