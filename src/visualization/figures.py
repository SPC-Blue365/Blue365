"""Plotly 시각화 (한글 안전·인터랙티브) [Synthesis-Agent].

브라우저 폰트로 렌더되어 한글이 깨지지 않는다. 자기완결 HTML 로 조립.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

TARGET = 44.6
GREEN, BLUE, RED, ORANGE = "#2ca02c", "#1f77b4", "#d62728", "#ff7f0e"


# 날짜축 포맷 (확대 수준별): 시 단위 → 일 단위 → 월 단위 (예: 2026/07/24)
KDATE_STOPS = [
    dict(dtickrange=[None, 3600000], value="%m/%d %H시"),               # 1시간 미만 간격
    dict(dtickrange=[3600000, 86400000], value="%m/%d %H시"),           # 시간 단위
    dict(dtickrange=[86400000, 604800000], value="%Y/%m/%d"),          # 일 단위
    dict(dtickrange=[604800000, None], value="%Y/%m"),                 # 주/월 단위
]


def _korean_date_axis(fig: go.Figure) -> go.Figure:
    """x축(시간)을 한글 년/월/일 표기로 설정."""
    fig.update_xaxes(tickformatstops=KDATE_STOPS)
    return fig


def _time_range_controls(fig: go.Figure, slider: bool = True) -> go.Figure:
    """그래프 우측 상단에 기간 선택 버튼(1주/2주/1개월/전체) + 하단 기간 슬라이더."""
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[
                dict(count=7, label="1주", step="day", stepmode="backward"),
                dict(count=14, label="2주", step="day", stepmode="backward"),
                dict(count=1, label="1개월", step="month", stepmode="backward"),
                dict(count=1, label="1년", step="year", stepmode="backward"),
                dict(step="all", label="전체"),
            ],
            x=1, xanchor="right", y=1.02, yanchor="bottom",
            # 활성 버튼은 어둡게 채우지 않고 '밝은 강조 + 진한 테두리'로 (글씨 항상 보이게)
            bgcolor="#f4f7fa", activecolor="#cfe0f2", bordercolor="#12395c",
            borderwidth=1, font=dict(size=11, color="#12395c"),
        ),
        rangeslider=dict(visible=slider, thickness=0.07),
    )
    return fig


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
    # 규격 라벨은 플롯 바깥 오른쪽에 (왼쪽 안쪽에 두면 y축 눈금에 잘린다)
    fig.add_hrect(y0=TARGET - 0.5, y1=TARGET + 0.5, fillcolor=GREEN, opacity=0.10, line_width=0)
    fig.add_hline(y=TARGET, line=dict(color=GREEN, dash="dash", width=1))
    fig.add_annotation(x=1.0, xref="paper", xanchor="left", xshift=6, y=TARGET, yref="y",
                       text=f"규격<br>{TARGET - 0.5:g}~{TARGET + 0.5:g}", showarrow=False,
                       align="left", font=dict(size=10, color="#1d7a1d"))
    fig.add_trace(go.Scatter(x=index, y=actual, name="실측 CaO (실제 측정)",
                             line=dict(color=BLUE, width=1.8),
                             hovertemplate="%{x|%m/%d %H시}<br>실측 %{y:.2f}%<extra></extra>"))
    fig.add_trace(go.Scatter(x=index, y=pred, name="예측 CaO (1시간 전에 예측한 값)",
                             line=dict(color=RED, width=1.8),
                             hovertemplate="%{x|%m/%d %H시}<br>예측 %{y:.2f}%<extra></extra>"))
    if np.any(oos):
        fig.add_trace(go.Scatter(x=np.asarray(index)[oos], y=np.asarray(pred)[oos],
                      mode="markers", name="규격이탈 사전경보",
                      marker=dict(color=ORANGE, size=8, symbol="triangle-up",
                                  line=dict(color="white", width=1)),
                      hovertemplate="%{x|%m/%d %H시}<br>규격이탈 예상 %{y:.2f}%<extra></extra>"))
    # 제목이 길어 범례와 겹치던 문제 → 범례를 제목 **아래 줄**로 내리고 위 여백을 넉넉히.
    fig.update_layout(title=dict(text=title, y=0.97, yanchor="top"),
                      height=372, font=dict(size=12),
                      margin=dict(l=10, r=76, t=88, b=10), yaxis_title="CaO (%)",
                      # 기간 버튼이 오른쪽(x=1)에 있으므로 범례는 왼쪽에 둔다
                      legend=dict(orientation="h", y=1.02, yanchor="bottom",
                                  x=0, xanchor="left", font=dict(size=11)))
    return _time_range_controls(_korean_date_axis(fig))


def prediction_scorecard(methods, tol: float = 0.5, title: str = "") -> go.Figure:
    """예측 방법별 평균 오차 비교 (가로 막대 · 모델만 강조).

    "이 예측이 쓸만한가"를 한 눈에 답하는 임원용 차트.
    methods = [(방법이름, MAE, is_model), ...] — is_model=True 인 항목만 색을 입히고
    나머지 기준선은 회색으로 후퇴시킨다(emphasis 형태: 1 hue + gray).
    tol = 목표 허용오차(±0.5%p) — 이 선보다 왼쪽이어야 실무 사용 가능.
    """
    ms = sorted(methods, key=lambda x: x[1], reverse=True)   # 가로막대는 아래가 먼저
    names = [m[0] for m in ms]
    vals = [m[1] for m in ms]
    colors = [BLUE if m[2] else "#b6bcc4" for m in ms]
    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation="h", marker_color=colors,
        text=[f"{v:.2f}" for v in vals], textposition="outside",
        textfont=dict(size=13, color="#1a1a1a"),
        hovertemplate="%{y}<br>평균 오차 %{x:.2f}%p<extra></extra>",
        width=0.55,
    ))
    fig.add_vline(x=tol, line=dict(color=GREEN, dash="dash", width=2))
    fig.add_annotation(x=tol, y=1.04, yref="paper", text=f"허용폭 ±{tol}%p", showarrow=False,
                       font=dict(color="#1d7a1d", size=12), xanchor="left", xshift=4)
    fig.update_layout(
        # meta.kind → 리포트 HTML의 허용폭 선택 JS가 이 차트의 기준선을 찾아 옮긴다
        meta=dict(kind="scorecard"),
        title=title, height=210 + 26 * len(ms), font=dict(size=12),
        margin=dict(l=10, r=54, t=54, b=34), showlegend=False,
        xaxis_title="평균 오차 (%p · 낮을수록 정확)", bargap=0.35,
        xaxis=dict(range=[0, max(vals) * 1.22], showgrid=True, gridcolor="#eceff2", zeroline=False),
        yaxis=dict(showgrid=False),
        plot_bgcolor="white",
    )
    return fig


#: 라인 구분용 계열색 (팔레트 검증기 6항목 전부 통과: CVD ΔE 20.1, 대비 3:1↑)
LINE_COLORS = {"기존": BLUE, "신설": "#eb6834"}


def inventory_series(mine, osp_exp, line: str, freq: str = "1D"):
    """한 라인의 OSP 재고 '증감' 시계열 = 누적(적재 − 인출).

    ⚠️ **시작 재고는 데이터에 없다.** 따라서 절대 재고량이 아니라 **기간 시작 대비
       누적 증감**만 계산한다(시작점 0). 지어내지 않는다(CLAUDE.md §2-1).
       판단에 쓰는 것은 **기울기**(늘고 있나 줄고 있나)이므로 기준선이 0이어도 무방하다.

    반환: (index, 누적증감, 구간별 적재, 구간별 인출) — 데이터가 없으면 모두 빈 값.
    """
    import pandas as pd

    def _agg(df, tcol, vcol):
        if df is None or len(df) == 0 or tcol not in df.columns:
            return pd.Series(dtype="float64")
        d = df[df["line"] == line] if "line" in df.columns else df
        d = d.dropna(subset=[tcol])
        if len(d) == 0:
            return pd.Series(dtype="float64")
        s = pd.Series(pd.to_numeric(d[vcol], errors="coerce").fillna(0).values,
                      index=pd.to_datetime(d[tcol].values))
        return s.resample(freq).sum()

    inflow = _agg(mine, "datetime", "tonnage")
    outflow = _agg(osp_exp, "datetime", "withdrawn_ton")
    if inflow.empty and outflow.empty:
        empty = pd.Series(dtype="float64")
        return empty.index, empty, empty, empty
    idx = inflow.index.union(outflow.index)
    inflow = inflow.reindex(idx, fill_value=0.0)
    outflow = outflow.reindex(idx, fill_value=0.0)
    return idx, (inflow - outflow).cumsum(), inflow, outflow


def inventory_trend(mine, osp_exp, freq: str = "1D", title: str = "") -> go.Figure:
    """OSP 재고 증감 추이 (라인별 · 기간 시작 대비 누적).

    선이 내려가면 **쓴 양이 들어온 양보다 많아 재고가 줄고 있다**는 뜻,
    올라가면 재고가 늘고 있다는 뜻. 0선은 '기간 시작 수준'.
    """
    import pandas as pd

    fig = go.Figure()
    any_data = False
    for ln, color in LINE_COLORS.items():
        idx, cum, inflow, outflow = inventory_series(mine, osp_exp, ln, freq)
        if len(idx) == 0:
            continue
        any_data = True
        fig.add_trace(go.Scatter(
            x=idx, y=cum.values, name=f"{ln} 라인", mode="lines",
            line=dict(color=color, width=2.2),
            customdata=np.stack([inflow.values, outflow.values], axis=-1),
            hovertemplate=("%{x|%m/%d}<br>누적 증감 %{y:,.0f}톤"
                           "<br>적재 %{customdata[0]:,.0f}톤 · 인출 %{customdata[1]:,.0f}톤"
                           "<extra>" + ln + "</extra>"),
        ))
        # 마지막 값 직접 라벨 (색만으로 구분하지 않도록)
        fig.add_annotation(x=idx[-1], y=cum.values[-1], text=f"{ln} {cum.values[-1]:+,.0f}t",
                           showarrow=False, xanchor="left", xshift=6,
                           font=dict(color=color, size=11))
    if not any_data:
        fig.update_layout(title="재고 추이 — 해당 기간 데이터 없음", height=300)
        return fig

    fig.add_hline(y=0, line=dict(color="#8c8c89", width=1.2),
                  annotation_text="기간 시작 수준", annotation_position="top left",
                  annotation_font=dict(size=11, color="#666"))
    fig.update_layout(
        title=title or "OSP 재고 증감 추이 (기간 시작 대비 누적 · 적재−인출)",
        height=360, font=dict(size=12), margin=dict(l=10, r=86, t=54, b=10),
        yaxis_title="누적 증감 (톤)", plot_bgcolor="white",
        yaxis=dict(showgrid=True, gridcolor="#eceff2", zeroline=False, tickformat=","),
        legend=dict(orientation="h", y=1.1, x=1, xanchor="right"),
    )
    return _time_range_controls(_korean_date_axis(fig))


def stock_trend(stock, mine, osp_exp, title: str = "", calibrations: dict | None = None) -> go.Figure:
    """OSP 실사 재고 vs 흐름계산 재고 (라인별 2단 비교).

    - **실선 = 실사 재고**(교대마다 파악한 실제 재고량, 1,000톤 단위 개략치)
    - **굵은 점선 = 보정 흐름**(실사에 맞춰 기록 배율을 추정·보정한 값)
    - **옅은 점선 = 보정 전 흐름**(적재−인출 그대로) — 보정 전후 차이를 함께 보인다
    두 선이 벌어지면 **광산 기록에 안 잡힌 유입**이 있다는 뜻이다. 어느 한쪽을
    맞다고 단정하지 않고 둘 다 보여준다(CLAUDE.md §2-1).
    """
    import pandas as pd
    from plotly.subplots import make_subplots

    from src.models.dataset import apply_calibration

    lines = [ln for ln in LINE_COLORS
             if stock is not None and len(stock) and (stock["line"] == ln).any()]
    if not lines:
        f = go.Figure()
        f.update_layout(title="OSP 실사 재고 — 해당 기간 데이터 없음", height=300)
        return f

    fig = make_subplots(rows=len(lines), cols=1, shared_xaxes=True, vertical_spacing=0.09,
                        subplot_titles=[f"{ln} 라인 (OSP{'1' if ln == '기존' else '2'})"
                                        for ln in lines])
    for i, ln in enumerate(lines, start=1):
        g = stock[stock["line"] == ln].dropna(subset=["stock_ton"]).sort_values("datetime")
        if not len(g):
            continue
        color = LINE_COLORS[ln]
        fig.add_trace(go.Scatter(
            x=g["datetime"], y=g["stock_ton"], name="실사 재고", legendgroup="a",
            showlegend=(i == 1), mode="lines", line=dict(color=color, width=2.2),
            hovertemplate="%{x|%m/%d %H시}<br>실사 재고 %{y:,.0f}톤<extra></extra>"),
            row=i, col=1)
        # 끝점 라벨은 두 곡선(실사·흐름)의 y 가 가까우면 겹친다 → 아래에서 한꺼번에 배치한다.
        end_labels = [dict(x=g["datetime"].iloc[-1], y=float(g["stock_ton"].iloc[-1]),
                           text=f"실사 {g['stock_ton'].iloc[-1]:,.0f}t", color=color)]

        # 흐름 계산: **흐름 데이터가 시작되는 시점의 실사값**을 출발점으로 (적재−인출) 누적.
        # (전체 실사의 첫 값에 붙이면 2년 전 값에서 출발해 선이 엉뚱한 곳으로 간다)
        idx, cum, inflow, outflow = inventory_series(mine, osp_exp, ln)
        if len(idx):
            flow_start = idx[0]
            prior = g[g["datetime"] <= flow_start]
            base = float(prior["stock_ton"].iloc[-1]) if len(prior) else float(g["stock_ton"].iloc[0])
            y = base + cum.values
            cal = (calibrations or {}).get(ln) or {}
            if cal:
                # 실사에 맞춘 보정 곡선을 주선으로, 보정 전은 옅게 참고용으로
                ycal = apply_calibration(cal, idx, inflow.cumsum().values,
                                         outflow.cumsum().values, base)
                fig.add_trace(go.Scatter(
                    x=idx, y=y, name="보정 전 흐름", legendgroup="c", showlegend=(i == 1),
                    mode="lines", line=dict(color="#c9cdd2", width=1.4, dash="dot"),
                    hovertemplate="%{x|%m/%d}<br>보정 전 %{y:,.0f}톤<extra></extra>"),
                    row=i, col=1)
                fig.add_trace(go.Scatter(
                    x=idx, y=ycal, name=f"보정 흐름 ({cal['method']}={cal['coef']:.3f})",
                    legendgroup="b", showlegend=(i == 1), mode="lines",
                    line=dict(color="#8c8c89", width=2.0, dash="dash"),
                    hovertemplate="%{x|%m/%d}<br>보정 흐름 %{y:,.0f}톤<extra></extra>"),
                    row=i, col=1)
                end_labels.append(dict(x=idx[-1], y=float(ycal[-1]),
                                       text=f"보정 {ycal[-1]:,.0f}t", color="#6b6b68"))
                y = ycal      # 0선 경고 판단은 보정 후 기준
            else:
                fig.add_trace(go.Scatter(
                    x=idx, y=y, name="흐름 계산 (적재−인출)", legendgroup="b",
                    showlegend=(i == 1), mode="lines",
                    line=dict(color="#8c8c89", width=1.8, dash="dash"),
                    hovertemplate="%{x|%m/%d}<br>흐름 계산 %{y:,.0f}톤<extra></extra>"),
                    row=i, col=1)
                end_labels.append(dict(x=idx[-1], y=float(y[-1]),
                                       text=f"계산 {y[-1]:,.0f}t", color="#6b6b68"))
            if np.nanmin(y) < 0:
                fig.add_hline(y=0, line=dict(color="#d03b3b", width=1, dash="dot"), row=i, col=1)
        # 끝점 라벨 배치 — 두 값이 가까우면 픽셀 단위로 벌려 글자가 겹치지 않게 한다.
        end_labels.sort(key=lambda d: -d["y"])
        span = max(float(np.nanmax(g["stock_ton"])) - float(np.nanmin(g["stock_ton"])), 1.0)
        shifts = [0] * len(end_labels)
        if len(end_labels) == 2 and abs(end_labels[0]["y"] - end_labels[1]["y"]) < span * 0.12:
            shifts = [9, -9]            # 위 라벨은 위로, 아래 라벨은 아래로
        for lb, sh in zip(end_labels, shifts):
            fig.add_annotation(x=lb["x"], y=lb["y"], text=lb["text"], showarrow=False,
                               xanchor="left", xshift=6, yshift=sh,
                               font=dict(color=lb["color"], size=11), row=i, col=1)

        fig.update_yaxes(title_text="재고 (톤)", row=i, col=1, tickformat=",",
                         showgrid=True, gridcolor="#eceff2", zeroline=False)

    fig.update_layout(
        title=title or "OSP 재고 — 실사(실선) vs 흐름 계산(점선)",
        height=250 * len(lines) + 150, font=dict(size=12),
        margin=dict(l=10, r=96, t=86, b=92), plot_bgcolor="white",
        # 범례를 아래로 — 위에 두면 서브플롯 제목과 기간 버튼을 동시에 가린다
        legend=dict(orientation="h", y=-0.30, yanchor="top", x=0.5, xanchor="center",
                    font=dict(size=11)),
    )
    for ax in fig.select_xaxes():
        ax.update(tickformatstops=KDATE_STOPS)
    # 아래 축에만 기간 버튼·슬라이더 (실사는 2년치, 흐름은 최근 몇 주 — 확대해서 비교)
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[dict(count=1, label="1개월", step="month", stepmode="backward"),
                     dict(count=3, label="3개월", step="month", stepmode="backward"),
                     dict(count=1, label="1년", step="year", stepmode="backward"),
                     dict(step="all", label="전체")],
            x=1, xanchor="right", y=1.02, yanchor="bottom",
            bgcolor="#f4f7fa", activecolor="#cfe0f2", bordercolor="#12395c",
            borderwidth=1, font=dict(size=11, color="#12395c")),
        rangeslider=dict(visible=True, thickness=0.05),
        row=len(lines), col=1,
    )
    # 처음엔 '비교가 보이는 구간'으로 확대해서 연다 (실사는 2년치라 그냥 두면 안 보인다).
    # 전체 이력은 위 '전체' 버튼·아래 슬라이더로 볼 수 있다.
    idx0, _, _, _ = inventory_series(mine, osp_exp, lines[0])
    if len(idx0):
        lo = pd.Timestamp(idx0[0]) - pd.Timedelta(days=7)
        hi = pd.Timestamp(stock["datetime"].max()) + pd.Timedelta(days=1)
        fig.update_xaxes(range=[lo, hi])
    return fig


def calibration_drift(windows: dict, title: str = "") -> go.Figure:
    """인출 벨트스케일 지시 배율 β 의 시간 변화 (교정 시점 판단용).

    β = 실제 인출량 / 계량기 지시값. **1.0 이면 정확**, 1.0 미만이면 계량기가
    실제보다 **많이 찍고 있다**는 뜻(예: 0.90 → 약 10% 과대 지시).
    오차막대는 95% 신뢰구간이며, 구간끼리 겹치지 않으면 실제로 변한 것이다.
    windows: {라인: [ {start,end,beta,se,n,ok,reason}, ... ]}

    ⚠️ ok=False 인 구간(라인 정지 등으로 인출이 거의 없어 β 를 식별할 수 없는 창)은
       그리지 않는다. 몇 개를 왜 뺐는지는 리포트 본문이 밝힌다(CLAUDE.md §2-1).
    """
    import pandas as pd

    fig = go.Figure()
    any_pt = False
    for ln, ws_all in (windows or {}).items():
        ws = [w for w in (ws_all or []) if w.get("ok", True)]
        if not ws:
            continue
        any_pt = True
        x = [pd.Timestamp(w["start"]) + (pd.Timestamp(w["end"]) - pd.Timestamp(w["start"])) / 2
             for w in ws]
        yv = [w["beta"] for w in ws]
        err = [1.96 * w["se"] for w in ws]
        fig.add_trace(go.Scatter(
            x=x, y=yv, name=f"{ln} 라인", mode="lines+markers",
            line=dict(color=LINE_COLORS.get(ln, BLUE), width=2),
            marker=dict(size=9),
            error_y=dict(type="data", array=err, visible=True, thickness=1.2, width=5),
            customdata=[[w["n"], (1 - w["beta"]) * 100] for w in ws],
            hovertemplate=("%{x|%m/%d}<br>β %{y:.3f}"
                           "<br>계량기 과대 지시 %{customdata[1]:+.1f}%"
                           "<br>실사 %{customdata[0]}회<extra>" + ln + "</extra>")))
    if not any_pt:
        fig.update_layout(title="계량 배율 추정 — 데이터 부족", height=300)
        return fig

    fig.add_hline(y=1.0, line=dict(color="#8c8c89", width=1.5), layer="below")
    fig.add_annotation(x=1.0, xref="paper", xanchor="left", xshift=6, y=1.0, yref="y",
                       text="1.0<br>정확", showarrow=False, align="left",
                       font=dict(size=10, color="#555"))
    fig.update_layout(
        title=dict(text=title or "인출 벨트스케일 지시 배율 β 추이 (1.0=정확 · 낮을수록 과대 지시)",
                   y=0.97, yanchor="top"),
        height=340, font=dict(size=12), margin=dict(l=10, r=78, t=84, b=10),
        yaxis_title="β (실제 ÷ 지시값)", plot_bgcolor="white",
        yaxis=dict(showgrid=True, gridcolor="#eceff2", zeroline=False),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left",
                    font=dict(size=11)),
    )
    return _korean_date_axis(fig)


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


def _fmt(v, nd: int = 2) -> str:
    """수치 표기. 값이 없으면 지어내지 않고 '-' (CLAUDE.md §2-1)."""
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"


def _wavg(values, weights) -> float:
    """물량가중 평균. 품위가 빈칸인 행은 분자·분모 양쪽에서 제외한다.

    (빈칸을 0으로 넣으면 평균이 0쪽으로 끌려간다 — 47Q CaO 45.6→36.6 왜곡 버그.)
    """
    import pandas as pd

    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0)
    ok = v.notna() & (w > 0)
    return float((v[ok] * w[ok]).sum() / w[ok].sum()) if w[ok].sum() > 0 else float("nan")


def build_tracking_sankey(mine, osp_exp, yards) -> go.Figure:
    """광산→라인→야드 추적 Sankey (원시 정제 데이터에서 흐름 계산).

    호버 수치는 정적/JS 재계산 경로가 동일한 규칙(물량가중·빈칸 제외)을 쓴다.
    """
    import pandas as pd

    from config import schema as S

    labels = ["49Q 광산(XRF)", "47Q 광산(감마)", "기존 라인", "신설 라인", "45Q 야드(4-5K)", "CNA 야드(6-7K)"]
    node_colors = ["#6baed6", "#9ecae1", "#f4a582", "#fdae61", "#74c476", "#31a354"]
    src, tgt, val, lc, hov, keys = [], [], [], [], [], []
    smap, lmap, ymap = {"49Q": 0, "47Q": 1}, {S.LINE_OLD: 2, S.LINE_NEW: 3}, {S.LINE_OLD: 4, S.LINE_NEW: 5}
    mm = mine[mine["line"].isin([S.LINE_OLD, S.LINE_NEW])]
    for (so, ln), g in mm.groupby(["source", "line"]):
        ton = g["tonnage"].sum(min_count=1)
        cao, mgo = _wavg(g["cao"], g["tonnage"]), _wavg(g["mgo"], g["tonnage"])
        if pd.isna(ton) or ton <= 0:
            continue
        src.append(smap[so]); tgt.append(lmap[ln]); val.append(float(ton)); lc.append(grade_color(cao))
        hov.append(f"{labels[smap[so]]} → {labels[lmap[ln]]}<br>이송 {ton:,.0f}톤"
                   f"<br>CaO {_fmt(cao)}% · MgO {_fmt(mgo)}%")
        keys.append(f"{so}|{ln}")
    for ln in [S.LINE_OLD, S.LINE_NEW]:
        ton = osp_exp.loc[osp_exp["line"] == ln, "withdrawn_ton"].sum(min_count=1)
        if pd.isna(ton) or ton <= 0:
            continue
        y = yards.get(ln)                                  # 라인 필터로 빠져 있을 수 있다
        ycao = y["cao"].mean() if y is not None and len(y) else float("nan")
        ymgo = y["mgo"].mean() if y is not None and len(y) else float("nan")
        src.append(lmap[ln]); tgt.append(ymap[ln]); val.append(float(ton)); lc.append(grade_color(ycao))
        hov.append(f"{labels[lmap[ln]]} → {labels[ymap[ln]]}<br>인출 {ton:,.0f}톤"
                   f"<br>야드 CaO {_fmt(ycao)}% · MgO {_fmt(ymgo)}%")
        keys.append(f"__yard__{ln}")
    fig = sankey_tracking(labels, node_colors, src, tgt, val, lc, hov)
    fig.update_layout(meta=dict(
        kind="flow_sankey", link_keys=keys,
        labels=[f"{labels[a]} → {labels[b]}" for a, b in zip(src, tgt)]))
    return fig


def sankey_daily_aggregates(mine, osp_exp, yards, yc) -> dict:
    """Sankey 링크의 '일별' 집계 → 정적 HTML에서 기간별로 JS가 재계산할 수 있게 한다.

    각 링크마다 [시각키, 물량, 물량×CaO, CaO유효물량, 물량×MgO, MgO유효물량] 을 쌓아두면,
    임의 구간 합계로 총물량과 물량가중 평균 품위를 정확히 복원할 수 있다.

    ⭐️ 시각키는 **시간 단위**(`YYYY-MM-DDTHH`)다. 야드변경 구간이 42시간부터 시작하므로
       일 단위로 묶으면 경계일이 이웃 구간과 섞인다. 문자열 사전순 비교가 시간순과
       일치하므로 JS 는 그대로 범위 비교만 하면 된다(날짜만 넘어오면 JS 가 T00/T99 로 보정).

    ⭐️ **품위 빈칸은 평균에서 제외한다**: 품위가 비어 있는 행은 물량(ton)에는 포함되지만
       가중평균의 분자·분모 **양쪽에서 모두 빠져야** 한다. 분모에 물량만 남으면 평균이
       0 쪽으로 끌려간다(47Q는 15%가 빈칸이라 CaO가 45.6 → 36.6으로 왜곡됐던 버그).
       CaO·MgO는 빈칸 위치가 다를 수 있으므로 **성분별로 유효물량을 따로** 집계한다.
    반환: {"yc"/"flow": {링크키: [[d, ton, wc, wton_c, wm, wton_m], ...]},
           "yard_daily": {라인: [[d, n_cao, sum_cao, n_mgo, sum_mgo], ...]}}
    """
    import pandas as pd

    from config import schema as S

    def _rows(df, key_cols, ton_col, cao_col=None, mgo_col=None, date_col="datetime",
              key_fmt="%Y-%m-%dT%H"):
        out: dict[str, list] = {}
        if df is None or len(df) == 0:
            return out
        d = df.dropna(subset=[date_col]).copy()
        d["_d"] = pd.to_datetime(d[date_col]).dt.strftime(key_fmt)

        def _weighted(g, ton, col):
            """(물량×품위 합, 품위가 유효한 행의 물량 합). 빈칸 행은 양쪽에서 제외."""
            if not col:
                return 0.0, 0.0
            v = pd.to_numeric(g[col], errors="coerce")
            ok = v.notna()
            return float((ton[ok] * v[ok]).sum()), float(ton[ok].sum())

        for keys, g in d.groupby(key_cols + ["_d"]):
            *kparts, day = keys if isinstance(keys, tuple) else (keys,)
            k = "|".join(str(x) for x in kparts)
            t = pd.to_numeric(g[ton_col], errors="coerce").fillna(0)
            wc, wtc = _weighted(g, t, cao_col)
            wm, wtm = _weighted(g, t, mgo_col)
            out.setdefault(k, []).append([day, float(t.sum()), wc, wtc, wm, wtm])
        return out

    # 야드변경은 **분 단위** 키를 쓴다 — 변경 시각이 12:30·19:50 처럼 분 단위라, 시간 단위로
    # 묶으면 구간 끝의 '다음 변경 이벤트'를 배제할 수 없어 물량이 통째로 한 건 더 섞인다.
    agg = {"yc": _rows(yc, ["line", "yard"], "tonnage", "cao", "mgo",
                       key_fmt="%Y-%m-%dT%H:%M")}

    # 물류 개요: 광산(source)→라인, 라인→야드
    flow: dict[str, list] = {}
    # 물류 링크도 **분 단위** 키. OSP 인출은 시각이 분 단위라, 시간 단위로 묶으면 구간
    # 끝에서 최대 59분치가 더 딸려 들어온다(신설 06/24 구간에서 9,000톤 초과 집계됐던 버그).
    mm = mine[mine["line"].isin([S.LINE_OLD, S.LINE_NEW])] if mine is not None else None
    # 광산도 교대 시각(datetime)을 쓴다 — 일 단위였을 때의 경계 오차가 사라진다
    flow.update(_rows(mm, ["source", "line"], "tonnage", "cao", "mgo", date_col="datetime",
                      key_fmt="%Y-%m-%dT%H:%M"))
    # 라인→야드: OSP 인출톤(물량) + 해당 야드 CaO는 별도(야드 측정 평균)로 색 결정
    o = _rows(osp_exp, ["line"], "withdrawn_ton", key_fmt="%Y-%m-%dT%H:%M")
    for k, v in o.items():
        flow[f"__yard__{k}"] = v
    yard_daily = {}
    for ln, y in (yards or {}).items():
        if y is None or len(y) == 0:
            continue
        d = y.dropna(subset=["datetime"]).copy()
        d["_d"] = d["datetime"].dt.strftime("%Y-%m-%dT%H")
        # 성분별로 유효 측정 건수를 따로 센다 (45Q는 MgO만 13.6% 비어 있어 공통 카운트 쓰면 왜곡)
        rows = []
        for day, g in d.groupby("_d"):
            c = pd.to_numeric(g["cao"], errors="coerce").dropna()
            m = pd.to_numeric(g["mgo"], errors="coerce").dropna()
            rows.append([day, int(len(c)), float(c.sum()), int(len(m)), float(m.sum())])
        yard_daily[ln] = rows
    agg["flow"] = flow
    agg["yard_daily"] = yard_daily
    return agg


def _mgo_color(v: float, alpha: float = 0.6) -> str:
    """MgO 색: 낮으면 초록(양호), 높으면 빨강(불리). 대략 2.5~4.5 범위."""
    if v is None or np.isnan(v):
        return f"rgba(150,150,150,{alpha})"
    t = max(0.0, min(1.0, (v - 2.5) / (4.5 - 2.5)))
    r, g, b = int(60 + 180 * t), int(160 - 90 * t), int(90 - 40 * t)
    return f"rgba({r},{g},{b},{alpha})"


def build_yardchange_sankey(yc, default: str = "CaO") -> go.Figure:
    """야드변경 기반 추적 Sankey — 라인→야드, 링크=야드물량, 색=CaO/MgO (버튼 토글).

    yc: (datetime, line, yard, cao, mgo, tonnage) long. 링크 두께=총 야드물량,
        색·호버는 CaO/MgO 버튼으로 전환. 값은 물량가중 평균.
    """
    import pandas as pd

    if yc is None or len(yc) == 0:
        f = go.Figure(); f.update_layout(title="야드변경 데이터 없음", height=300); return f

    g = (yc.dropna(subset=["tonnage"]).groupby(["line", "yard"])
         .apply(lambda d: pd.Series(dict(
             ton=d["tonnage"].sum(),
             # _wavg: 품위 빈칸 행만 제외(np.average 는 빈칸 하나에 링크 전체가 NaN이 됨)
             cao=_wavg(d["cao"], d["tonnage"]),
             mgo=_wavg(d["mgo"], d["tonnage"]),
             n=len(d))), include_groups=False)
         .reset_index())

    lines = list(dict.fromkeys(g["line"]))
    yards = list(dict.fromkeys(g["yard"]))
    labels = [f"{l} 라인" for l in lines] + yards
    lidx = {l: i for i, l in enumerate(lines)}
    yidx = {y: len(lines) + i for i, y in enumerate(yards)}
    node_colors = ["#f4a582"] * len(lines) + ["#74c476"] * len(yards)

    src = [lidx[r.line] for r in g.itertuples()]
    tgt = [yidx[r.yard] for r in g.itertuples()]
    val = [float(r.ton) for r in g.itertuples()]
    cao_c = [grade_color(r.cao) for r in g.itertuples()]
    mgo_c = [_mgo_color(r.mgo) for r in g.itertuples()]
    cao_h = [f"{r.line} → {r.yard}<br>물량 {r.ton:,.0f}톤 · 변경 {int(r.n)}회<br>"
             f"<b>CaO {r.cao:.2f}%</b> · MgO {r.mgo:.2f}%" for r in g.itertuples()]
    mgo_h = [f"{r.line} → {r.yard}<br>물량 {r.ton:,.0f}톤 · 변경 {int(r.n)}회<br>"
             f"CaO {r.cao:.2f}% · <b>MgO {r.mgo:.2f}%</b>" for r in g.itertuples()]

    link_keys = [f"{r.line}|{r.yard}" for r in g.itertuples()]
    start_c, start_h = (cao_c, cao_h) if default == "CaO" else (mgo_c, mgo_h)
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, color=node_colors, pad=24, thickness=26,
                  line=dict(color="rgba(0,0,0,0.25)", width=1)),
        link=dict(source=src, target=tgt, value=val, color=start_c, customdata=start_h,
                  hovertemplate="%{customdata}<extra></extra>"),
    ))
    fig.update_layout(
        meta=dict(kind="yc_sankey", link_keys=link_keys,
                  labels=[f"{r.line} → {r.yard}" for r in g.itertuples()]),
        title=f"야드변경 추적 · 성분={default}  (링크 두께=야드물량, 색=품위)",
        font=dict(size=13), height=440, margin=dict(l=10, r=10, t=70, b=10),
        updatemenus=[dict(
            type="buttons", direction="right", x=1.0, y=1.18, xanchor="right",
            showactive=True, active=(0 if default == "CaO" else 1),
            pad=dict(r=4, t=2), bgcolor="#f0f4f8",
            buttons=[
                dict(label="CaO", method="update",
                     args=[{"link.color": [cao_c], "link.customdata": [cao_h]},
                           {"title.text": "야드변경 추적 · 성분=CaO  (링크 두께=야드물량, 색=품위)"}]),
                dict(label="MgO", method="update",
                     args=[{"link.color": [mgo_c], "link.customdata": [mgo_h]},
                           {"title.text": "야드변경 추적 · 성분=MgO  (링크 두께=야드물량, 색=품위)"}]),
            ])],
    )
    return fig


def yardchange_trend(yc) -> go.Figure:
    """변경일자별 CaO·MgO 추이 (라인별). CaO=좌축 실선, MgO=우축 점선, 마커=야드물량 비례."""
    import pandas as pd

    fig = go.Figure()
    if yc is None or len(yc) == 0:
        fig.update_layout(title="야드변경 데이터 없음", height=300); return fig
    palette = {"기존": BLUE, "신설": "#7b3fbf"}
    for line, d in yc.sort_values("datetime").groupby("line"):
        c = palette.get(line, BLUE)
        sizes = 8 + 14 * (d["tonnage"] / yc["tonnage"].max())
        fig.add_trace(go.Scatter(x=d["datetime"], y=d["cao"], mode="lines+markers",
                      name=f"{line} CaO", line=dict(color=c, width=1.6),
                      marker=dict(size=sizes, color=c),
                      customdata=np.stack([d["yard"], d["tonnage"], d["mgo"]], axis=-1),
                      hovertemplate="%{x|%Y/%m/%d}<br>%{customdata[0]}<br>CaO %{y:.2f}% · MgO %{customdata[2]:.2f}%"
                                    "<br>물량 %{customdata[1]:,.0f}톤<extra></extra>"))
        fig.add_trace(go.Scatter(x=d["datetime"], y=d["mgo"], mode="lines+markers",
                      name=f"{line} MgO", line=dict(color=c, width=1.1, dash="dot"),
                      marker=dict(size=5, color=c, symbol="diamond"), yaxis="y2",
                      hovertemplate="%{x|%Y/%m/%d}<br>MgO %{y:.2f}%<extra></extra>"))
    fig.add_hrect(y0=TARGET - 0.5, y1=TARGET + 0.5, fillcolor=GREEN, opacity=0.10, line_width=0)
    fig.add_hline(y=TARGET, line=dict(color=GREEN, dash="dash", width=1))
    fig.update_layout(
        title="변경일자별 야드 CaO·MgO 추이 (마커 크기=야드물량)", height=380, font=dict(size=12),
        margin=dict(l=10, r=10, t=46, b=10),
        yaxis=dict(title="CaO (%)"), yaxis2=dict(title="MgO (%)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.14, x=1, xanchor="right"))
    return _time_range_controls(_korean_date_axis(fig))


def yardchange_gantt(yc, default: str = "CaO") -> go.Figure:
    """야드 변경 타임라인(Gantt) — 라인별로 '언제 어느 야드를 썼는지' 구간 표시.

    각 구간 = [변경일 → 다음 변경일]. 막대 내부=야드+함량값, 색=함량(colorbar 범례),
    성분은 CaO/MgO 버튼 토글. 날짜는 x축이 담당(중복 라벨 제거로 가독성 개선).
    """
    import re

    import pandas as pd

    if yc is None or len(yc) == 0:
        f = go.Figure(); f.update_layout(title="야드변경 데이터 없음", height=280); return f

    end_all = yc["datetime"].max() + pd.Timedelta(days=2)
    rows = []
    for line, d in yc.sort_values("datetime").groupby("line"):
        dd = d.reset_index(drop=True)
        for i in range(len(dd)):
            start = dd.loc[i, "datetime"]
            end = dd.loc[i + 1, "datetime"] if i + 1 < len(dd) else end_all
            m = re.search(r"(Y\d)", str(dd.loc[i, "yard"]))
            rows.append(dict(line=f"{line} 라인", yard=dd.loc[i, "yard"],
                             short=m.group(1) if m else str(dd.loc[i, "yard"]),
                             start=start, end=end,
                             cao=dd.loc[i, "cao"], mgo=dd.loc[i, "mgo"], ton=dd.loc[i, "tonnage"]))
    seg = pd.DataFrame(rows)
    dur = (seg["end"] - seg["start"]).dt.total_seconds() * 1000
    cao_txt = [f"{s} · {c:.1f}" for s, c in zip(seg["short"], seg["cao"])]
    mgo_txt = [f"{s} · {m:.2f}" for s, m in zip(seg["short"], seg["mgo"])]
    cdata = np.stack([seg["yard"], seg["cao"], seg["mgo"], seg["ton"],
                      [s.strftime("%Y/%m/%d") for s in seg["start"]]], axis=-1)

    hover = ("<b>%{customdata[0]}</b> · %{customdata[4]} 변경<br>"
             "CaO %{customdata[1]:.2f}% · MgO %{customdata[2]:.2f}%<br>"
             "야드물량 %{customdata[3]:,.0f}톤<extra></extra>")
    common = dict(y=seg["line"], x=dur, base=seg["start"], orientation="h",
                  textposition="inside", insidetextanchor="middle",
                  textfont=dict(size=11, color="#111"), constraintext="inside",
                  cliponaxis=False, customdata=cdata, hovertemplate=hover)
    is_cao = default == "CaO"
    # 성분별 트레이스 2개(색=함량 연속 + colorbar). 버튼으로 표시 전환 → 컬러스케일 정확.
    fig = go.Figure()
    fig.add_trace(go.Bar(  # CaO: 목표기준 발산(RdBu 역), 낮음=파랑/높음=빨강
        name="CaO", visible=is_cao, text=cao_txt,
        marker=dict(color=seg["cao"], colorscale="RdBu", reversescale=True, cmin=43.0, cmax=46.2,
                    colorbar=dict(title="CaO %", thickness=12, len=0.9), line=dict(color="white", width=1.2)),
        **common))
    fig.add_trace(go.Bar(  # MgO: 순차(OrRd), 낮음=연함/높음=진한 빨강
        name="MgO", visible=not is_cao, text=mgo_txt,
        marker=dict(color=seg["mgo"], colorscale="OrRd", cmin=2.5, cmax=4.5,
                    colorbar=dict(title="MgO %", thickness=12, len=0.9), line=dict(color="white", width=1.2)),
        **common))
    ttl = "야드 변경 타임라인 — 막대 안=야드·{c} 함량, 색=함량(우측 범례)"
    fig.update_layout(
        title=dict(text=ttl.format(c=default), x=0.5, xanchor="center"),
        barmode="overlay", height=420, font=dict(size=12),
        xaxis_type="date", bargap=0.35, margin=dict(l=10, r=10, t=76, b=10), showlegend=False,
        updatemenus=[dict(type="buttons", direction="right", x=0.0, y=1.14, xanchor="left",
                          showactive=True, active=(0 if is_cao else 1),
                          pad=dict(r=4, t=2), bgcolor="#f0f4f8",
                          buttons=[
                              dict(label="CaO", method="update",
                                   args=[{"visible": [True, False]}, {"title.text": ttl.format(c="CaO")}]),
                              dict(label="MgO", method="update",
                                   args=[{"visible": [False, True]}, {"title.text": ttl.format(c="MgO")}]),
                          ])],
    )
    return _time_range_controls(_korean_date_axis(fig))


def _std_bar(g, title: str) -> go.Figure:
    """공용 표준편차 그룹막대. g: DataFrame[name,cao_std,mgo_std,cao_m,mgo_m,n]."""
    fig = go.Figure()
    if g is None or len(g) == 0:
        fig.update_layout(title="데이터 없음", height=300); return fig
    fig.add_trace(go.Bar(x=g["name"], y=g["cao_std"], name="CaO 표준편차", marker_color="#1f77b4",
                         text=[f"{v:.2f}" for v in g["cao_std"]], textposition="outside",
                         customdata=np.stack([g["cao_m"], g["n"]], axis=-1),
                         hovertemplate="%{x}<br>CaO 표준편차 %{y:.3f}<br>평균 %{customdata[0]:.2f}% · n=%{customdata[1]}<extra></extra>"))
    fig.add_trace(go.Bar(x=g["name"], y=g["mgo_std"], name="MgO 표준편차", marker_color="#ff7f0e",
                         text=[f"{v:.2f}" for v in g["mgo_std"]], textposition="outside",
                         customdata=np.stack([g["mgo_m"], g["n"]], axis=-1),
                         hovertemplate="%{x}<br>MgO 표준편차 %{y:.3f}<br>평균 %{customdata[0]:.2f}% · n=%{customdata[1]}<extra></extra>"))
    # 목표선은 막대·라벨 **아래**로 깔고(layer='below'), 주석은 플롯 **바깥 오른쪽**에 둔다.
    # (안 그러면 0.5 근처 막대의 값 라벨과 겹치고, 큰 막대 위에 글씨가 얹힌다)
    fig.add_hline(y=0.5, line=dict(color=GREEN, dash="dash"), layer="below")
    fig.add_annotation(x=1.0, xref="paper", xanchor="left", xshift=6, y=0.5, yref="y",
                       text="목표 0.5", showarrow=False, font=dict(color="#1d7a1d", size=11))
    ymax = float(np.nanmax([g["cao_std"].max(), g["mgo_std"].max(), 0.5]))
    fig.update_layout(title=title, barmode="group", height=360, font=dict(size=12),
                      yaxis_title="표준편차 (%p)", margin=dict(l=10, r=76, t=64, b=10),
                      yaxis=dict(range=[0, ymax * 1.18]),      # 값 라벨이 잘리지 않게 여유
                      legend=dict(orientation="h", y=1.06, yanchor="bottom",
                                  x=1, xanchor="right"))
    return fig


def _agg_std(df, group_col):
    import pandas as pd
    g = (df.groupby(group_col).agg(cao_std=("cao", "std"), mgo_std=("mgo", "std"),
                                   cao_m=("cao", "mean"), mgo_m=("mgo", "mean"), n=(group_col, "size"))
         .reset_index().rename(columns={group_col: "name"}))
    return g


def yardchange_std_summary(yc, level: str = "yard") -> go.Figure:
    """야드변경 데이터 기준 CaO·MgO 표준편차. level='yard'(Y1/Y2) 또는 'line'(기존/신설)."""
    if yc is None or len(yc) == 0:
        f = go.Figure(); f.update_layout(title="야드변경 데이터 없음", height=300); return f
    col = "yard" if level == "yard" else "line"
    order = (["기존(Y1)", "기존(Y2)", "신설(Y1)", "신설(Y2)"] if level == "yard" else ["기존", "신설"])
    g = _agg_std(yc, col)
    g = g.set_index("name").reindex([o for o in order if o in g["name"].values]).reset_index()
    unit = "야드별" if level == "yard" else "라인별"
    return _std_bar(g, f"{unit} CaO·MgO 표준편차 — 변경데이터 기준 (낮을수록 안정)")


def continuous_std_summary(yards: dict) -> go.Figure:
    """연속 야드데이터(CNA/45Q) 기준 라인별 CaO·MgO 표준편차 (실측 변동성)."""
    import pandas as pd

    rows = []
    label = {"기존": "기존(45Q)", "신설": "신설(CNA)"}
    for line in ["기존", "신설"]:
        d = yards.get(line)
        if d is None or len(d) == 0:
            continue
        rows.append(dict(name=label[line], cao_std=d["cao"].std(), mgo_std=d["mgo"].std(),
                         cao_m=d["cao"].mean(), mgo_m=d["mgo"].mean(), n=len(d)))
    g = pd.DataFrame(rows)
    return _std_bar(g, "라인별 CaO·MgO 표준편차 — 연속 야드측정(CNA/45Q) 기준")


def control_chart(times, values, lo, hi, title) -> go.Figure:
    """관리도: 최근 CaO + 규격밴드 + 통계 관리상/하한(평균±3σ) + 이탈점 강조."""
    v = np.asarray(values, dtype=float)
    fin = v[np.isfinite(v)]
    mean = float(fin.mean()) if len(fin) else TARGET
    sd = float(fin.std()) if len(fin) else 0.0
    ucl, lcl = mean + 3 * sd, mean - 3 * sd
    fig = go.Figure()
    # 기준선 라벨은 전부 플롯 **바깥 오른쪽**에 세로로 나눠 배치한다.
    # (안쪽에 두면 '규격'은 y축 눈금과, '평균'은 오른쪽 가장자리와 겹친다)
    fig.add_hrect(y0=lo, y1=hi, fillcolor=GREEN, opacity=0.10, line_width=0)
    fig.add_hline(y=mean, line=dict(color="#555", width=1))
    for y, nm in [(ucl, "UCL"), (lcl, "LCL")]:
        fig.add_hline(y=y, line=dict(color=RED, dash="dot", width=1))
    # 규격 범위는 제목에 넣고(라벨끼리 겹침 방지), 오른쪽에는 3개만 세로로 배치한다.
    # 값이 가까우면 겹치므로 위에서부터 훑으며 최소 간격(픽셀)을 강제한다.
    lab = sorted([(ucl, "UCL", "#b23"), (mean, f"평균 {mean:.2f}", "#555"),
                  (lcl, "LCL", "#b23")], key=lambda t: -t[0])
    span = max(ucl - lcl, 1e-6)
    min_gap = span * 0.09          # 이보다 가까우면 아래로 밀어낸다
    prev_y, prev_shift = None, 0
    for y, txt, col in lab:
        shift = 0
        if prev_y is not None and (prev_y - y) < min_gap:
            shift = prev_shift - 13
        fig.add_annotation(x=1.0, xref="paper", xanchor="left", xshift=6, y=y, yref="y",
                           yshift=shift, text=txt, showarrow=False,
                           font=dict(size=10, color=col))
        prev_y, prev_shift = y, shift
    fig.add_trace(go.Scatter(x=times, y=v, mode="lines+markers", name="CaO",
                             line=dict(color=BLUE, width=1.3), marker=dict(size=4)))
    oos = (v < lo) | (v > hi)
    if np.any(oos):
        fig.add_trace(go.Scatter(x=np.asarray(times)[oos], y=v[oos], mode="markers",
                      name="규격이탈", marker=dict(color=ORANGE, size=8, symbol="x")))
    # 규격 범위를 제목에 넣어 오른쪽 라벨 수를 줄인다(겹침 방지)
    ttl = title if "규격 " in title else f"{title} · 규격 {lo:g}~{hi:g}"
    fig.update_layout(title=dict(text=ttl, y=0.97, yanchor="top"),
                      height=364, font=dict(size=12), yaxis_title="CaO (%)",
                      margin=dict(l=10, r=92, t=76, b=10),   # 오른쪽은 기준선 라벨 자리
                      # 기간 버튼이 오른쪽(x=1)이므로 범례는 왼쪽에 둔다
                      legend=dict(orientation="h", y=1.02, yanchor="bottom",
                                  x=0, xanchor="left", font=dict(size=11)))
    return _time_range_controls(_korean_date_axis(fig))


def alert_history_timeline(hist) -> go.Figure:
    """경보 이력 타임라인 (수준별 색·라인별)."""
    import pandas as pd

    fig = go.Figure()
    cmap = {"경고": RED, "주의": ORANGE, "정상": GREEN}
    if hist is None or len(hist) == 0:
        fig.update_layout(title="경보 이력 없음", height=280)
        return fig
    h = hist.copy()
    h["dt"] = pd.to_datetime(h["data_time"], errors="coerce")
    for lvl, c in cmap.items():
        sub = h[h["level"] == lvl]
        if len(sub):
            fig.add_trace(go.Scatter(x=sub["dt"], y=sub["line"], mode="markers", name=lvl,
                          marker=dict(color=c, size=9, symbol="square"),
                          text=sub["message"], hovertemplate="%{x}<br>%{y}<br>%{text}<extra></extra>"))
    fig.update_layout(title="경보 이력 타임라인", height=300, font=dict(size=12),
                      margin=dict(l=10, r=10, t=44, b=10))
    return _time_range_controls(_korean_date_axis(fig))


def model_benchmark_bar(bench_df, title: str) -> go.Figure:
    """모델별 CV MAE 가로 막대. 최적=초록, 기준선=회색, 나머지=파랑. 목표(0.5)·persist 표시."""
    d = bench_df.sort_values("MAE", ascending=False)
    best_name = bench_df[~bench_df["is_baseline"]].sort_values("MAE").iloc[0]["model"]
    colors = []
    for _, r in d.iterrows():
        if r["model"] == best_name:
            colors.append(GREEN)
        elif r["is_baseline"]:
            colors.append("#9aa0a6")
        else:
            colors.append(BLUE)
    fig = go.Figure(go.Bar(
        x=d["MAE"], y=d["model"], orientation="h", marker_color=colors,
        text=[f"{v:.3f}" for v in d["MAE"]], textposition="outside",
    ))
    fig.add_vline(x=0.5, line=dict(color=GREEN, dash="dash"),
                  annotation_text="목표 0.5", annotation_position="top")
    fig.update_layout(title=title, height=430, font=dict(size=11),
                      margin=dict(l=10, r=10, t=44, b=10), xaxis_title="MAE (낮을수록 좋음)")
    return fig


def assemble_tabbed_html(title: str, tabs: list[dict], date_range: tuple | None = None) -> str:
    """여러 탭을 가진 단일 통합 HTML. tabs=[{name, sections:[(heading, Figure|html)]}].

    plotly.js 는 1회만 인라인. 탭 전환 시 숨겨진 차트를 Plotly.Plots.resize 로 재조정.
    date_range=(min, max) 지정 시 상단에 년-월-일 직접 입력 컨트롤(모든 시간축 차트 확대) 추가.
    """
    import plotly.io as pio

    state = {"first": True}

    def render(obj) -> str:
        if isinstance(obj, go.Figure):
            inc = state["first"]
            state["first"] = False
            return pio.to_html(obj, include_plotlyjs=(True if inc else False),
                               full_html=False, config={"displayModeBar": False})
        return str(obj)

    nav, panels = [], []
    for i, tab in enumerate(tabs):
        act = " active" if i == 0 else ""
        nav.append(f'<button class="tabbtn{act}" onclick="showTab({i})">{tab["name"]}</button>')
        body = []
        for heading, obj in tab["sections"]:
            if heading:
                body.append(f"<h2>{heading}</h2>")
            body.append(render(obj))
        panels.append(f'<div class="tabpanel{act}" id="tab{i}">{"".join(body)}</div>')

    dmin, dmax = (date_range or ("", ""))
    daterow = ""
    if date_range:
        daterow = (
            '<div class="daterow">📅 기간 직접설정: '
            f'<input type="date" id="drS" value="{dmin}" min="{dmin}" max="{dmax}"> ~ '
            f'<input type="date" id="drE" value="{dmax}" min="{dmin}" max="{dmax}"> '
            '<button onclick="applyRange()">적용</button>'
            '<button class="ghost" onclick="resetRange()">전체</button>'
            '<span class="hint">모든 시간축 차트가 선택 기간으로 확대됩니다</span></div>'
        )

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;margin:0;color:#1a1a1a;background:#f7f9fb}}
header{{background:#12395c;color:#fff;padding:16px 22px}}header h1{{margin:0;font-size:1.35rem}}
nav{{position:sticky;top:0;background:#fff;border-bottom:2px solid #12395c;padding:6px 10px;display:flex;flex-wrap:wrap;gap:4px;z-index:9}}
.tabbtn{{border:none;background:#eef2f6;color:#12395c;padding:9px 14px;border-radius:7px 7px 0 0;cursor:pointer;font-size:.92rem;font-weight:600}}
.tabbtn.active{{background:#12395c;color:#fff}}
.daterow{{background:#eef2f6;padding:8px 12px;display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:.9rem;border-bottom:1px solid #d5dde5}}
.daterow input[type=date]{{padding:4px 6px;border:1px solid #b9c4cf;border-radius:5px;font-size:.88rem}}
.daterow button{{background:#12395c;color:#fff;border:none;padding:5px 12px;border-radius:5px;cursor:pointer;font-weight:600}}
.daterow button.ghost{{background:#fff;color:#12395c;border:1px solid #12395c}}
.daterow .hint{{color:#667;font-size:.8rem;margin-left:6px}}
.wrap{{max-width:1060px;margin:0 auto;padding:16px}}
.tabpanel{{display:none}}.tabpanel.active{{display:block}}
h2{{color:#12395c;margin-top:26px;border-left:5px solid #1f77b4;padding-left:10px}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}th,td{{border:1px solid #ddd;padding:8px;text-align:center}}th{{background:#eef2f6}}
.ok{{background:#e8f5e9;border-left:4px solid #2ca02c;padding:10px 14px;margin:12px 0;border-radius:4px}}
.note{{background:#fff8e1;border-left:4px solid #ffb300;padding:10px 14px;margin:12px 0;border-radius:4px}}
.cap{{color:#334;font-size:.9rem;margin:2px 0 8px;background:#eef5ff;border-left:3px solid #1f77b4;padding:7px 11px;border-radius:4px;line-height:1.5}}
.exec{{border:1px solid #d5dde5;border-radius:10px;padding:4px 18px 14px;margin:6px 0 18px;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.tolbar{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0;padding:8px 12px;
background:#eef2f6;border:1px solid #d5dde5;border-radius:8px;font-size:.92rem}}
.tolbar select{{padding:5px 10px;border:1px solid #b9c4cf;border-radius:6px;font-size:.95rem;
font-weight:700;color:#12395c;background:#fff;cursor:pointer}}
.tolbar .hint{{color:#667;font-size:.82rem}}
.kpirow{{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}}
.kpi{{flex:1;min-width:150px;background:#f7f9fb;border:1px solid #e2e8ee;border-radius:8px;padding:10px 14px}}
.kpi .v{{font-size:1.5rem;font-weight:800;color:#12395c}}.kpi .l{{font-size:.82rem;color:#667}}
.muted{{color:#667;font-size:.84rem}}
.badge{{display:inline-block;font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:10px;
margin-left:8px;vertical-align:middle;white-space:nowrap}}
.badge.live{{background:#e8f5e9;color:#1d7a1d;border:1px solid #9ccc9c}}
.badge.fixed{{background:#f0f2f5;color:#5a6472;border:1px solid #c8cfd8}}
.legendbar{{background:#eef5ff;border:1px solid #cfe0f2;border-radius:8px;padding:9px 14px;
margin:10px 0 16px;font-size:.86rem;line-height:1.7}}
.glossary dt{{font-weight:700;color:#12395c;margin-top:8px}}.glossary dd{{margin:0 0 2px 12px;color:#445;font-size:.92rem}}
pre{{background:#f4f4f4;padding:12px;border-radius:6px;overflow-x:auto}}code{{background:#f4f4f4;padding:1px 5px;border-radius:3px}}</style></head>
<body><header><h1>{title}</h1></header>
<nav>{"".join(nav)}</nav>
{daterow}
<div class="wrap">{"".join(panels)}</div>
<p style="color:#888;font-size:.82rem;text-align:center;padding:14px">※ 본 리포트·데이터는 로컬 전용입니다. 외부(원격)에 발행/커밋하지 않습니다.</p>
<script>
var DR_MIN="{dmin}", DR_MAX="{dmax}";
function _timeGraphs(){{
  return [...document.querySelectorAll('.plotly-graph-div')].filter(function(g){{
    return g._fullLayout && g._fullLayout.xaxis && g._fullLayout.xaxis.type==='date';
  }});
}}
// --- Sankey 기간 재계산 (일별 집계 SANKEYAGG 로 링크 물량·색 갱신) ---
function _caoColor(v,a){{
  if(v===null||isNaN(v)){{return 'rgba(150,150,150,'+a+')';}}
  var d=Math.max(-2,Math.min(2,v-44.6))/2, r,g,b;
  if(d>=0){{r=214;g=Math.round(160-120*d);b=Math.round(120-100*d);}}
  else{{r=Math.round(60-30*d);g=Math.round(140+20*d);b=200;}}
  return 'rgba('+r+','+g+','+b+','+a+')';
}}
function _mgoColor(v,a){{
  if(v===null||isNaN(v)){{return 'rgba(150,150,150,'+a+')';}}
  var t=Math.max(0,Math.min(1,(v-2.5)/2));
  return 'rgba('+Math.round(60+180*t)+','+Math.round(160-90*t)+','+Math.round(90-40*t)+','+a+')';
}}
// 행 = [날짜, 물량, 물량×CaO, CaO유효물량, 물량×MgO, MgO유효물량]
// 품위 빈칸 행은 유효물량에서 빠지므로 분모에 남아 평균을 0쪽으로 끌지 않는다.
function _sumRows(rows,s,e){{
  var ton=0,wc=0,wtc=0,wm=0,wtm=0;
  (rows||[]).forEach(function(r){{if(r[0]>=s&&r[0]<=e){{
    ton+=r[1];wc+=r[2];wtc+=r[3];wm+=r[4];wtm+=r[5];}}}});
  return {{ton:ton, cao: wtc>0?wc/wtc:null, mgo: wtm>0?wm/wtm:null}};
}}
// 집계 키가 'YYYY-MM-DDTHH' 이므로 날짜만 넘어오면 그 날 전체를 덮도록 보정한다.
// (T00~T99 — 'T99' 는 어떤 실제 시각키보다 사전순으로 크다)
function _nrm(v,hi){{
  if(!v){{return hi?'9999':'0000';}}
  return v.length===10 ? v+(hi?'T99':'T00') : v;
}}
// 링크 키에서 라인 이름을 뽑는다. 데이터는 라인별로 완전히 구분되어 있으므로
// 구간을 고르면 '그 라인의 흐름만' 남길 수 있다.
//   야드변경 키 = '기존|기존(Y1)'      → 앞부분
//   물류 키     = '49Q|기존' / '__yard__기존' → 뒷부분
function _keyLine(k,isYC){{
  if(isYC){{return k.split('|')[0];}}
  if(k.indexOf('__yard__')===0){{return k.slice(8);}}
  var p=k.split('|'); return p.length>1?p[1]:'';
}}
function recomputeSankeys(s,e){{
  if(!window.SANKEYAGG){{return;}}
  var label=(s||'전체')+' ~ '+(e||'전체');
  s=_nrm(s,false); e=_nrm(e,true);
  document.querySelectorAll('.plotly-graph-div').forEach(function(gd){{
    var meta=gd.layout&&gd.layout.meta; if(!meta||!meta.link_keys){{return;}}
    var isYC=meta.kind==='yc_sankey';
    var store=isYC?window.SANKEYAGG.yc:window.SANKEYAGG.flow;
    var yd=window.SANKEYAGG.yard_daily||{{}};
    var vals=[],cao=[],mgo=[],hov=[],hovM=[];
    meta.link_keys.forEach(function(k,i){{
      // 구간을 고르면 그 라인의 흐름만 남긴다 (다른 라인은 같은 시간에 따로 돌던 것)
      if(window.YCLINE && _keyLine(k,isYC)!==window.YCLINE){{
        vals.push(0); cao.push(null); mgo.push(null);
        hov.push(''); hovM.push(''); return;
      }}
      // 광산도 교대 시각(49Q)·실측 시각(47Q)을 갖게 되어 다른 소스와 같은 경계를 쓴다.
      var a=_sumRows(store[k],s,e), c=a.cao, m=a.mgo;
      if(!isYC && k.indexOf('__yard__')===0){{   // 라인→야드: 색은 야드 실측 평균
        // 야드 일별행 = [날짜, CaO건수, CaO합, MgO건수, MgO합] — 성분별 건수로 나눈다
        var ln=k.replace('__yard__',''), nc=0,sc=0,nm=0,sm=0;
        (yd[ln]||[]).forEach(function(r){{if(r[0]>=s&&r[0]<=e){{
          nc+=r[1];sc+=r[2];nm+=r[3];sm+=r[4];}}}});
        c = nc>0?sc/nc:null; m = nm>0?sm/nm:null;
      }}
      vals.push(a.ton); cao.push(c); mgo.push(m);
      var lb=meta.labels?meta.labels[i]:k;
      var tt=Math.round(a.ton).toLocaleString();
      hov.push('<b>'+lb+'</b><br>물량 '+tt+'톤<br>CaO '+(c==null?'-':c.toFixed(2))+'% · MgO '+(m==null?'-':m.toFixed(2))+'%');
      hovM.push('<b>'+lb+'</b><br>물량 '+tt+'톤<br>MgO '+(m==null?'-':m.toFixed(2))+'% · CaO '+(c==null?'-':c.toFixed(2))+'%');
    }});
    var mode=gd.getAttribute('data-comp')||'CaO';
    var colors=(mode==='MgO')?mgo.map(function(v){{return _mgoColor(v,0.75);}})
                             :cao.map(function(v){{return _caoColor(v,0.55);}});
    // 야드변경 구간을 고르면 그 링크만 진하게, 나머지는 흐리게 (선택 구간 강조)
    if(isYC && window.YCHL){{
      colors=colors.map(function(c,i){{
        return meta.link_keys[i]===window.YCHL ? c.replace(/,[\\d.]+\\)$/,',0.9)')
                                               : c.replace(/,[\\d.]+\\)$/,',0.10)');
      }});
    }}
    Plotly.restyle(gd,{{'link.value':[vals],'link.color':[colors],
                       'link.customdata':[mode==='MgO'?hovM:hov]}},[0]);
    var base=(gd.layout.title&&gd.layout.title.text?gd.layout.title.text:'').split('  〔')[0];
    Plotly.relayout(gd,{{'title.text': base+'  〔'+label
                        +(window.YCLINE?' · '+window.YCLINE+' 라인만':'')+'〕'}});
  }});
}}
function applyRange(){{
  var s=document.getElementById('drS').value, e=document.getElementById('drE').value;
  if(!s||!e){{return;}}
  _timeGraphs().forEach(function(g){{Plotly.relayout(g,{{'xaxis.range':[s+' 00:00:00', e+' 23:59:59']}});}});
  if(window.recomputeSummary){{window.recomputeSummary(s,e);}}
  if(window.recomputeKPI){{window.recomputeKPI(s,e);}}
  recomputeSankeys(s,e);
}}
function resetRange(){{
  document.getElementById('drS').value=DR_MIN; document.getElementById('drE').value=DR_MAX;
  _timeGraphs().forEach(function(g){{Plotly.relayout(g,{{'xaxis.autorange':true}});}});
  if(window.recomputeSummary){{window.recomputeSummary(DR_MIN,DR_MAX);}}
  if(window.recomputeKPI){{window.recomputeKPI(DR_MIN,DR_MAX);}}
  recomputeSankeys(DR_MIN,DR_MAX);
}}
function showTab(i){{
  document.querySelectorAll('.tabpanel').forEach((p,idx)=>p.classList.toggle('active',idx===i));
  document.querySelectorAll('.tabbtn').forEach((b,idx)=>b.classList.toggle('active',idx===i));
  document.querySelectorAll('#tab'+i+' .plotly-graph-div').forEach(d=>{{if(window.Plotly)Plotly.Plots.resize(d);}});
}}
// Sankey CaO/MgO 버튼 클릭 시 현재 성분을 기록(기간 재계산이 성분 유지)
function _hookSankeyToggle(){{
  document.querySelectorAll('.plotly-graph-div').forEach(function(gd){{
    var meta=gd.layout&&gd.layout.meta; if(!meta||!meta.link_keys){{return;}}
    if(!gd.getAttribute('data-comp')){{gd.setAttribute('data-comp','CaO');}}
    if(gd._compHooked){{return;}} gd._compHooked=true;
    gd.on('plotly_buttonclicked',function(ev){{
      var lb=ev&&ev.button&&ev.button.label; if(lb==='CaO'||lb==='MgO'){{gd.setAttribute('data-comp',lb);}}
    }});
  }});
}}
window.addEventListener('load',function(){{
  showTab(0);
  if(window.recomputeSummary){{recomputeSummary(DR_MIN,DR_MAX);}}
  if(window.recomputeKPI){{recomputeKPI(DR_MIN,DR_MAX);}}
  _hookSankeyToggle();
}});
</script></body></html>"""


def assemble_html(title: str, sections: list[tuple[str, object]], tail_html: str = "") -> str:
    """섹션(제목, Figure 또는 HTML문자열)들을 자기완결 HTML 로 조립. plotly.js 1회 인라인."""
    import plotly.io as pio

    body, first = [], True
    for heading, obj in sections:
        if heading:
            body.append(f"<h2>{heading}</h2>")
        if isinstance(obj, go.Figure):
            body.append(pio.to_html(obj, include_plotlyjs=(True if first else False),
                                    full_html=False, config={"displayModeBar": False}))
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


def surge_timeline(events, cycles, capacity_ton: float = 10_000, title: str = "") -> go.Figure:
    """수항(사일로) 이벤트 타임라인 + 채움→고갈 사이클의 누적 재고 하한.

    ⚠️ **연속 재고 곡선이 아니다.** 정상 운전 중 수항으로 흘러든 양은 기록되지 않아
       전체 곡선은 만들 수 없다. 여기 그리는 것은 **'고갈' 앵커(재고≈0) 사이에서
       기록으로 확인되는 누적 채움**이며, 실제 재고의 **하한**이다.
    """
    fig = go.Figure()
    if events is None or len(events) == 0:
        fig.update_layout(title="수항 이벤트 — 데이터 없음", height=300)
        return fig

    # 사이클별 누적 채움(계단) — 고갈에서 0 으로 떨어진다
    if cycles is not None and len(cycles):
        xs, ys = [], []
        for _, c in cycles.iterrows():
            fills = events[(events["kind"] == "채움")
                           & (events["datetime"] >= c["start"])
                           & (events["datetime"] <= c["end"])].sort_values("datetime")
            acc = 0.0
            for _, f in fills.iterrows():
                xs += [f["datetime"], f["datetime"]]
                ys += [acc, acc + float(f["ton"] or 0)]
                acc += float(f["ton"] or 0)
            xs += [c["end"], c["end"], None]
            ys += [acc, 0, None]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name="기록된 누적 채움 (재고 하한)",
            line=dict(color=BLUE, width=2, shape="hv"),
            hovertemplate="%{x|%m/%d %H시}<br>누적 채움 %{y:,.0f}톤<extra></extra>"))

    ev_ton = events[events["kind"] == "채움"]
    if len(ev_ton):
        fig.add_trace(go.Scatter(
            x=ev_ton["datetime"], y=ev_ton["ton"], mode="markers", name="채움 기록",
            marker=dict(color=BLUE, size=9, symbol="triangle-up"),
            customdata=ev_ton["note"],
            hovertemplate="%{x|%m/%d %H시}<br>채움 %{y:,.0f}톤<br>%{customdata}<extra></extra>"))
    for kind, sym, col, nm in (("고갈", "x", RED, "수항재고 고갈 (재고≈0)"),
                               ("수항단독", "diamond", ORANGE, "수항 단독 생산")):
        g = events[events["kind"] == kind]
        if not len(g):
            continue
        fig.add_trace(go.Scatter(
            x=g["datetime"], y=[0] * len(g), mode="markers", name=nm,
            marker=dict(color=col, size=10, symbol=sym),
            customdata=g["note"],
            hovertemplate="%{x|%m/%d %H시}<br>" + nm + "<br>%{customdata}<extra></extra>"))

    fig.add_hline(y=capacity_ton, line=dict(color=GREEN, dash="dash", width=1.2), layer="below")
    fig.add_annotation(x=1.0, xref="paper", xanchor="left", xshift=6, y=capacity_ton, yref="y",
                       text=f"용량<br>{capacity_ton:,.0f}t", showarrow=False, align="left",
                       font=dict(size=10, color="#555"))
    fig.update_layout(
        title=dict(text=title or "수항(사일로) 이벤트 — 기록된 누적 채움은 실제 재고의 하한",
                   y=0.97, yanchor="top"),
        height=360, font=dict(size=12), margin=dict(l=10, r=86, t=88, b=10),
        yaxis_title="톤", plot_bgcolor="white",
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left",
                    font=dict(size=11)))
    return _time_range_controls(_korean_date_axis(fig))
