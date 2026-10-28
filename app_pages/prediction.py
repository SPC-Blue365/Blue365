"""강도 예측: 재령(1·3·7·28일)과 품종을 골라 결과가 나오기 전에 압축강도를 회귀 예측."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from qms import prediction as P
from qms.ui import add_limit_lines, colors, fmt, get_ctx, page_header

ctx = get_ctx()
reg, store = ctx.registry, ctx.store
page_header(ctx, "🔮 압축강도 예측 (재령별)")
st.caption("재령과 품종을 고르면, 그 재령 결과가 나오기 전에 **앞 재령 강도·분말도·SO₃·클링커 C₃S** 등으로 강도를 회귀 예측합니다. "
           "예측값은 **추정치**이며 실측으로 확정해야 합니다. 강도 자료는 출하시멘트(로트)·물성 시트에서 읽습니다.")

prods = P.products_with_strength(store)
if not prods:
    st.warning("강도 실측 로트가 부족합니다(품종별 10로트 이상 필요). 📥 데이터 관리에서 출하시멘트 강도 자료를 올려 주세요.")
    st.stop()
c1, c2 = st.columns([1.6, 1.4])
product = c1.segmented_control("품종", prods, default=prods[0], key="pa_prod") or prods[0]
age = c2.segmented_control("예측할 재령", list(P.AGES), default=28, key="pa_age", format_func=lambda a: f"{a}일") or 28
target = f"phy_s{age}"
item = reg[target]

models = P.fit_age_models(store, product, age)
if not models:
    st.warning(f"{product} {age}일 강도를 예측할 학습 자료가 부족합니다({age}일 실측 로트와 입력값이 함께 있는 로트가 더 필요).")
    st.stop()
best = models[0]
if best.n < 30:
    st.warning(f"학습 로트가 {best.n}개뿐이라 예측 신뢰도가 낮습니다(30로트 이상 권장). 참고용으로만 보세요.", icon="⚠️")

# ── 모델 ────────────────────────────────────────────────────────────────
st.subheader(f"{product} · {age}일 강도 예측 모델")
mt = pd.DataFrame([{"순위": i + 1, "모델": m.label, "입력": ", ".join(P.FEATURE_LABELS.get(f, f) for f in m.features),
                    "학습 로트": m.n, "R²": round(m.r2, 2), "오차 RMSE(LOO, MPa)": round(m.rmse, 2), "회귀식": m.equation(3)}
                   for i, m in enumerate(models)])
st.dataframe(mt, hide_index=True, width="stretch", column_config={"회귀식": st.column_config.TextColumn(width="large")})
st.caption("로트마다 입력값이 모두 있는 모델 중 **오차가 가장 작은 모델**로 예측합니다. RMSE(LOO) = 한 로트씩 빼고 학습해 예측한 오차"
           "(실제 사용 시 기대 오차에 가까움). 예측구간 = 예측값 ± 1.96×RMSE(약 95%). 자료가 갱신되면 자동 재학습됩니다.")

p = P.predict_age(store, product, age, models)
lim = item.limits_for(product)
c = colors()

# ── 추이 ────────────────────────────────────────────────────────────────
days = st.select_slider("그래프 기간", ["최근 90일", "최근 180일", "최근 1년", "전체"], value="최근 180일", key="pa_period")
span = {"최근 90일": 90, "최근 180일": 180, "최근 1년": 365}.get(days)
pv = p if span is None else p[p["timestamp"] >= p["timestamp"].max() - pd.Timedelta(days=span)]
past, fut = pv[pv["status"] == "실측"], pv[pv["status"] == "미도래"]
fig = go.Figure()
fig.add_trace(go.Scatter(x=past["timestamp"], y=past["actual"], mode="lines+markers", name=f"{age}일 실측",
                         line=dict(color=c["series"], width=2), marker=dict(size=6)))
fig.add_trace(go.Scatter(x=past["timestamp"], y=past["loo_pred"], mode="lines", name="예측(실측 로트, 검증용)",
                         line=dict(color=c["pred"], width=1.5, dash="dot")))
if len(fut):
    fig.add_trace(go.Scatter(x=pd.concat([fut["timestamp"], fut["timestamp"][::-1]]),
                             y=pd.concat([fut["pred_hi"], fut["pred_lo"][::-1]]), fill="toself", fillcolor=c["band"],
                             line=dict(width=0), name="예측구간(95%)", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fut["timestamp"], y=fut["pred"], mode="lines+markers", name="예측(결과 미도래)",
                             line=dict(color=c["pred"], width=2, dash="dash"), marker=dict(size=9)))
add_limit_lines(fig, item, product)
fig.update_layout(height=420, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), yaxis_title="MPa",
                  legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
st.plotly_chart(fig, key="pa_fig")


def _judge(v, lo):
    if not np.isfinite(v):
        return "-"
    if lim.ks_min is not None and v < lim.ks_min:
        return "🔴 KS 미달 예측"
    if lim.lsl is not None and v < lim.lsl:
        return "🟠 사내기준 미달 예측"
    if lim.lsl is not None and np.isfinite(lo) and lo < lim.lsl:
        return "🟡 하한 근접(구간 하단 미달)"
    return "🟢 양호" if (lim.lsl is not None or lim.ks_min is not None) else "기준 미설정"


# ── 미도래 로트 ─────────────────────────────────────────────────────────
st.subheader(f"{age}일 결과가 아직 없는 로트")
fut_all = p[p["status"] == "미도래"].sort_values("timestamp", ascending=False)
if len(fut_all):
    t = fut_all.assign(판정=[_judge(v, lo) for v, lo in zip(fut_all["pred"], fut_all["pred_lo"])],
                       결과예정일=fut_all["timestamp"] + pd.Timedelta(days=age))
    t = t.rename(columns={"timestamp": "채취일", "pred": f"예측 {age}일(MPa)", "pred_lo": "구간 하한", "pred_hi": "구간 상한",
                          "model": "사용 모델"})[["채취일", "결과예정일", f"예측 {age}일(MPa)", "구간 하한", "구간 상한", "사용 모델", "판정"]]
    st.dataframe(t, hide_index=True, width="stretch", column_config={
        "채취일": st.column_config.DatetimeColumn(format="YYYY-MM-DD"), "결과예정일": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
        **{k: st.column_config.NumberColumn(format="%.1f") for k in (f"예측 {age}일(MPa)", "구간 하한", "구간 상한")}})
    std = " · ".join(x for x in (f"KS {lim.ks_min:g}" if lim.ks_min is not None else "", f"사내 하한 {lim.lsl:g}" if lim.lsl is not None else "") if x)
    st.caption(f"판정 기준: {std or '기준 미설정(⚙️ 기준·알림 설정 또는 🚢 출하시멘트 관리기준에서 입력)'} MPa · 예측값이 기준 근처면 실측으로 꼭 확인하세요.")
else:
    st.info(f"{age}일 결과를 기다리는 로트가 없습니다(최근 로트의 {age}일 결과가 모두 나왔습니다).")

# ── 직접 입력해 예측 ────────────────────────────────────────────────────
with st.expander("✍️ 값을 직접 넣어 예측하기 (예: 오늘 나온 3일·7일 강도로 28일 미리 보기)", expanded=False):
    mi = st.selectbox("모델", range(len(models)), format_func=lambda i: f"{models[i].label} (오차 ±{1.96 * models[i].rmse:.1f} MPa)",
                      key=f"pa_model_{product}_{age}")
    m = models[mi]
    df_f = P.age_feature_frame(store, product)
    last = df_f.dropna(subset=m.features).tail(1)
    cols = st.columns(min(len(m.features), 4) or 1)
    vals = []
    for i, f in enumerate(m.features):
        v0 = float(last[f].iloc[0]) if len(last) else float(df_f[f].median())
        step = 10.0 if f == "f_blaine" else 0.1
        vals.append(cols[i % len(cols)].number_input(P.FEATURE_LABELS.get(f, f), value=round(v0, 2), step=step,
                                                     key=f"pa_in_{product}_{age}_{m.code}_{f}"))
    yv = float(m.predict(np.array([vals], float))[0])
    lo, hi = yv - 1.96 * m.rmse, yv + 1.96 * m.rmse
    r1, r2 = st.columns([1, 2])
    r1.metric(f"예측 {age}일 강도", fmt(yv, 1, "MPa"), delta=f"95% 구간 {lo:.1f} ~ {hi:.1f}", delta_color="off", delta_arrow="off")
    r2.markdown(f"**판정:** {_judge(yv, lo)}  \n기본값은 가장 최근 로트의 실제 값입니다. 학습 범위를 크게 벗어난 값을 넣으면 예측이 맞지 않습니다(외삽, 추정).")

# ── 적합도 ──────────────────────────────────────────────────────────────
st.subheader(f"모델 검증 — 실측 vs 예측 ({best.label})")
ok = p["status"].eq("실측") & p["loo_pred"].notna()
pp = p[ok]
if len(pp):
    resid_z = (pp["actual"] - pp["loo_pred"]) / best.rmse
    sc = go.Figure()
    sc.add_trace(go.Scatter(x=pp["loo_pred"], y=pp["actual"], mode="markers", marker=dict(size=7, color=c["series"], opacity=0.7),
                            text=pp["timestamp"].dt.strftime("%Y-%m-%d"), name="로트",
                            hovertemplate="%{text}<br>예측 %{x:.1f} / 실측 %{y:.1f}<extra></extra>"))
    lo_, hi_ = float(min(pp["loo_pred"].min(), pp["actual"].min())) - 1, float(max(pp["loo_pred"].max(), pp["actual"].max())) + 1
    sc.add_trace(go.Scatter(x=[lo_, hi_], y=[lo_, hi_], mode="lines", line=dict(color=c["cl"], dash="dash", width=1), name="예측 = 실측"))
    out = pp[resid_z.abs() >= 2]
    if len(out):
        sc.add_trace(go.Scatter(x=out["loo_pred"], y=out["actual"], mode="markers",
                                marker=dict(size=12, color="rgba(0,0,0,0)", line=dict(color=c["violation"], width=2)),
                                name="|잔차| ≥ 2σ (시험오차·특이 로트 의심)"))
    sc.update_layout(height=380, xaxis_title=f"예측 {age}일 (MPa, LOO)", yaxis_title=f"{age}일 실측 (MPa)",
                     margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.05))
    st.plotly_chart(sc, key="pa_scatter")
    within = float((resid_z.abs() < 1.96).mean() * 100)
    st.caption(f"검증 {len(pp)}로트 중 {within:.0f}%가 예측구간(±1.96×RMSE) 안에 들어왔습니다. "
               + (f"빨간 원 {len(out)}로트: 앞 재령 강도로 설명되지 않는 결과 — 양생·시험 조건 확인 대상: "
                  + ", ".join(out.sort_values("timestamp", ascending=False)["timestamp"].dt.strftime("%m/%d").head(10)) if len(out) else ""))
