"""그래프 보기(항목 자유 선택): 시계열 집계·이동평균·기준선과 저장된 보기(data/chart_views.json)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .standards import DATA_DIR

VIEWS_PATH = DATA_DIR / "chart_views.json"
# 범주 색(고정 순서, 검증된 기본 팔레트 — 순서를 돌려 쓰지 않음. 8개를 넘으면 항목별 그래프로 나눠 본다)
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
AGGS = {"원자료": None, "일 평균": "1D", "주 평균": "W-MON", "월 평균": "MS"}
PERIODS = {"최근 30일": 30, "최근 90일": 90, "최근 180일": 180, "최근 1년": 365, "전체": None}
LIMIT_STYLE = {"ks_min": ("KS 하한", "#d03b3b", "solid"), "ks_max": ("KS 상한", "#d03b3b", "solid"),
               "lsl": ("사내 하한", "#ec835a", "dash"), "usl": ("사내 상한", "#ec835a", "dash"),
               "target": ("목표", "#0ca30c", "dot")}


def aggregate(s: pd.Series, agg: str | None) -> pd.Series:
    s = s.dropna().sort_index()
    if not agg or s.empty:
        return s
    return s.resample(agg, label="left", closed="left").mean().dropna()


def moving(s: pd.Series, n: int) -> pd.Series:
    if not n or n < 2 or len(s) < 2:
        return pd.Series(dtype=float)
    return s.rolling(n, min_periods=max(2, n // 3)).mean()


def zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=1)
    return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else s * 0


def item_figure(s: pd.Series, title: str, unit: str, color: str = SERIES[0], ma: int = 0,
                limits: dict | None = None, show_points: bool = True, height: int = 300) -> go.Figure:
    """항목 하나의 추이. limits: {필드: 상수 또는 x와 같은 길이의 Series}."""
    fig = go.Figure()
    mode = "lines+markers" if show_points and len(s) <= 400 else "lines"
    fig.add_trace(go.Scatter(x=s.index, y=s.values, mode=mode, name=title, line=dict(color=color, width=2),
                             marker=dict(size=6, color=color), hovertemplate=f"%{{x|%Y-%m-%d}}<br>{title} %{{y:,.2f}} {unit}<extra></extra>"))
    m = moving(s, ma)
    if len(m):
        fig.add_trace(go.Scatter(x=m.index, y=m.values, mode="lines", name=f"{ma}점 이동평균", line=dict(color="#0f172a", width=2),
                                 hoverinfo="skip"))
    for f, v in (limits or {}).items():
        if f not in LIMIT_STYLE or v is None:
            continue
        lab, col, dash = LIMIT_STYLE[f]
        if isinstance(v, pd.Series):
            if v.notna().any():
                fig.add_trace(go.Scatter(x=v.index, y=v.values, mode="lines", name=lab, line=dict(color=col, width=1.5, dash=dash, shape="hv"),
                                         hoverinfo="skip"))
        elif np.isfinite(v):
            fig.add_hline(y=float(v), line=dict(color=col, width=1.5, dash=dash), annotation_text=f"{lab} {v:g}",
                          annotation_position="top left", annotation_font=dict(size=11, color="#52514e"))
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)), height=height, margin=dict(l=10, r=10, t=40, b=10),
                      hovermode="x unified", showlegend=len(fig.data) > 1, yaxis=dict(title=unit or None, gridcolor="#eef1f7"),
                      xaxis=dict(type="date", showgrid=False), legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0))
    return fig


def overlay_figure(series: list[tuple[str, str, pd.Series]], standardize: bool, ma: int = 0, title: str = "",
                   height: int = 420) -> go.Figure:
    """여러 항목을 한 그래프에(축은 하나). 단위가 다르면 standardize=True(평균 0·표준편차 1)로만 겹친다."""
    fig = go.Figure()
    for i, (name, unit, s) in enumerate(series[: len(SERIES)]):
        y = zscore(s) if standardize else s
        col = SERIES[i]
        fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines+markers" if len(y) <= 300 else "lines", name=name,
                                 line=dict(color=col, width=2), marker=dict(size=6, color=col),
                                 customdata=s.values, hovertemplate=f"{name} %{{customdata:,.2f}} {unit}<extra></extra>"))
        m = moving(y, ma)
        if len(m):
            fig.add_trace(go.Scatter(x=m.index, y=m.values, mode="lines", name=f"{name} 이동평균", line=dict(color=col, width=3, dash="dot"),
                                     hoverinfo="skip", showlegend=False))
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)) if title else None, height=height,
                      margin=dict(l=10, r=10, t=40 if title else 12, b=10), hovermode="x unified",
                      yaxis=dict(title="표준화 값(평균=0, 표준편차=1)" if standardize else (series[0][1] if series else None), gridcolor="#eef1f7",
                                 zeroline=standardize),
                      xaxis=dict(type="date", showgrid=False), legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0))
    return fig


def wide_table(series: list[tuple[str, str, pd.Series]]) -> pd.DataFrame:
    if not series:
        return pd.DataFrame()
    df = pd.concat({f"{n} ({u})" if u else n: s for n, u, s in series}, axis=1).sort_index()
    df.index.name = "일시"
    return df.reset_index()


# ── 저장된 보기 ─────────────────────────────────────────────────────────
def load_views(path: Path = VIEWS_PATH) -> list[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, json.JSONDecodeError):
        d = []
    return [v for v in d if isinstance(v, dict) and v.get("name")]


def save_view(view: dict, path: Path = VIEWS_PATH) -> list[dict]:
    views = [v for v in load_views(path) if v["name"] != view["name"]] + [view]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(views, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return views


def delete_view(name: str, path: Path = VIEWS_PATH) -> list[dict]:
    views = [v for v in load_views(path) if v["name"] != name]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(views, ensure_ascii=False, indent=2), encoding="utf-8")
    return views
