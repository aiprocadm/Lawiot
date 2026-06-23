from dataclasses import dataclass

from assistant.diff_explain import (
    MODE_EXPLAINED,
    MODE_NO_CHANGES,
    MODE_UNAVAILABLE,
    build_diff_prompt,
    explain_diff,
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
        self.messages = _Msgs(self.calls, resp or _FakeResp("Статья 5 уточнена."))


_CHANGES = [
    {"number": "5", "status": "changed", "old_text": "старый текст", "new_text": "новый текст"},
    {"number": "6", "status": "added", "old_text": "", "new_text": "новая статья"},
]


def test_build_prompt_includes_before_after_and_status():
    prompt = build_diff_prompt(_CHANGES)
    assert "Статья 5" in prompt
    assert "старый текст" in prompt
    assert "новый текст" in prompt
    # добавленная статья помечена, старого текста у неё нет
    assert "Статья 6" in prompt
    assert "добавлена" in prompt


def test_explain_returns_text_with_client():
    fake = _FakeClient()
    result = explain_diff(_CHANGES, client=fake)
    assert result.mode == MODE_EXPLAINED
    assert "уточнена" in result.text
    # модель вызвана один раз, заземлена текстом изменений
    assert len(fake.calls) == 1
    assert "старый текст" in fake.calls[0]["messages"][0]["content"]


def test_no_changes_short_circuits_without_calling_model():
    fake = _FakeClient()
    result = explain_diff([], client=fake)
    assert result.mode == MODE_NO_CHANGES
    assert result.text is None
    assert fake.calls == []


def test_no_client_degrades_to_unavailable():
    # без клиента и без ключа — функция не падает, режим «недоступно»
    result = explain_diff(_CHANGES, client=None)
    assert result.mode == MODE_UNAVAILABLE
    assert result.text is None


def test_api_error_degrades_gracefully():
    class _Boom:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("network down")

    result = explain_diff(_CHANGES, client=_Boom())
    assert result.mode == MODE_UNAVAILABLE
    assert result.error


def test_refusal_degrades_gracefully():
    fake = _FakeClient(resp=_FakeResp("", stop_reason="refusal"))
    result = explain_diff(_CHANGES, client=fake)
    assert result.mode == MODE_UNAVAILABLE


def test_empty_text_degrades_gracefully():
    fake = _FakeClient(resp=_FakeResp("   "))
    result = explain_diff(_CHANGES, client=fake)
    assert result.mode == MODE_UNAVAILABLE
