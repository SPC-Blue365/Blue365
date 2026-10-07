"""28일 강도 조기 예측."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from qms.prediction import FEATURE_LABELS, predict
from qms.ui import add_limit_lines, colors, get_ctx, sidebar

ctx = get_ctx()
sidebar(ctx)
reg, store = ctx.registry, ctx.store
st.title("🔮 28일 압축강도 조기 예측")
st.caption("28일 결과가 나오기 전에 조기강도(1·3·7일)·분말도·SO₃·클링커 C₃S로 28일 강도를 회귀 예측합니다. "
           "예측값은 **추정치**이며 실측으로 확정해야 합니다.")

product = st.segmented_control("품종", ["1종", "3종"], default="1종", key="pred_prod") or "1종"
models = ctx.models.get(product, {})
if not models:
    st.warning("학습 가능한 데이터가 부족합니다(28일 실측 로트가 더 필요).")
    st.stop()

st.subheader("예측 모델")
mt = pd.DataFrame([{"모델": m.label, "입력 변수": ", ".join(FEATURE_LABELS.get(f, f) for f in m.features), "학습 로트": m.n,
                    "R²": round(m.r2, 3), "RMSE(LOO, MPa)": round(m.rmse, 2), "회귀식": m.equation(3)}
                   for m in models.values()])
st.dataframe(mt, hide_index=True, column_config={"회귀식": st.column_config.TextColumn(width="large")})
st.caption("RMSE(LOO): 한 로트씩 빼고 학습해 예측한 오차 — 실제 사용 시 기대 오차에 가깝습니다. "
           "예측구간 = 예측값 ± 1.96×RMSE(약 95%). 모델은 데이터가 갱신될 때마다 자동 재학습됩니다.")

p = predict(store, product, models)
lim = reg["phy_s28"].limits_for(product)
c = colors()
fig = go.Figure()
fut = p[p["s28_actual"].isna()]
past = p[p["s28_actual"].notna()]
fig.add_trace(go.Scatter(x=past["timestamp"], y=past["s28_actual"], mode="lines+markers", name="28일 실측",
                         line=dict(color=c["series"], width=2), marker=dict(size=8)))
fig.add_trace(go.Scatter(x=past["timestamp"], y=past["s28_pred"], mode="lines", name="예측(실측 로트, 검증용)",
                         line=dict(color=c["pred"], width=1.5, dash="dot")))
if len(fut):
    fig.add_trace(go.Scatter(x=pd.concat([fut["timestamp"], fut["timestamp"][::-1]]),
                             y=pd.concat([fut["pred_hi"], fut["pred_lo"][::-1]]), fill="toself", fillcolor=c["band"],
                             line=dict(width=0), name="예측구간(95%)", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fut["timestamp"], y=fut["s28_pred"], mode="lines+markers", name="예측(미도래)",
                             line=dict(color=c["pred"], width=2, dash="dash"), marker=dict(size=8)))
add_limit_lines(fig, reg["phy_s28"], product)
fig.update_layout(height=420, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), yaxis_title="MPa",
                  legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
st.plotly_chart(fig, key="pred_fig")

st.subheader("미도래 로트 예측 결과")
if len(fut):
    t = fut.copy()
    t["판정"] = np.where(t["s28_pred"] < lim.ks_min, "🔴 KS 미달 예측",
                       np.where(t["s28_pred"] < lim.lsl, "🟠 사내기준 미달 예측",
                                np.where(t["pred_lo"] < lim.lsl, "🟡 하한 근접(구간 하단 미달)", "🟢 양호")))
    t = t.rename(columns={"timestamp": "생산일", "s28_pred": "예측 28일(MPa)", "pred_lo": "구간 하한", "pred_hi": "구간 상한",
                          "model": "사용 모델"})[["생산일", "예측 28일(MPa)", "구간 하한", "구간 상한", "사용 모델", "판정"]]
    st.dataframe(t.sort_values("생산일", ascending=False), hide_index=True, column_config={
        "생산일": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
        "예측 28일(MPa)": st.column_config.NumberColumn(format="%.1f"),
        "구간 하한": st.column_config.NumberColumn(format="%.1f"),
        "구간 상한": st.column_config.NumberColumn(format="%.1f")})
    n_bad = int((fut["s28_pred"] < lim.lsl).sum())
    if n_bad:
        st.error(f"{n_bad}개 로트가 사내 관리기준({lim.lsl:g} MPa) 미달로 예측됩니다. 🧪 원인 진단에서 '28일 강도(예측)' 이벤트를 확인하세요.")
else:
    st.info("미도래 로트가 없습니다.")

st.subheader("모델 적합도 (실측 vs 7일 강도 기반 예측)")
m7 = models.get("M7")
if m7 is not None and len(past):
    ok = past["resid_z"].notna()
    pp = past[ok]
    yhat = pp["s28_actual"] - pp["resid_z"] * m7.rmse
    sc = go.Figure()
    sc.add_trace(go.Scatter(x=yhat, y=pp["s28_actual"], mode="markers", marker=dict(size=9, color=c["series"]),
                            text=pp["timestamp"].dt.strftime("%Y-%m-%d"), name="로트",
                            hovertemplate="%{text}<br>예측 %{x:.1f} / 실측 %{y:.1f}<extra></extra>"))
    lo, hi = float(np.nanmin([yhat.min(), pp["s28_actual"].min()])) - 1, float(np.nanmax([yhat.max(), pp["s28_actual"].max()])) + 1
    sc.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", line=dict(color=c["cl"], dash="dash", width=1), name="y=x"))
    out = pp[pp["resid_z"].abs() >= 2]
    if len(out):
        sc.add_trace(go.Scatter(x=(out["s28_actual"] - out["resid_z"] * m7.rmse), y=out["s28_actual"], mode="markers",
                                marker=dict(size=13, color="rgba(0,0,0,0)", line=dict(color=c["violation"], width=2)),
                                name="|잔차| ≥ 2σ (시험오차 의심)"))
    sc.update_layout(height=380, xaxis_title="7일 강도 기반 예측 (MPa)", yaxis_title="28일 실측 (MPa)",
                     margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.05))
    st.plotly_chart(sc, key="pred_scatter")
    if len(out):
        st.caption("빨간 원: 조기강도로 설명되지 않는 28일 결과(|잔차| ≥ 2σ) — 양생·시험 조건 확인 대상: "
                   + ", ".join(out["timestamp"].dt.strftime("%m/%d")))
