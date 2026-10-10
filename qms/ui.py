"""Streamlit 화면 공통 요소: 데이터 로딩(캐시), 사이드바, 차트, 표시 형식."""

from __future__ import annotations

import functools
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .alerts import (
    SEVERITY_ICON,
    SEVERITY_ORDER,
    AlertEvent,
    detect_events,
    events_frame,
)
from . import share
from .demo import generate_demo_data
from .prediction import FittedModel, attach_predictions
from .rawmix import FcaoModel, XrdMap, fit_fcao_model, fit_xrd_map
from .spc import baseline_stats, rule_flags
from .standards import (
    PRODUCTS,
    SETTINGS_PATH,
    TABLES,
    USER_STANDARDS_PATH,
    ItemSpec,
    SpecRegistry,
    load_registry,
    load_settings,
)
from .store import DB_PATH, DataStore, clear_db, db_mtime, load_alert_status, load_store, save_raw
from .strength import TARGETS, StrengthModels, fit_strength_models

DEMO_FLAG = DB_PATH.parent / ".demo"
_TILDE = re.compile(r"(?<!\\)~")


def md_escape(text):
    """한국어 범위 표기 '~'(예: 8~20%)가 마크다운 취소선으로 해석되지 않도록 이스케이프."""
    return _TILDE.sub(r"\\~", text) if isinstance(text, str) and "~" in text else text


def enable_tilde_escape() -> None:
    """st.markdown·caption·info·warning·success·error 출력 시 '~'를 자동 이스케이프(앱 시작 시 1회 호출).

    Streamlit 마크다운(GFM)은 '~텍스트~'를 취소선으로 렌더링하므로, '0.3~0.5 MPa … 1~2일'처럼 한 문단에 범위 표기가
    두 번 나오면 사이 글자가 지워진 것처럼 보이는 문제를 막는다.
    """
    from streamlit.delta_generator import DeltaGenerator

    if getattr(DeltaGenerator, "_qms_tilde_patched", False):
        return
    for name in ("markdown", "caption", "info", "warning", "success", "error"):
        orig = getattr(DeltaGenerator, name)

        def wrapper(self, body, *args, _orig=orig, **kwargs):
            return _orig(self, md_escape(body), *args, **kwargs)

        functools.update_wrapper(wrapper, orig)
        setattr(DeltaGenerator, name, wrapper)
        main = getattr(st, "_main", None)
        if main is not None:
            setattr(st, name, getattr(main, name))       # st.markdown 등은 import 시 묶인 메서드라 다시 연결
    DeltaGenerator._qms_tilde_patched = True


# ── 태블릿·좁은 화면 대응 ──────────────────────────────────────────────────
TABLET_UA = re.compile(r"iPad|iPhone|Android|Mobile|Tablet", re.IGNORECASE)
_METRIC_ROW = ('[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"]'
               ' > [data-testid="stElementContainer"] > [data-testid="stMetric"])')
RESPONSIVE_CSS = f"""<style>
/* 한글은 단어 중간에서 줄을 바꾸지 않음(예: '대시보/드' 방지) */
[data-testid="stMarkdownContainer"], [data-testid="stHeading"], [data-testid="stMetricLabel"] {{
  word-break: keep-all; overflow-wrap: break-word; }}
/* 본문 폭 기준(container query) — 사이드바를 펼친 태블릿처럼 본문이 좁을 때만 적용, 넓은 PC 화면은 그대로 */
[data-testid="stMainBlockContainer"] {{ container-type: inline-size; container-name: qms-main; }}
{_METRIC_ROW} > [data-testid="stColumn"] {{ container-type: inline-size; container-name: qms-metric; }}
/* 숫자 카드가 좁으면 잘림(…) 대신 줄바꿈, 더 좁으면 글자 크기도 줄임(넓은 PC 화면은 변화 없음) */
@container qms-metric (max-width: 200px) {{
  [data-testid="stMetricValue"] div, [data-testid="stMetricLabel"] div, [data-testid="stMetricLabel"] p,
  [data-testid="stMetricDelta"] div, [data-testid="stMetricDelta"] p {{
    white-space: normal; overflow: visible; text-overflow: clip; }}
}}
@container qms-metric (max-width: 160px) {{ [data-testid="stMetricValue"] {{ font-size: 1.5rem; }} }}
/* 태블릿·소형 노트북: 본문 좌우 여백을 줄여 내용 폭 확보 */
@media (min-width: 641px) and (max-width: 1280px) {{
  [data-testid="stMainBlockContainer"] {{ padding-left: 1.5rem !important; padding-right: 1.5rem !important; }}
}}
/* 숫자 카드 줄: 같은 폭의 바둑판 배치(5개 → 넓으면 한 줄, 좁으면 4+1·3+2) */
@container qms-main (max-width: 960px) {{
  {_METRIC_ROW} {{ display: grid !important; grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr)); gap: 0.75rem 1rem; }}
  {_METRIC_ROW} > [data-testid="stColumn"] {{ width: auto !important; min-width: 0 !important; max-width: none !important; }}
}}
/* 세로 태블릿 등: 여러 칸 배치는 줄바꿈(한 칸 최소 14rem), 그래프는 한 줄에 하나 */
@container qms-main (max-width: 720px) {{
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; row-gap: 0.75rem; }}
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{ flex: 1 1 14rem !important; min-width: min(100%, 14rem) !important; }}
  [data-testid="stHorizontalBlock"]:has([data-testid="stPlotlyChart"]) > [data-testid="stColumn"] {{ flex-basis: 100% !important; }}
  h1 {{ font-size: 1.9rem !important; }}
}}
</style>"""


def apply_responsive_css() -> None:
    """태블릿·좁은 창에서 숫자 카드가 잘리거나 그래프가 비좁게 붙지 않도록 화면 서식을 보정(매 실행 시 호출)."""
    st.html(RESPONSIVE_CSS)


def tablet_mode() -> bool:
    """태블릿 보기 여부 — 주소에 ?view=tablet(태블릿 접속 QR)이 있거나 모바일 브라우저면 처음에 자동으로 켠다.

    iPad Safari 는 PC(Mac)처럼 자신을 알리므로 자동 판별이 안 될 수 있어, QR 주소와 사이드바 스위치를 함께 둔다.
    """
    ss = st.session_state
    if "qms_tablet" not in ss:
        try:
            ua = st.context.headers.get("User-Agent", "") or ""
        except Exception:  # noqa: BLE001 - 헤더를 못 읽는 환경(자동 시험 등)은 PC로 본다
            ua = ""
        ss["qms_tablet"] = st.query_params.get("view") == "tablet" or bool(TABLET_UA.search(ua))
    return bool(ss["qms_tablet"])


def enable_touch_charts() -> None:
    """태블릿 보기일 때 그래프의 '끌어서 확대'를 끈다(앱 시작 시 1회 호출).

    Plotly 기본값은 손가락으로 끌면 확대하므로, 그래프가 화면을 채운 페이지에서는 태블릿으로 스크롤이 되지 않는다.
    dragmode=False 이면 그래프 위에서도 화면이 스크롤되고, 값은 탭해서 확인할 수 있다. PC 화면은 그대로 둔다.
    """
    from streamlit.delta_generator import DeltaGenerator

    if getattr(DeltaGenerator, "_qms_touch_patched", False):
        return
    orig = DeltaGenerator.plotly_chart

    def wrapper(self, figure_or_data, *args, _orig=orig, **kwargs):
        if isinstance(figure_or_data, go.Figure) and tablet_mode():
            figure_or_data.update_layout(dragmode=False)      # 그림은 실행마다 새로 만들므로(캐시 안 함) 직접 수정
            kwargs["config"] = {**(kwargs.get("config") or {}), "displayModeBar": False}
        return _orig(self, figure_or_data, *args, **kwargs)

    functools.update_wrapper(wrapper, orig)
    DeltaGenerator.plotly_chart = wrapper
    main = getattr(st, "_main", None)
    if main is not None:
        st.plotly_chart = main.plotly_chart
    DeltaGenerator._qms_touch_patched = True


def tablet_access_panel() -> None:
    """다른 기기(태블릿·휴대폰)에서 접속할 주소와 QR 코드."""
    address = st.get_option("server.address") or ""
    port = int(st.get_option("server.port") or 8501)
    if not share.is_shared(address):
        st.markdown("지금은 **이 PC에서만** 볼 수 있게 실행 중입니다.\n\n"
                    "태블릿에서 보려면 실행 창을 닫고 **3_RUN_SHARE.bat**으로 다시 실행하세요"
                    "(공유 PC에서 처음 1회 4_FIREWALL_ADMIN.bat).")
        return
    urls = share.share_urls(port, address)
    if not urls:
        st.warning("이 PC의 사내 IP를 찾지 못했습니다. 명령 프롬프트에서 ipconfig 로 IPv4 주소를 확인하세요.")
        return
    url = urls[0] + share.TABLET_QUERY
    png = share.qr_png(url)
    st.caption("태블릿 카메라로 QR 코드를 비추면 바로 열립니다(태블릿 보기 자동 켜짐).")
    if png:
        st.image(png, width=180)
    st.code(url, language=None)
    for other in urls[1:]:
        st.caption(f"다른 주소: {other}")
    st.caption("자주 보려면 Safari 공유 버튼 또는 Chrome 메뉴(⋮)에서 '홈 화면에 추가'를 누르세요.")
    st.caption("열리지 않으면 태블릿이 사내망(업무망) Wi-Fi에 연결돼 있는지, 공유 PC의 방화벽이 허용돼 있는지 확인하세요.")


@dataclass
class Ctx:
    store: DataStore
    registry: SpecRegistry
    settings: dict
    models: dict[str, dict[str, FittedModel]]
    events: list[AlertEvent]
    demo: bool

    def event(self, event_id: str | None) -> AlertEvent | None:
        return next((e for e in self.events if e.event_id == event_id), None)

    def events_df(self) -> pd.DataFrame:
        return events_frame(self.events, load_alert_status())


def _mtime(path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


@st.cache_resource(show_spinner="데이터를 불러와 분석하는 중…", max_entries=3)
def _load(db_m: float, std_m: float, set_m: float, demo: bool) -> Ctx:
    store = load_store()
    registry = load_registry()
    settings = load_settings()
    models = attach_predictions(store, registry)
    events = detect_events(store, registry, settings)
    return Ctx(store, registry, settings, models, events, demo)


def _demo_outdated() -> bool:
    """이전 버전 데모 DB(XRD·크롬 테이블 없음)이면 True — 데모 데이터만 자동 갱신 대상."""
    if not (DB_PATH.exists() and DEMO_FLAG.exists()):
        return False
    try:
        with closing(sqlite3.connect(DB_PATH)) as con:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return False
    return "xrd" not in names


def init_demo_if_empty() -> None:
    if not DB_PATH.exists() or _demo_outdated():
        clear_db()
        save_raw(generate_demo_data(), replace=True)
        DEMO_FLAG.parent.mkdir(parents=True, exist_ok=True)
        DEMO_FLAG.write_text("demo", encoding="utf-8")


def get_ctx() -> Ctx:
    init_demo_if_empty()
    return _load(db_mtime(), _mtime(USER_STANDARDS_PATH), _mtime(SETTINGS_PATH), DEMO_FLAG.exists())


@dataclass
class DesignModels:
    fcao: FcaoModel
    xrd: XrdMap
    strength: dict[str, StrengthModels]


@st.cache_resource(show_spinner="배합·강도 예측 모델을 학습하는 중…", max_entries=3)
def _design(db_m: float, std_m: float, set_m: float, demo: bool) -> DesignModels:
    ctx = _load(db_m, std_m, set_m, demo)
    xm = fit_xrd_map(ctx.store)
    return DesignModels(fit_fcao_model(ctx.store), xm,
                        {p: fit_strength_models(ctx.store, ctx.registry, p, xm) for p in PRODUCTS})


def get_design() -> DesignModels:
    init_demo_if_empty()
    return _design(db_mtime(), _mtime(USER_STANDARDS_PATH), _mtime(SETTINGS_PATH), DEMO_FLAG.exists())


def refresh() -> None:
    st.cache_resource.clear()


# ── 색상(dataviz 기준 팔레트: 계열=파랑, 임계선=상태색) ─────────────────
def colors() -> dict:
    dark = False
    try:
        dark = getattr(st.context.theme, "type", "light") == "dark"
    except Exception:  # noqa: BLE001 - 테마 정보가 없는 실행 환경
        dark = False
    if dark:
        return {"series": "#3987e5", "pred": "#86b6ef", "band": "rgba(57,135,229,0.18)", "ks": "#d03b3b",
                "spec": "#ec835a", "target": "#0ca30c", "cl": "#898781", "zone": "#2c2c2a", "muted": "#c3c2b7",
                "violation": "#d03b3b", "event": "rgba(236,131,90,0.16)", "event_ks": "rgba(208,59,59,0.18)",
                "pos": "#3987e5", "neg": "#ec835a"}
    return {"series": "#2a78d6", "pred": "#6da7ec", "band": "rgba(42,120,214,0.14)", "ks": "#d03b3b",
            "spec": "#ec835a", "target": "#0ca30c", "cl": "#898781", "zone": "#e1e0d9", "muted": "#52514e",
            "violation": "#d03b3b", "event": "rgba(236,131,90,0.14)", "event_ks": "rgba(208,59,59,0.14)",
            "pos": "#2a78d6", "neg": "#eb6834"}


def fmt(v, nd: int = 2, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return f"{v:,.{nd}f}{(' ' + unit) if unit else ''}"


def sev_label(sev: str) -> str:
    return f"{SEVERITY_ICON.get(sev, '')} {sev}"


def item_options(registry: SpecRegistry, stage: str | None = None, only_with_limits: bool = False) -> list[str]:
    out = []
    for it in registry.all():
        if stage and it.stage != stage:
            continue
        if only_with_limits and not (it.limits or it.rules):
            continue
        out.append(it.key)
    return out


def item_label(registry: SpecRegistry, key: str) -> str:
    it = registry[key]
    return f"{it.name}" + (f" ({it.unit})" if it.unit else "")


# ── 차트 ───────────────────────────────────────────────────────────────
def _base_layout(fig: go.Figure, title: str | None, height: int, unit: str = ""):
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=15)) if title else None,
        height=height, margin=dict(l=10, r=10, t=42 if title else 12, b=10), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        yaxis=dict(title=unit or None, showgrid=True, zeroline=False),
        xaxis=dict(showgrid=False),
    )


def add_limit_lines(fig: go.Figure, item: ItemSpec, product: str | None, show_target: bool = True):
    c = colors()
    lim = item.limits_for(product)
    kl = item.ks_label
    for v, label, col, dash in ((lim.ks_max, f"{kl} 상한", c["ks"], "solid"), (lim.ks_min, f"{kl} 하한", c["ks"], "solid"),
                                (lim.usl, "사내 상한", c["spec"], "dash"), (lim.lsl, "사내 하한", c["spec"], "dash")):
        if v is not None:
            fig.add_hline(y=v, line=dict(color=col, width=1.5, dash=dash),
                          annotation_text=f"{label} {v:g}", annotation_position="top left",
                          annotation_font=dict(size=11, color=c["muted"]))
    if show_target and lim.target is not None:
        fig.add_hline(y=lim.target, line=dict(color=c["target"], width=1, dash="dot"),
                      annotation_text=f"목표 {lim.target:g}", annotation_position="bottom left",
                      annotation_font=dict(size=11, color=c["muted"]))


def add_event_shading(fig: go.Figure, events: list[AlertEvent], start=None, end=None):
    c = colors()
    for e in events:
        if e.severity == "주의":
            continue
        x0, x1 = e.start, e.end
        if x0 == x1:
            x0, x1 = x0 - pd.Timedelta(hours=1), x1 + pd.Timedelta(hours=1)
        if start is not None and x1 < pd.Timestamp(start):
            continue
        if end is not None and x0 > pd.Timestamp(end):
            continue
        fig.add_vrect(x0=x0, x1=x1, fillcolor=c["event_ks"] if e.severity == "위험" else c["event"], line_width=0,
                      layer="below")


def trend_figure(ctx: Ctx, key: str, product: str | None, start=None, end=None, resample: str | None = None,
                 title: str | None = None, height: int = 320, show_events: bool = True,
                 show_target: bool = True) -> go.Figure | None:
    reg = ctx.registry
    item = reg[key]
    s = ctx.store.series(key, reg, product, start, end)
    if len(s) == 0:
        return None
    if resample:
        s = s.resample(resample).mean().dropna()
    c = colors()
    fig = go.Figure()
    daily = TABLES[item.table].get("spc_resample") is None
    fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers" if (daily or len(s) < 120) else "lines",
                             name=item.name, line=dict(color=c["series"], width=2), marker=dict(size=8 if daily else 5),
                             hovertemplate=f"%{{y:,.{item.decimals}f}} {item.unit}<extra>{item.name}</extra>"))
    if key == "phy_s28":
        p = ctx.store.series("pred_s28", reg, product, start, end)
        if len(p):
            fig.add_trace(go.Scatter(x=p.index, y=p.values, mode="lines+markers", name="예측(미도래)",
                                     line=dict(color=c["pred"], width=2, dash="dash"), marker=dict(size=8),
                                     hovertemplate="%{y:.1f} MPa<extra>예측</extra>"))
    add_limit_lines(fig, item, product, show_target)
    if show_events:
        evs = [e for e in ctx.events if e.item_key == key and e.product == product]
        add_event_shading(fig, evs, start, end)
    _base_layout(fig, title, height, item.unit)
    fig.update_layout(showlegend=key == "phy_s28")
    return fig


def spc_figure(series: pd.Series, item: ItemSpec, product: str | None, settings: dict, show_spec: bool = True,
               height: int = 380) -> tuple[go.Figure, go.Figure, dict]:
    """I 관리도 + MR 관리도. 반환: (I fig, MR fig, 정보 dict)."""
    c = colors()
    stats = baseline_stats(series, settings)
    rules = [r for r in item.rules if r in settings.get("enabled_rules", [])] or ["R1"]
    x = series.to_numpy(float)
    flags = rule_flags(x, stats, rules, settings.get("run_length", 9), settings.get("trend_length", 6)) if stats else {}
    any_flag = np.zeros(len(x), bool)
    for f in flags.values():
        any_flag |= f
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=x, mode="lines+markers", name=item.name,
                             line=dict(color=c["series"], width=1.5), marker=dict(size=6, color=c["series"]),
                             hovertemplate=f"%{{y:,.{item.decimals}f}} {item.unit}<extra></extra>"))
    if any_flag.any():
        fig.add_trace(go.Scatter(x=series.index[any_flag], y=x[any_flag], mode="markers", name="판정규칙 위반",
                                 marker=dict(size=10, color=c["violation"], symbol="diamond",
                                             line=dict(width=2, color="white")),
                                 hovertemplate="위반 %{y:,.2f}<extra></extra>"))
    if stats:
        for k, dash, label in ((0, "solid", "CL"), (3, "dash", "UCL"), (-3, "dash", "LCL")):
            v = stats.center + k * stats.sigma
            fig.add_hline(y=v, line=dict(color=c["cl"], width=1.25, dash=dash),
                          annotation_text=f"{label} {v:,.{item.decimals}f}", annotation_position="top right",
                          annotation_font=dict(size=11, color=c["muted"]))
        for k in (1, 2):
            for sgn in (1, -1):
                fig.add_hline(y=stats.center + sgn * k * stats.sigma, line=dict(color=c["zone"], width=1))
        fig.add_vrect(x0=stats.base_start, x1=stats.base_end, fillcolor="rgba(137,135,129,0.08)", line_width=0,
                      layer="below", annotation_text="기준기간", annotation_position="top left",
                      annotation_font=dict(size=11, color=c["muted"]))
    if show_spec:
        add_limit_lines(fig, item, product, show_target=False)
    _base_layout(fig, "I 관리도(개별값)", height, item.unit)

    mr = np.abs(np.diff(x)) if len(x) > 1 else np.array([])
    fig2 = go.Figure()
    if len(mr):
        fig2.add_trace(go.Scatter(x=series.index[1:], y=mr, mode="lines+markers", name="MR",
                                  line=dict(color=c["series"], width=1.5), marker=dict(size=5),
                                  hovertemplate="%{y:,.3f}<extra>MR</extra>"))
        mrbar = float(np.mean(mr))
        fig2.add_hline(y=mrbar, line=dict(color=c["cl"], width=1.25), annotation_text=f"MR̄ {mrbar:,.3f}",
                       annotation_position="top right", annotation_font=dict(size=11, color=c["muted"]))
        fig2.add_hline(y=3.267 * mrbar, line=dict(color=c["cl"], width=1.25, dash="dash"),
                       annotation_text=f"UCL {3.267 * mrbar:,.3f}", annotation_position="top right",
                       annotation_font=dict(size=11, color=c["muted"]))
    _base_layout(fig2, "MR 관리도(이동범위)", 220)
    fig.update_layout(showlegend=bool(any_flag.any()))
    fig2.update_layout(showlegend=False)
    info = {"stats": stats, "flags": flags, "rules": rules}
    return fig, fig2, info


def histogram_figure(series: pd.Series, item: ItemSpec, product: str | None, height: int = 320) -> go.Figure:
    c = colors()
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=series.values, nbinsx=30, marker=dict(color=c["series"], line=dict(width=2, color="white")),
                               name=item.name, hovertemplate="%{x}<br>%{y}건<extra></extra>"))
    lim = item.limits_for(product)
    kl = item.ks_label
    for v, label, col, dash in ((lim.ks_max, f"{kl} 상한", c["ks"], "solid"), (lim.ks_min, f"{kl} 하한", c["ks"], "solid"),
                                (lim.usl, "사내 상한", c["spec"], "dash"), (lim.lsl, "사내 하한", c["spec"], "dash"),
                                (lim.target, "목표", c["target"], "dot")):
        if v is not None:
            fig.add_vline(x=v, line=dict(color=col, width=1.5, dash=dash), annotation_text=f"{label} {v:g}",
                          annotation_position="top", annotation_font=dict(size=11, color=c["muted"]))
    _base_layout(fig, "분포(히스토그램)", height)
    fig.update_layout(showlegend=False, hovermode="closest", bargap=0.05)
    fig.update_xaxes(title=item.unit or None)
    fig.update_yaxes(title="빈도")
    return fig


def signed_bar_figure(labels: list[str], values: list[float], unit: str, height: int = 300,
                      title: str | None = None) -> go.Figure:
    """가로 막대(양수 = 파랑, 음수 = 주황). 기여도·민감도 표시용."""
    c = colors()
    order = np.argsort(np.abs(np.asarray(values, float)))
    lab = [labels[i] for i in order]
    val = [float(values[i]) for i in order]
    fig = go.Figure(go.Bar(x=val, y=lab, orientation="h", marker=dict(color=[c["pos"] if v >= 0 else c["neg"] for v in val]),
                           text=[f"{v:+.2f}" for v in val], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x:+.2f} " + unit + "<extra></extra>"))
    _base_layout(fig, title, height)
    fig.update_layout(showlegend=False, hovermode="closest", margin=dict(l=10, r=40, t=42 if title else 12, b=10))
    fig.update_xaxes(title=unit, zeroline=True, zerolinecolor=c["cl"], showgrid=True)
    fig.update_yaxes(showgrid=False)
    return fig


def single_bar_figure(labels: list[str], values: list[float], unit: str, height: int = 300, title: str | None = None,
                      fmt_str: str = "{:.1f}") -> go.Figure:
    """단일 계열 가로 막대(파랑 한 색) — 비율·파레토 표시용(값이 큰 항목이 위)."""
    c = colors()
    lab, val = list(labels)[::-1], [float(v) for v in values][::-1]
    fig = go.Figure(go.Bar(x=val, y=lab, orientation="h", marker=dict(color=c["series"]),
                           text=[fmt_str.format(v) for v in val], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x:.2f} " + unit + "<extra></extra>"))
    _base_layout(fig, title, height)
    fig.update_layout(showlegend=False, hovermode="closest", margin=dict(l=10, r=40, t=42 if title else 12, b=10))
    fig.update_xaxes(title=unit, showgrid=True)
    fig.update_yaxes(showgrid=False)
    return fig


def tornado_figure(df: pd.DataFrame, base: float, unit: str, height: int = 360) -> go.Figure:
    """민감도(토네이도): 입력을 낮췄을 때(주황)·높였을 때(파랑) 결과."""
    c = colors()
    fig = go.Figure()
    fig.add_trace(go.Bar(y=df["입력"], x=df["낮음"] - base, base=base, orientation="h", name="입력 −",
                         marker=dict(color=c["neg"]), hovertemplate="%{y}<br>입력 감소 시 %{x:+.2f}<extra></extra>"))
    fig.add_trace(go.Bar(y=df["입력"], x=df["높음"] - base, base=base, orientation="h", name="입력 +",
                         marker=dict(color=c["pos"]), hovertemplate="%{y}<br>입력 증가 시 %{x:+.2f}<extra></extra>"))
    fig.add_vline(x=base, line=dict(color=c["cl"], width=1.25, dash="dash"), annotation_text=f"기준 {base:.2f}",
                  annotation_position="top", annotation_font=dict(size=11, color=c["muted"]))
    _base_layout(fig, None, height)
    fig.update_layout(barmode="overlay", hovermode="closest")
    fig.update_xaxes(title=unit)
    return fig


def strength_curve_figure(pred: pd.DataFrame, registry: SpecRegistry, product: str, height: int = 360) -> go.Figure:
    """재령별 강도 예측(점·95% 구간) + KS·사내 하한."""
    c = colors()
    rows = pred[pred["target"].isin([t for t, v in TARGETS.items() if v["age"]])].copy()
    rows["age"] = rows["target"].map(lambda t: TARGETS[t]["age"])
    rows = rows.sort_values("age")
    fig = go.Figure()
    if len(rows):
        x = rows["age"].astype(str) + "일"
        fig.add_trace(go.Scatter(x=list(x) + list(x[::-1]), y=list(rows["상한(95%)"]) + list(rows["하한(95%)"][::-1]),
                                 fill="toself", fillcolor=c["band"], line=dict(width=0), name="예측구간(95%)",
                                 mode="lines", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=rows["예측"], mode="lines+markers+text", name="예측",
                                 line=dict(color=c["series"], width=2), marker=dict(size=9),
                                 text=[f"{v:.1f}" for v in rows["예측"]], textposition="middle left",
                                 hovertemplate="%{x}: %{y:.1f} MPa<extra>예측</extra>"))
        ks, spec = [], []
        for t in rows["target"]:
            lim = registry[t].limits_for(product) if t in registry else None
            ks.append(lim.ks_min if lim else None)
            spec.append(lim.lsl if lim else None)
        if any(v is not None for v in ks):
            fig.add_trace(go.Scatter(x=x, y=ks, mode="markers+lines", name="KS 하한", line=dict(color=c["ks"], width=1.5),
                                     marker=dict(symbol="line-ew-open", size=14), connectgaps=False))
        if any(v is not None for v in spec):
            fig.add_trace(go.Scatter(x=x, y=spec, mode="markers+lines", name="사내 하한",
                                     line=dict(color=c["spec"], width=1.5, dash="dash"),
                                     marker=dict(symbol="line-ew-open", size=14), connectgaps=False))
    _base_layout(fig, None, height, "MPa")
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title="재령")
    return fig


# ── 사이드바 ────────────────────────────────────────────────────────────
def sidebar(ctx: Ctx) -> None:
    tablet_mode()                                     # 스위치를 만들기 전에 자동 판별값을 정해 둔다
    with st.sidebar:
        period = ctx.store.period()
        if period:
            st.caption(f"데이터 기간  \n{period[0]:%Y-%m-%d} ~ {period[1]:%Y-%m-%d %H:%M}")
        if ctx.demo:
            st.warning("데모 데이터 사용 중", icon="🧪")
        recent = [e for e in ctx.events if period and e.end >= period[1] - pd.Timedelta(days=7)]
        counts = {k: sum(e.severity == k for e in recent) for k in ("위험", "경고", "주의")}
        st.caption("최근 7일 알림")
        st.markdown(" · ".join(f"{SEVERITY_ICON[k]} {k} **{v}**" for k, v in counts.items()))
        if st.button("🔄 새로고침", width="stretch", help="데이터·기준을 다시 불러와 재분석합니다."):
            refresh()
            st.rerun()
        st.toggle("📱 태블릿 보기", key="qms_tablet",
                  help="그래프 위를 손가락으로 쓸어도 화면이 스크롤되도록 그래프의 '끌어서 확대'를 끕니다(값은 탭해서 확인). "
                       "태블릿·휴대폰 브라우저나 QR 주소로 접속하면 자동으로 켜집니다.")
        with st.popover("📲 태블릿·휴대폰으로 보기", width="stretch"):
            tablet_access_panel()


def recent_events(ctx: Ctx, days: int = 7, min_sev: str = "주의") -> list[AlertEvent]:
    period = ctx.store.period()
    if not period:
        return []
    since = period[1] - pd.Timedelta(days=days)
    return [e for e in ctx.events if e.end >= since and SEVERITY_ORDER[e.severity] >= SEVERITY_ORDER[min_sev]]


def open_diagnosis(event_id: str) -> None:
    st.session_state["selected_event_id"] = event_id
    st.switch_page("app_pages/diagnosis.py")
