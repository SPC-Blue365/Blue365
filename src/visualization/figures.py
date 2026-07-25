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
    return _time_range_controls(_korean_date_axis(fig))


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


def build_tracking_sankey(mine, osp_exp, yards) -> go.Figure:
    """광산→라인→야드 추적 Sankey (원시 정제 데이터에서 흐름 계산)."""
    import pandas as pd

    from config import schema as S

    labels = ["49Q 광산(XRF)", "47Q 광산(감마)", "기존 라인", "신설 라인", "45Q 야드(4-5K)", "CNA 야드(6-7K)"]
    node_colors = ["#6baed6", "#9ecae1", "#f4a582", "#fdae61", "#74c476", "#31a354"]
    src, tgt, val, lc, hov = [], [], [], [], []
    smap, lmap, ymap = {"49Q": 0, "47Q": 1}, {S.LINE_OLD: 2, S.LINE_NEW: 3}, {S.LINE_OLD: 4, S.LINE_NEW: 5}
    mm = mine[mine["line"].isin([S.LINE_OLD, S.LINE_NEW])]
    for (so, ln), g in mm.groupby(["source", "line"]):
        ton, cao = g["tonnage"].sum(min_count=1), g["cao"].mean()
        if pd.isna(ton) or ton <= 0:
            continue
        src.append(smap[so]); tgt.append(lmap[ln]); val.append(float(ton)); lc.append(grade_color(cao))
        hov.append(f"{labels[smap[so]]} → {labels[lmap[ln]]}<br>이송 {ton:,.0f}톤 · 평균 CaO {cao:.2f}%")
    for ln in [S.LINE_OLD, S.LINE_NEW]:
        ton = osp_exp.loc[osp_exp["line"] == ln, "withdrawn_ton"].sum(min_count=1)
        ycao = yards[ln]["cao"].mean()
        if pd.isna(ton) or ton <= 0:
            continue
        src.append(lmap[ln]); tgt.append(ymap[ln]); val.append(float(ton)); lc.append(grade_color(ycao))
        hov.append(f"{labels[lmap[ln]]} → {labels[ymap[ln]]}<br>인출 {ton:,.0f}톤 · 야드 CaO {ycao:.2f}%")
    return sankey_tracking(labels, node_colors, src, tgt, val, lc, hov)


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
             cao=np.average(d["cao"], weights=d["tonnage"]) if d["tonnage"].sum() else np.nan,
             mgo=np.average(d["mgo"], weights=d["tonnage"]) if d["tonnage"].sum() else np.nan,
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

    start_c, start_h = (cao_c, cao_h) if default == "CaO" else (mgo_c, mgo_h)
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, color=node_colors, pad=24, thickness=26,
                  line=dict(color="rgba(0,0,0,0.25)", width=1)),
        link=dict(source=src, target=tgt, value=val, color=start_c, customdata=start_h,
                  hovertemplate="%{customdata}<extra></extra>"),
    ))
    fig.update_layout(
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
    fig.add_hline(y=0.5, line=dict(color=GREEN, dash="dash"),
                  annotation_text="목표 CaO 표준편차 0.5", annotation_position="top right")
    fig.update_layout(title=title, barmode="group", height=360, font=dict(size=12),
                      yaxis_title="표준편차 (%p)", margin=dict(l=10, r=10, t=46, b=10),
                      legend=dict(orientation="h", y=1.14, x=1, xanchor="right"))
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
    fig.add_hrect(y0=lo, y1=hi, fillcolor=GREEN, opacity=0.10, line_width=0,
                  annotation_text="규격", annotation_position="top left")
    fig.add_hline(y=mean, line=dict(color="#555", width=1), annotation_text=f"평균 {mean:.2f}")
    for y, nm in [(ucl, "UCL"), (lcl, "LCL")]:
        fig.add_hline(y=y, line=dict(color=RED, dash="dot", width=1), annotation_text=nm)
    fig.add_trace(go.Scatter(x=times, y=v, mode="lines+markers", name="CaO",
                             line=dict(color=BLUE, width=1.3), marker=dict(size=4)))
    oos = (v < lo) | (v > hi)
    if np.any(oos):
        fig.add_trace(go.Scatter(x=np.asarray(times)[oos], y=v[oos], mode="markers",
                      name="규격이탈", marker=dict(color=ORANGE, size=8, symbol="x")))
    fig.update_layout(title=title, height=340, font=dict(size=12), yaxis_title="CaO (%)",
                      margin=dict(l=10, r=10, t=44, b=10),
                      legend=dict(orientation="h", y=1.12, x=1, xanchor="right"))
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
.kpirow{{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}}
.kpi{{flex:1;min-width:150px;background:#f7f9fb;border:1px solid #e2e8ee;border-radius:8px;padding:10px 14px}}
.kpi .v{{font-size:1.5rem;font-weight:800;color:#12395c}}.kpi .l{{font-size:.82rem;color:#667}}
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
function applyRange(){{
  var s=document.getElementById('drS').value, e=document.getElementById('drE').value;
  if(!s||!e){{return;}}
  _timeGraphs().forEach(function(g){{Plotly.relayout(g,{{'xaxis.range':[s+' 00:00:00', e+' 23:59:59']}});}});
}}
function resetRange(){{
  document.getElementById('drS').value=DR_MIN; document.getElementById('drE').value=DR_MAX;
  _timeGraphs().forEach(function(g){{Plotly.relayout(g,{{'xaxis.autorange':true}});}});
}}
function showTab(i){{
  document.querySelectorAll('.tabpanel').forEach((p,idx)=>p.classList.toggle('active',idx===i));
  document.querySelectorAll('.tabbtn').forEach((b,idx)=>b.classList.toggle('active',idx===i));
  document.querySelectorAll('#tab'+i+' .plotly-graph-div').forEach(d=>{{if(window.Plotly)Plotly.Plots.resize(d);}});
}}
window.addEventListener('load',()=>showTab(0));
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
