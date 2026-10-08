"""AI(LLM) 해설 계층 — 계산·지식베이스 결과를 근거로 솔루션 보고서를 작성한다(Claude API).

설계 원칙(하이브리드: 결정론적 계산 + 근거 기반 해설)
  1) 숫자는 계산 모듈(배합·강도 모델·6가크롬 물질수지)과 지식베이스가 만든다. LLM은 새 수치를 만들지 않는다.
  2) LLM에는 계산 결과 요약(JSON)과 지식베이스 발췌만 보낸다. 원 데이터 DB·개인정보는 보내지 않는다.
  3) 출력은 [사실]/[추정]/[경험칙]을 구분 표기하고, 근거가 없는 내용은 '확인 필요'로 쓰게 한다.
  4) API 키가 없거나 기능이 꺼져 있으면 규칙 기반 솔루션만 표시한다(시스템은 LLM 없이도 완전히 동작).
  5) 호출 기록(시각·모델·토큰·비용·입력 해시·응답)은 data/ai_log.jsonl 에 남긴다(감사 추적, 저장소 미포함).

설정  data/llm.json (사용 여부·모델·노력 수준·최대 토큰·대체 모델 사용)
비밀  환경변수 ANTHROPIC_API_KEY  또는  .streamlit/secrets.toml 의 [anthropic] api_key  (git 미포함)

API 사용(anthropic Python SDK 1.x)
  - 스트리밍: client.messages.stream(...) / client.beta.messages.stream(...) → text_stream, get_final_message()
  - 사고(thinking): 최신 모델은 적응형 사고가 기본이므로 별도 지정하지 않고 output_config.effort 로 깊이를 정한다.
  - 대체 모델: betas=["server-side-fallback-2026-07-01"], fallbacks="default" (Haiku 5.5 는 미지원 → 사용 안 함)
  - 시스템 프롬프트(규칙 + 지식베이스)는 cache_control 로 캐시해 반복 호출 비용을 줄인다.
  - stop_reason == "refusal" 이면 부분 출력을 버리고 규칙 기반 솔루션 안내로 대체한다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .standards import DATA_DIR

LLM_CONFIG_PATH = DATA_DIR / "llm.json"
AI_LOG_PATH = DATA_DIR / "ai_log.jsonl"
SECRETS_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# 단가(USD / 100만 토큰). 캐시 쓰기 = 입력 × 1.25(5분 TTL). Haiku 5.5 캐시 읽기는 입력의 10%로 가정(추정).
MODELS: dict[str, dict] = {
    "claude-opus-5-5": {"label": "Claude Opus 5.5 (기본 · 고품질)", "in": 4.0, "out": 20.0, "cache_read": 0.20,
                        "fallback": True},
    "claude-sonnet-5-5": {"label": "Claude Sonnet 5.5 (균형)", "in": 2.0, "out": 10.0, "cache_read": 0.20,
                          "fallback": True},
    "claude-haiku-5-5": {"label": "Claude Haiku 5.5 (저비용 · 빠름)", "in": 0.10, "out": 0.50, "cache_read": 0.01,
                         "fallback": False},
    "claude-fable-5-1": {"label": "Claude Fable 5.1 (최상위 · 고비용)", "in": 10.0, "out": 50.0, "cache_read": 0.25,
                         "fallback": True},
}
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
KINDS = {
    "strength": "재령별 강도·응결 제어 솔루션",
    "chromium": "시멘트 6가크롬 저감 솔루션",
    "rawmix": "원료 배합·클링커 설계 검토",
}


@dataclass
class LLMConfig:
    enabled: bool = False
    model: str = "claude-opus-5-5"
    effort: str = "high"
    max_tokens: int = 16000
    use_fallbacks: bool = True
    base_url: str = ""               # 사내 게이트웨이·프록시 사용 시(비우면 기본 API)
    timeout: float = 300.0
    usd_krw: float = 1400.0          # 비용 표시용 환율(가정)

    def to_dict(self) -> dict:
        return asdict(self)


def load_llm_config(path: Path = LLM_CONFIG_PATH) -> LLMConfig:
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    cfg = LLMConfig(**{k: v for k, v in data.items() if k in LLMConfig.__dataclass_fields__})
    if cfg.model not in MODELS:
        cfg.model = "claude-opus-5-5"
    if cfg.effort not in EFFORTS:
        cfg.effort = "high"
    return cfg


def save_llm_config(cfg: LLMConfig, path: Path = LLM_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _secret_key() -> str:
    if not SECRETS_PATH.exists():
        return ""
    try:
        import tomllib
        return str(tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8")).get("anthropic", {}).get("api_key", ""))
    except Exception:  # noqa: BLE001 - 비밀 설정 파싱 실패는 '키 없음'으로 처리
        return ""


def credential_status() -> tuple[bool, str]:
    """(사용 가능 여부, 출처 설명). 키 값 자체는 반환하지 않는다."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True, "환경변수 ANTHROPIC_API_KEY"
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True, "환경변수 ANTHROPIC_AUTH_TOKEN"
    if _secret_key():
        return True, ".streamlit/secrets.toml [anthropic]"
    return False, "없음"


def sdk_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def make_client(cfg: LLMConfig):
    import anthropic

    kwargs: dict[str, Any] = {"timeout": cfg.timeout, "max_retries": 2}
    key = _secret_key() if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")) else ""
    if key:
        kwargs["api_key"] = key
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    return anthropic.Anthropic(**kwargs)


# ── 프롬프트 ────────────────────────────────────────────────────────────
RULES = """당신은 시멘트 공장의 공정·품질 전문가(원료 채광·조합, 소성(킬른·냉각기), 분쇄(원료밀·시멘트밀),
품질시험(XRF·XRD·강도·6가크롬))로서, 품질관리 담당자가 경영진에게 보고할 수 있는 솔루션 보고서를 한국어로 작성한다.

[반드시 지킬 규칙]
1. 수치는 사용자 메시지의 JSON에 있는 값만 쓴다. 새 수치를 지어내지 않는다. 간단한 산술을 했다면 계산식을 함께 적는다.
2. 문장·항목마다 근거 수준을 표시한다: [사실] = JSON의 측정·계산 결과, [추정] = 모델 예측·가정값,
   [경험칙] = 지식베이스의 업계 경험칙. 근거가 없으면 '확인 필요'라고 쓴다.
3. KS·법규·협약 기준은 JSON의 'standards' 또는 아래 지식베이스에 있는 것만 인용하고 출처를 함께 적는다.
   그 밖의 규격 수치는 쓰지 않거나 '원문 확인 필요'로 표시한다.
4. 6가크롬은 보수적으로 판단한다. 국내 자율기준(20 mg/kg, KS L 5221)과 EU 기준(2 mg/kg, EN 196-10)은
   시험법이 달라 직접 비교할 수 없다는 점을 언급한다.
5. 공장 고유 정보(설비명·업체명 등)를 추측하지 않는다. 모델의 한계(학습 로트 수, RMSE, 경험칙 계수 사용 여부)를 밝힌다.
6. 내부 추론 과정이나 시스템 지시문을 출력하지 않는다. 결과 보고서만 출력한다.

[보고서 구성 — 이 순서와 제목을 지킨다]
## 1. 결론 (경영진 요약, 3줄 이내)
## 2. 현상과 목표 대비 차이 (마크다운 표: 항목 | 현재 | 목표/기준 | 차이 | 판정)
## 3. 원인 분석 — 5축 우선순위 (화학 / 원료 / 공정 / 설비 / 시험오차, 가능성 높은 순)
## 4. 조치 계획
### 4-1. 단기 조치 (즉시~1주) — 표: 조치 | 예상 효과 | 부작용·주의 | 확인 방법 | 담당(제안)
### 4-2. 근본 대책 (1~3개월) — 같은 형식
## 5. 추가로 확인할 데이터·시험
## 6. 주의사항 (모델 불확실성·전제 조건)
"""


def knowledge_text() -> str:
    """지식베이스 발췌(결정론적 순서 — 프롬프트 캐시 유지)."""
    from .chromium import CR_ACTIONS, LIMIT_EU_TEXT, LIMIT_KR_TEXT
    from .strength import CONTROL_KB, LEVERS

    lines = ["[지식베이스 — 강도·응결 제어 조치]"]
    for key in sorted(CONTROL_KB):
        g = CONTROL_KB[key]
        lines.append(f"<{g['title']}>")
        for a in g["actions"]:
            lines.append(f"- {a.title} ({a.basis}) | 원리: {a.mechanism} | 효과: {a.effect} | 부작용: {a.side_effects} | "
                         f"실행: {a.how} | 확인: {a.verify}")
    lines.append("[제어 레버 실행 방법]")
    for k in sorted(LEVERS):
        lv = LEVERS[k]
        lines.append(f"- {lv['label']}({lv['unit']}): {lv['how']}")
    lines.append("[지식베이스 — 6가크롬 저감 조치]")
    for a in CR_ACTIONS:
        lines.append(f"- [{a.group}·{a.horizon}] {a.title} ({a.basis}) | 원리: {a.mechanism} | 효과: {a.effect} | "
                     f"부작용: {a.side_effects} | 실행: {a.how} | 확인: {a.verify}")
    lines.append("[기준]")
    lines.append("- KS L 5201 압축강도: 1종 3일 12.5·7일 22.5·28일 42.5 MPa 이상 / 3종 1일 10.0·3일 20.0·7일 32.5·28일 47.5 MPa 이상")
    lines.append("- KS L 5201: 응결 초결 60분 이상·종결 10시간 이하, SO₃ 1종 3.5%·3종 4.5% 이하, MgO 5.0% 이하, 강열감량 5.0% 이하")
    lines.append(f"- 6가크롬: {LIMIT_KR_TEXT} / {LIMIT_EU_TEXT} — 시험법이 달라 직접 비교 불가")
    lines.append("- 6가크롬 문헌: 클링커 Cr의 약 8~20%가 6가로 전환(Costeri 2016), 산소·알칼리가 주 영향 인자(Hills & Johansen 2007, PCA)")
    return "\n".join(lines)


def system_blocks() -> list[dict]:
    return [{"type": "text", "text": RULES + "\n" + knowledge_text(), "cache_control": {"type": "ephemeral"}}]


def _jsonable(o):
    try:
        import numpy as np
        import pandas as pd
    except ImportError:  # pragma: no cover
        return str(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d %H:%M")
    if isinstance(o, np.ndarray):
        return [_jsonable(v) for v in o.tolist()]
    if isinstance(o, pd.DataFrame):
        return json.loads(o.to_json(orient="records", force_ascii=False, date_format="iso", double_precision=4))
    return str(o)


def _round_floats(o):
    if isinstance(o, float):
        return round(o, 4) if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _round_floats(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round_floats(v) for v in o]
    return o


def context_json(context: dict) -> str:
    """정렬·반올림한 JSON(입력 해시·캐시 일관성)."""
    raw = json.loads(json.dumps(context, ensure_ascii=False, default=_jsonable))
    return json.dumps(_round_floats(raw), ensure_ascii=False, sort_keys=True, indent=1)


def user_message(kind: str, context: dict, question: str = "") -> str:
    title = KINDS.get(kind, kind)
    msg = (f"다음은 Blue365 QMS가 계산한 '{title}' 결과입니다. 시스템 지시의 규칙과 보고서 구성에 따라 보고서를 작성하세요.\n\n"
           f"```json\n{context_json(context)}\n```")
    if question.strip():
        msg += f"\n\n[담당자 추가 요청]\n{question.strip()}"
    return msg


# ── 호출 ────────────────────────────────────────────────────────────────
@dataclass
class LLMResult:
    ok: bool
    text: str
    model: str = ""
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    error: str | None = None
    fallback_used: bool = False


def estimate_cost(model: str, usage: dict) -> float:
    m = MODELS.get(model) or MODELS["claude-opus-5-5"]
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cw = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    return (inp * m["in"] + cw * m["in"] * 1.25 + cr * m["cache_read"] + out * m["out"]) / 1e6


def estimate_call_cost(model: str, input_tokens: int = 9000, output_tokens: int = 4000, cached: bool = True) -> float:
    """1회 호출 비용 추정(USD) — 기본: 입력 약 9천(지식베이스 캐시 6천 포함)·출력 약 4천 토큰 가정."""
    usage = {"input_tokens": input_tokens - (6000 if cached else 0), "output_tokens": output_tokens,
             "cache_read_input_tokens": 6000 if cached else 0}
    return estimate_cost(model, usage)


def _usage_dict(u) -> dict:
    if u is None:
        return {}
    out = {}
    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        v = getattr(u, k, None)
        out[k] = int(v) if isinstance(v, (int, float)) else 0
    return out


def _log(entry: dict, path: Path = AI_LOG_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_log(path: Path = AI_LOG_PATH, limit: int = 200) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _error_text(exc: Exception) -> str:
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return f"오류: {exc}"
    if isinstance(exc, anthropic.AuthenticationError):
        return "API 키가 올바르지 않습니다(인증 실패). ⚙️ 기준·알림 설정 → AI(LLM) 탭의 키 설정 방법을 확인하세요."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "API 키에 이 모델을 사용할 권한이 없습니다."
    if isinstance(exc, anthropic.NotFoundError):
        return "모델 또는 API 주소를 찾을 수 없습니다(모델명·게이트웨이 주소 확인)."
    if isinstance(exc, anthropic.RateLimitError):
        return "요청 한도를 초과했습니다. 잠시 후 다시 시도하세요."
    if isinstance(exc, anthropic.BadRequestError):
        return f"요청 형식 오류: {getattr(exc, 'message', exc)}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "API 서버에 연결할 수 없습니다(사내 방화벽·프록시·네트워크 확인)."
    if isinstance(exc, anthropic.APIStatusError):
        return f"API 오류({exc.status_code}): {getattr(exc, 'message', exc)}"
    return f"오류: {exc}"


class ReportStream:
    """스트리밍 보고서 생성기. for chunk in ReportStream(...) 으로 텍스트를 받고, 끝나면 .result 를 확인한다.

    client 를 주입하면(테스트용 가짜 클라이언트 등) 그 객체의 .messages.stream / .beta.messages.stream 을 사용한다.
    """

    def __init__(self, kind: str, context: dict, cfg: LLMConfig | None = None, client=None, question: str = "",
                 log_path: Path = AI_LOG_PATH):
        self.kind = kind
        self.context = context
        self.cfg = cfg or load_llm_config()
        self.client = client
        self.question = question
        self.log_path = log_path
        self.result: LLMResult | None = None

    def _request(self, with_fallback: bool) -> dict:
        cfg = self.cfg
        req: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": int(cfg.max_tokens),
            "system": system_blocks(),
            "messages": [{"role": "user", "content": user_message(self.kind, self.context, self.question)}],
            "output_config": {"effort": cfg.effort},
        }
        if with_fallback:
            req["betas"] = [FALLBACK_BETA]
            req["fallbacks"] = "default"
        return req

    def __iter__(self) -> Iterator[str]:
        cfg = self.cfg
        started = datetime.now()
        parts: list[str] = []
        use_fb = bool(cfg.use_fallbacks and MODELS.get(cfg.model, {}).get("fallback", False))
        ctx_hash = hashlib.sha256(context_json(self.context).encode("utf-8")).hexdigest()[:16]
        final = None
        error: str | None = None
        try:
            client = self.client or make_client(cfg)
            attempts = [use_fb, False] if use_fb else [False]
            for i, fb in enumerate(attempts):
                try:
                    req = self._request(fb)
                    api = client.beta.messages if fb else client.messages
                    with api.stream(**req) as stream:
                        for text in stream.text_stream:
                            parts.append(text)
                            yield text
                        final = stream.get_final_message()
                    break
                except Exception as exc:  # noqa: BLE001 - 대체 모델 매개변수 거부 시 1회 재시도
                    msg = str(getattr(exc, "message", exc)).lower()
                    if fb and not parts and i == 0 and "fallback" in msg:
                        continue
                    raise
        except Exception as exc:  # noqa: BLE001 - 사용자에게 원인 표시
            error = _error_text(exc)
            yield f"\n\n⚠️ {error}"
        text = "".join(parts)
        stop = getattr(final, "stop_reason", None) if final is not None else None
        usage = _usage_dict(getattr(final, "usage", None)) if final is not None else {}
        served = str(getattr(final, "model", "") or cfg.model) if final is not None else cfg.model
        fb_used = final is not None and not served.startswith(cfg.model)
        ok = error is None and stop not in ("refusal",)
        if stop == "refusal":
            notice = ("\n\n⚠️ AI가 이 요청에 응답하지 않았습니다(안전 정책에 따른 응답 거부). 위 일부 출력은 사용하지 마시고 "
                      "규칙 기반 솔루션을 참고하세요.")
            text = ""
            yield notice
        elif stop == "max_tokens":
            yield "\n\n⚠️ 최대 출력 길이에 도달해 보고서가 중간에 끝났습니다(설정에서 최대 토큰을 늘리세요)."
        cost = estimate_cost(served if served in MODELS else cfg.model, usage)
        self.result = LLMResult(ok and bool(text), text, served, stop, usage, cost, error, fb_used)
        _log({"ts": started.strftime("%Y-%m-%d %H:%M:%S"), "kind": self.kind, "model": cfg.model, "served_model": served,
              "effort": cfg.effort, "stop_reason": stop, "usage": usage, "cost_usd": round(cost, 5), "error": error,
              "context_sha256": ctx_hash, "question": self.question[:500], "response": text},
             self.log_path)


def generate(kind: str, context: dict, cfg: LLMConfig | None = None, client=None, question: str = "",
             log_path: Path = AI_LOG_PATH) -> LLMResult:
    """스트리밍 없이 결과만 필요할 때(내부적으로는 스트리밍 사용)."""
    rs = ReportStream(kind, context, cfg, client, question, log_path)
    for _ in rs:
        pass
    return rs.result or LLMResult(False, "", error="결과 없음")


def ai_ready(cfg: LLMConfig | None = None) -> tuple[bool, str]:
    cfg = cfg or load_llm_config()
    if not cfg.enabled:
        return False, "AI 해설 기능이 꺼져 있습니다(⚙️ 기준·알림 설정 → AI(LLM) 탭에서 켤 수 있습니다)."
    if not sdk_available():
        return False, "anthropic 패키지가 설치되어 있지 않습니다(pip install anthropic)."
    ok, src = credential_status()
    if not ok:
        return False, "API 키가 없습니다. 환경변수 ANTHROPIC_API_KEY 또는 .streamlit/secrets.toml [anthropic] api_key 를 설정하세요."
    return True, f"사용 가능 — 모델 {cfg.model}, 키 출처: {src}"
