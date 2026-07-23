"""Plotly 시각화 (한글 안전·인터랙티브) [Synthesis-Agent].

브라우저 폰트로 렌더되어 한글이 깨지지 않는다. 자기완결 HTML 로 조립.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

TARGET = 44.6
GREEN, BLUE, RED, ORANGE = "#2ca02c", "#1f77b4", "#d62728", "#ff7f0e"


def grade_color(cao: float, alpha: float = 0.55) -> str:
    """CaO 를 목표(44.6) 기준 발산 색으로. 낮으면 파랑, 높으면 빨강."""
    if cao is None or np.isnan(cao):
        return f"rgba(150,150,150,{alpha})"
    d = max(-2.0, min(2.0, cao - TARGET)) / 2.0  # -1..1
    if d >= 0:
        r, g, b = 214, int(160 - 120 * d), int(120 - 100 * d)
    else:
        r, g, b = int(60 - 30 * d), int(140 + 20 * d), 200
    return f"rgba({r},{g},{b},{alpha})"


def sankey_tracking(labels, node_colors, srcs, tgts, values, link_colors, link_hover) -> go.Figure:
    """광산→라인→야드 추적 흐름 Sankey."""
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, color=node_colors, pad=22, thickness=26,
                  line=dict(color="rgba(0,0,0,0.25)", width=1)),
        link=dict(source=srcs, target=tgts, value=values, color=link_colors,
                  customdata=link_hover, hovertemplate="%{customdata}<extra></extra>"),
    ))
    fig.update_layout(
        title="① 광산 → OSP → 야드 물류·품위 추적 (링크 두께=물량, 색=CaO)",
        font=dict(size=13), height=430, margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def prediction_timeseries(index, actual, pred, oos, title) -> go.Figure:
    """예측 실측 대비 + 규격밴드 + 조기경보."""
    fig = go.Figure()
    fig.add_hrect(y0=TARGET - 0.5, y1=TARGET + 0.5, fillcolor=GREEN, opacity=0.10,
                  line_width=0, annotation_text="규격 44.1~45.1", annotation_position="top left")
    fig.add_hline(y=TARGET, line=dict(color=GREEN, dash="dash", width=1))
    fig.add_trace(go.Scatter(x=index, y=actual, name="실측 CaO", line=dict(color=BLUE, width=1.6)))
    fig.add_trace(go.Scatter(x=index, y=pred, name="예측 CaO", line=dict(color=RED, width=1.6)))
    if np.any(oos):
        fig.add_trace(go.Scatter(x=np.asarray(index)[oos], y=np.asarray(pred)[oos],
                      mode="markers", name="규격이탈 경보",
                      marker=dict(color=ORANGE, size=7, symbol="triangle-up")))
    fig.update_layout(title=title, height=340, font=dict(size=12),
                      margin=dict(l=10, r=10, t=44, b=10),
                      yaxis_title="CaO (%)", legend=dict(orientation="h", y=1.12, x=1, xanchor="right"))
    return fig


def stage_cao_bar(stages) -> go.Figure:
    """단계별 CaO 평균±표준편차 (변동성 축소 목표 시각화). stages=[(name,mean,std,color)]."""
    names = [s[0] for s in stages]
    means = [s[1] for s in stages]
    stds = [s[2] for s in stages]
    colors = [s[3] for s in stages]
    fig = go.Figure(go.Bar(
        x=names, y=means, marker_color=colors,
        error_y=dict(type="data", array=stds, visible=True),
        text=[f"{m:.2f}±{s:.2f}" for m, s in zip(means, stds)], textposition="outside",
    ))
    fig.add_hline(y=TARGET, line=dict(color=GREEN, dash="dash"),
                  annotation_text=f"목표 {TARGET}", annotation_position="right")
    fig.update_layout(title="② 공정 단계별 CaO 평균±표준편차 (오차막대=변동성)",
                      height=360, font=dict(size=12), yaxis_title="CaO (%)",
                      margin=dict(l=10, r=10, t=46, b=10), yaxis_range=[42, 48])
    return fig


def assemble_html(title: str, sections: list[tuple[str, object]], tail_html: str = "") -> str:
    """섹션(제목, Figure 또는 HTML문자열)들을 자기완결 HTML 로 조립. plotly.js 1회 인라인."""
    import plotly.io as pio

    body, first = [], True
    for heading, obj in sections:
        if heading:
            body.append(f"<h2>{heading}</h2>")
        if isinstance(obj, go.Figure):
            body.append(pio.to_html(obj, include_plotlyjs=(True if first else False),
                                    full_html=False, config={"displModeBar": False}))
            first = False
        else:
            body.append(str(obj))
    inner = "\n".join(body)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>body{{font-family:system-ui,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;
max-width:1040px;margin:22px auto;padding:0 16px;color:#1a1a1a;line-height:1.6}}
h1{{border-bottom:3px solid #1f77b4;padding-bottom:8px}}h2{{margin-top:30px;color:#12395c}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}th,td{{border:1px solid #ddd;padding:8px;text-align:center}}
th{{background:#f0f4f8}}.ok{{background:#e8f5e9;border-left:4px solid #2ca02c;padding:10px 14px;margin:14px 0;border-radius:4px}}
.note{{background:#fff8e1;border-left:4px solid #ffb300;padding:10px 14px;margin:14px 0;border-radius:4px}}
code,pre{{background:#f4f4f4;border-radius:4px}}pre{{padding:12px;overflow-x:auto}}code{{padding:1px 5px}}</style></head>
<body><h1>{title}</h1>{inner}{tail_html}
<p style="color:#888;font-size:0.85em;margin-top:24px">※ 본 리포트·데이터는 로컬 전용입니다. 외부(원격)에 발행/커밋하지 않습니다.</p>
</body></html>"""
