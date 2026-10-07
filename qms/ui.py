"""Streamlit 화면 공통 요소: 데이터 로딩(캐시), 사이드바, 차트, 표시 형식."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .alerts import SEVERITY_ICON, SEVERITY_ORDER, AlertEvent, detect_events, events_frame
from .demo import generate_demo_data
from .prediction import FittedModel, attach_predictions
from .spc import baseline_stats, rule_flags
from .standards import SETTINGS_PATH, TABLES, USER_STANDARDS_PATH, ItemSpec, SpecRegistry, load_registry, load_settings
from .store import DB_PATH, DataStore, db_mtime, load_alert_status, load_store, save_raw

DEMO_FLAG = DB_PATH.parent / ".demo"


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


def init_demo_if_empty() -> None:
    if not DB_PATH.exists():
        save_raw(generate_demo_data(), replace=True)
        DEMO_FLAG.parent.mkdir(parents=True, exist_ok=True)
        DEMO_FLAG.write_text("demo", encoding="utf-8")


def get_ctx() -> Ctx:
    init_demo_if_empty()
    return _load(db_mtime(), _mtime(USER_STANDARDS_PATH), _mtime(SETTINGS_PATH), DEMO_FLAG.exists())


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
                "violation": "#d03b3b", "event": "rgba(236,131,90,0.16)", "event_ks": "rgba(208,59,59,0.18)"}
    return {"series": "#2a78d6", "pred": "#6da7ec", "band": "rgba(42,120,214,0.14)", "ks": "#d03b3b",
            "spec": "#ec835a", "target": "#0ca30c", "cl": "#898781", "zone": "#e1e0d9", "muted": "#52514e",
            "violation": "#d03b3b", "event": "rgba(236,131,90,0.14)", "event_ks": "rgba(208,59,59,0.14)"}


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
    for v, label, col, dash in ((lim.ks_max, "KS 상한", c["ks"], "solid"), (lim.ks_min, "KS 하한", c["ks"], "solid"),
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
    for v, label, col, dash in ((lim.ks_max, "KS 상한", c["ks"], "solid"), (lim.ks_min, "KS 하한", c["ks"], "solid"),
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


# ── 사이드바 ────────────────────────────────────────────────────────────
def sidebar(ctx: Ctx) -> None:
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


def recent_events(ctx: Ctx, days: int = 7, min_sev: str = "주의") -> list[AlertEvent]:
    period = ctx.store.period()
    if not period:
        return []
    since = period[1] - pd.Timedelta(days=days)
    return [e for e in ctx.events if e.end >= since and SEVERITY_ORDER[e.severity] >= SEVERITY_ORDER[min_sev]]


def open_diagnosis(event_id: str) -> None:
    st.session_state["selected_event_id"] = event_id
    st.switch_page("app_pages/diagnosis.py")
