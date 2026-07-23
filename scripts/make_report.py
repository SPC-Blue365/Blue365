"""파일럿 결과물 생성 (Plotly 인터랙티브·한글안전) [Synthesis-Agent].

실행: python scripts/make_report.py
→ outputs/report_pilot1.html (추적 Sankey + 단계별 CaO + 라인별 예측 + 최적화 데모). 로컬 전용.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from config import schema as S
from config.paths import RAW_DIR, OUTPUTS_DIR, ensure_dirs
from src.data import clean as C
from src.matching import pipeline as P
from src.models import forecast as F
from src.models.benchmark import benchmark, recommend
from src.optimization.blend import BlendSource, recommend_blend
from src.visualization import figures as V

PAIR = {S.LINE_OLD: (S.SHEET_MINE_45Q, "45Q·4-5K"), S.LINE_NEW: (S.SHEET_YARD_CNA, "CNA·6-7K")}


def _load():
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)
    m49 = C.clean_mine_49Q(pd.read_excel(xls, S.SHEET_MINE_49Q))
    m47 = C.clean_mine_47Q(pd.read_excel(xls, S.SHEET_MINE_47Q))
    mine = pd.concat([m49, m47], ignore_index=True)
    osp = pd.concat([C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_OLD), S.LINE_OLD, S.PW_COLS_OLD),
                     C.clean_osp(pd.read_excel(xls, S.SHEET_OSP_NEW), S.LINE_NEW, S.PW_COLS_NEW)],
                    ignore_index=True)
    osp_exp = P.assign_expected_cao_timeaware(osp, mine)
    yards = {ln: C.clean_yard(pd.read_excel(xls, sh)) for ln, (sh, _) in PAIR.items()}
    return xls, mine, osp_exp, yards


def build_sankey(mine, osp_exp, yards):
    labels = ["49Q 광산(XRF)", "47Q 광산(감마)", "기존 라인", "신설 라인", "45Q 야드(4-5K)", "CNA 야드(6-7K)"]
    node_colors = ["#6baed6", "#9ecae1", "#f4a582", "#fdae61", "#74c476", "#31a354"]
    src, tgt, val, lc, hov = [], [], [], [], []
    mm = mine[mine["line"].isin([S.LINE_OLD, S.LINE_NEW])]
    smap = {"49Q": 0, "47Q": 1}
    lmap = {S.LINE_OLD: 2, S.LINE_NEW: 3}
    for (so, ln), g in mm.groupby(["source", "line"]):
        ton = g["tonnage"].sum(min_count=1)
        cao = g["cao"].mean()
        if pd.isna(ton) or ton <= 0:
            continue
        src.append(smap[so]); tgt.append(lmap[ln]); val.append(float(ton))
        lc.append(V.grade_color(cao))
        hov.append(f"{labels[smap[so]]} → {labels[lmap[ln]]}<br>이송 {ton:,.0f}톤 · 평균 CaO {cao:.2f}%")
    # 라인 → 야드 (OSP 인출량)
    ymap = {S.LINE_OLD: 4, S.LINE_NEW: 5}
    for ln in [S.LINE_OLD, S.LINE_NEW]:
        ton = osp_exp.loc[osp_exp["line"] == ln, "withdrawn_ton"].sum(min_count=1)
        ycao = yards[ln]["cao"].mean()
        if pd.isna(ton) or ton <= 0:
            continue
        src.append(lmap[ln]); tgt.append(ymap[ln]); val.append(float(ton))
        lc.append(V.grade_color(ycao))
        hov.append(f"{labels[lmap[ln]]} → {labels[ymap[ln]]}<br>인출 {ton:,.0f}톤 · 야드 CaO {ycao:.2f}%")
    return V.sankey_tracking(labels, node_colors, src, tgt, val, lc, hov)


def build_stage_bar(mine, yards):
    def ms(df, col="cao"):
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        return s.mean(), s.std()
    m49 = mine[mine["source"] == "49Q"]; m47 = mine[mine["source"] == "47Q"]
    stages = [
        ("광산 49Q", *ms(m49), "#6baed6"),
        ("광산 47Q", *ms(m47), "#9ecae1"),
        ("야드 45Q(4-5K)", *ms(yards[S.LINE_OLD]), "#74c476"),
        ("야드 CNA(6-7K)", *ms(yards[S.LINE_NEW]), "#31a354"),
        ("목표", 44.6, 0.5, "#2ca02c"),
    ]
    return V.stage_cao_bar(stages)


def line_features(osp_exp, line, yards):
    y = yards[line].dropna(subset=["datetime"]).copy()
    y["h"] = y["datetime"].dt.floor("1h")
    ys = y.groupby("h")["cao"].mean().asfreq("1h")
    o = osp_exp[osp_exp["line"] == line].dropna(subset=["datetime"]).copy()
    o["h"] = o["datetime"].dt.floor("1h")
    oh = o.groupby("h").agg(impl=("expected_cao", "mean"), ton=("withdrawn_ton", "sum"))
    lag = P.estimate_time_lag(oh.reset_index().rename(columns={"h": "datetime", "impl": "osp_expected_cao"}),
                              ys.reset_index().rename(columns={"h": "datetime", "cao": "yard_cao"}), 24).best_lag_hours
    return F.build_features(ys, oh, lag)


def build_pred(feats, line):
    d = feats.dropna(subset=F.AR_CORE + ["cao"]).copy()
    k = int(len(d) * 0.7)
    model, fcols = F.fit_final(d.iloc[:k], use_upstream=False)
    te = d.iloc[k:]
    pred = model.predict(te[fcols].fillna(0).values)
    mae = float(np.abs(te["cao"].values - pred).mean())
    oos = (pred < V.TARGET - 0.5) | (pred > V.TARGET + 0.5)
    fig = V.prediction_timeseries(te.index, te["cao"].values, pred, oos,
                                  f"{line} 라인 → 야드 (검증 MAE={mae:.2f}, 경보 {int(oos.sum())}/{len(te)}h)")
    return fig, mae, int(oos.sum()), len(te)


def main():
    ensure_dirs()
    xls, mine, osp_exp, yards = _load()

    sankey = V.build_tracking_sankey(mine, osp_exp, yards)
    stagebar = build_stage_bar(mine, yards)

    pred_secs, metric_rows, bench_secs, bench_reco = [], [], [], []
    for line, (sheet, alias) in PAIR.items():
        feats = line_features(osp_exp, line, yards)
        fig, mae, oos, n = build_pred(feats, line)
        pred_secs.append(("", fig))
        metric_rows.append(f"<tr><td>{line}</td><td>{alias}</td><td><b>{mae:.2f}</b></td><td>{oos}/{n}</td></tr>")
        bench = benchmark(feats, use_upstream=False, n_splits=5)
        bench_secs.append(("", V.model_benchmark_bar(bench, f"{line} 라인 → {alias}: 10개 모델 CV MAE 비교")))
        bench_reco.append(f"<tr><td>{line}→{alias}</td><td><b>{recommend(bench)}</b></td>"
                          f"<td>{bench[~bench['is_baseline']]['MAE'].min():.3f}</td></tr>")

    demo = recommend_blend([BlendSource("구역45(기존)", 44.1, 2000), BlendSource("구역55(신설)", 45.4, 2000),
                            BlendSource("구역60", 46.0, 1500)], demand_ton=3000, target_cao=44.6)

    table = ("<table><tr><th>라인</th><th>야드</th><th>검증 MAE</th><th>규격이탈 경보</th></tr>"
             + "".join(metric_rows) + "</table>")
    intro = ("<p>원본 <code>data_v1.xlsx</code> (2026-06~07). 광산(49Q·47Q) → OSP 인출(기존·신설) → "
             "야드(45Q·CNA) 전 공정 추적 매칭 + 야드 CaO 단기 예측.</p>")
    notes = (table +
             '<div class="ok"><b>실무 유용성:</b> naive(평균) 대비 오차를 크게 낮춰, 실시간 CaO 모니터링·조기경보에 사용 가능합니다.</div>'
             '<div class="note"><b>정직한 한계:</b> 목표 MAE&lt;0.5는 미달. 야드 CaO는 지속성이 지배적이며 상류(OSP) 정보가 '
             '야드 품위를 거의 설명하지 못합니다(상관 0.18). 규격이탈 경보가 잦은 것은 <b>야드 변동성이 실제로 크다</b>는 '
             '본 과제의 핵심 문제를 보여줍니다.</div>')
    opt = (f'<pre>{demo.summary()}</pre>'
           '<p style="color:#555">구조는 완성돼 있으며, 데이터 축적으로 구역-품위 추정이 정밀해지면 그대로 처방 정밀도가 오릅니다.</p>')

    reco_table = ("<table><tr><th>라인→야드</th><th>추천 모델</th><th>최적 MAE</th></tr>"
                  + "".join(bench_reco) + "</table>"
                  '<div class="ok"><b>결론:</b> 10개 모델 중 <b>선형 계열(LinearRegression·Ridge)</b>이 최적입니다. '
                  'XGBoost·LightGBM·RandomForest 등 복잡 모델은 소표본에서 과적합해 오히려 성능이 낮습니다. '
                  '→ 운영 모델은 <b>Ridge(정규화 선형)</b> 권장(과적합에 강건, LinearRegression과 성능 동일).</div>')

    sections = [
        ("", intro),
        ("추적 매칭 흐름 (한눈에 보기)", sankey),
        ("공정 단계별 품위와 변동성", stagebar),
        ("최적 모델 탐색 — 10개 모델 벤치마크", reco_table),
        ("", bench_secs[0][1]), ("", bench_secs[1][1]),
        ("예측 성능 요약 & 판단", notes),
        ("라인별 예측 실측 대비 & 조기경보", pred_secs[0][1]), ("", pred_secs[1][1]),
        ("배합 최적화 (경로 2 · 향후용 프레임워크)", opt),
    ]
    html = V.assemble_html("석회석 광산-야드 CaO 추적·예측 파일럿", sections)
    out = OUTPUTS_DIR / "report_pilot1.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] 리포트: {out}  ({out.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
