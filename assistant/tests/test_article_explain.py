from dataclasses import dataclass

from assistant.article_explain import (
    MODE_EXPLAINED,
    MODE_UNAVAILABLE,
    explain_article,
)


@dataclass
class _Block:
    type: str
    text: str


class _FakeResp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block("text", text)]
        self.stop_reason = stop_reason


class _Msgs:
    def __init__(self, capture, resp):
        self.capture = capture
        self.resp = resp

    def create(self, **kwargs):
        self.capture.append(kwargs)
        return self.resp


class _FakeClient:
    def __init__(self, resp=None):
        self.calls = []
        self.messages = _Msgs(self.calls, resp or _FakeResp("Простыми словами: ..."))


_TEXT = "Работодатель обязан предоставить работнику отпуск продолжительностью 28 дней."


def test_explain_returns_text_and_grounds_on_article():
    fake = _FakeClient()
    result = explain_article(_TEXT, client=fake)
    assert result.mode == MODE_EXPLAINED
    assert "Простыми словами" in result.text
    assert len(fake.calls) == 1
    # текст статьи передан модели
    assert "28 дней" in fake.calls[0]["messages"][0]["content"]


def test_blank_text_is_unavailable_without_calling_model():
    fake = _FakeClient()
    result = explain_article("   ", client=fake)
    assert result.mode == MODE_UNAVAILABLE
    assert fake.calls == []


def test_no_client_degrades_to_unavailable():
    result = explain_article(_TEXT, client=None)
    assert result.mode == MODE_UNAVAILABLE
    assert result.text is None


def test_api_error_degrades_gracefully():
    class _Boom:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("network down")

    result = explain_article(_TEXT, client=_Boom())
    assert result.mode == MODE_UNAVAILABLE
    assert result.error


def test_refusal_degrades_gracefully():
    fake = _FakeClient(resp=_FakeResp("", stop_reason="refusal"))
    result = explain_article(_TEXT, client=fake)
    assert result.mode == MODE_UNAVAILABLE


def test_empty_text_response_degrades_gracefully():
    fake = _FakeClient(resp=_FakeResp("   "))
    result = explain_article(_TEXT, client=fake)
    assert result.mode == MODE_UNAVAILABLE
