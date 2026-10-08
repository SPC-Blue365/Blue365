import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from qms import llm


class _Stream:
    def __init__(self, chunks, final, fail=None):
        self.chunks, self.final, self.fail = chunks, final, fail

    def __enter__(self):
        if self.fail:
            raise self.fail
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter(self.chunks)

    def get_final_message(self):
        return self.final


class _API:
    def __init__(self, owner, beta):
        self.owner, self.beta = owner, beta

    def stream(self, **kw):
        self.owner.calls.append((self.beta, kw))
        fail = self.owner.fail_beta if self.beta else None
        return _Stream(self.owner.chunks, self.owner.final, fail)


class FakeClient:
    def __init__(self, chunks, stop="end_turn", model="claude-opus-5-5", fail_beta=None):
        self.calls = []
        self.chunks = chunks
        self.fail_beta = fail_beta
        self.final = NS(stop_reason=stop, model=model,
                        usage=NS(input_tokens=3000, output_tokens=2000, cache_creation_input_tokens=0,
                                 cache_read_input_tokens=6000))
        self.messages = _API(self, False)
        self.beta = NS(messages=_API(self, True))


@pytest.fixture()
def log_path(tmp_path):
    return tmp_path / "ai_log.jsonl"


def test_stream_request_shape_and_logging(log_path):
    fc = FakeClient(["## 1. 결론\n", "[사실] 28일 52.5 MPa"])
    rs = llm.ReportStream("strength", {"b": np.float64(1.234567), "a": [1, np.nan]}, llm.LLMConfig(enabled=True),
                          client=fc, log_path=log_path)
    text = "".join(rs)
    assert "결론" in text and rs.result.ok and rs.result.text == text
    beta, kw = fc.calls[0]
    assert beta and kw["betas"] == [llm.FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"] == {"effort": "high"}
    assert "thinking" not in kw                                   # 적응형 사고가 기본 — 지정하지 않음
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "[사실]" in kw["system"][0]["text"] and "6가크롬" in kw["system"][0]["text"]
    content = kw["messages"][0]["content"]
    payload = json.loads(content.split("```json\n")[1].split("\n```")[0])
    assert payload == {"a": [1, None], "b": 1.2346}               # 정렬·반올림·NaN→null
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["kind"] == "strength" and entry["usage"]["output_tokens"] == 2000 and entry["cost_usd"] > 0
    assert rs.result.cost_usd == pytest.approx((3000 * 4 + 6000 * 0.2 + 2000 * 20) / 1e6)


def test_refusal_discards_partial_output(log_path):
    fc = FakeClient(["부분 출력"], stop="refusal")
    res = llm.generate("chromium", {"x": 1}, llm.LLMConfig(enabled=True), client=fc, log_path=log_path)
    assert not res.ok and res.text == "" and res.stop_reason == "refusal"


def test_haiku_has_no_fallbacks_and_fallback_retry(log_path):
    fc = FakeClient(["ok"], model="claude-haiku-5-5")
    llm.generate("rawmix", {"x": 1}, llm.LLMConfig(enabled=True, model="claude-haiku-5-5"), client=fc, log_path=log_path)
    beta, kw = fc.calls[0]
    assert not beta and "fallbacks" not in kw and "betas" not in kw
    fc2 = FakeClient(["ok"], fail_beta=RuntimeError("fallbacks parameter not supported"))
    res = llm.generate("rawmix", {"x": 1}, llm.LLMConfig(enabled=True), client=fc2, log_path=log_path)
    assert res.ok and [b for b, _ in fc2.calls] == [True, False]    # 대체 모델 매개변수 거부 → 일반 요청 재시도


def test_errors_are_reported_not_raised(log_path):
    fc = FakeClient([], fail_beta=RuntimeError("boom"))
    res = llm.generate("rawmix", {"x": 1}, llm.LLMConfig(enabled=True), client=fc, log_path=log_path)
    assert not res.ok and "boom" in res.error


def test_ai_ready_requires_enable_and_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(llm, "_secret_key", lambda: "")
    assert not llm.ai_ready(llm.LLMConfig(enabled=False))[0]
    ok, msg = llm.ai_ready(llm.LLMConfig(enabled=True))
    assert not ok and "API 키" in msg
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert llm.credential_status() == (True, "환경변수 ANTHROPIC_API_KEY")


def test_config_roundtrip_and_cost_estimate(tmp_path):
    p = tmp_path / "llm.json"
    llm.save_llm_config(llm.LLMConfig(enabled=True, model="claude-sonnet-5-5", effort="max"), p)
    cfg = llm.load_llm_config(p)
    assert cfg.enabled and cfg.model == "claude-sonnet-5-5" and cfg.effort == "max"
    assert "api_key" not in p.read_text(encoding="utf-8")
    assert llm.estimate_call_cost("claude-haiku-5-5") < llm.estimate_call_cost("claude-opus-5-5") < \
        llm.estimate_call_cost("claude-fable-5-1")
