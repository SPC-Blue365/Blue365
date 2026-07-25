"""최종 통합 리포트 (3종 종합, 탭 단일 HTML) [Synthesis-Agent].

실행: python scripts/make_final_report.py → outputs/final_report.html (로컬 전용)
탭: 개요 · 추적 흐름 · 변경일자별 추이 · 예측·모델 · 관리도 · 모니터·경보 · 배합 최적화
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from config import schema as S
from config.paths import OUTPUTS_DIR, ensure_dirs
from src.models import forecast as F
from src.models.benchmark import benchmark, recommend
from src.models.dataset import build_line_data, filter_period, load_sources, load_yard_change
from src.monitoring import monitor_line
from src.monitoring.alerts import AlertConfig, Level
from src.optimization.blend import BlendSource, recommend_blend
from src.visualization import figures as V

BADGE = {Level.GREEN: ("🟢", "정상"), Level.YELLOW: ("🟡", "주의"), Level.RED: ("🔴", "경고")}


def _line_feats(osp_exp, yards, line):
    ld = build_line_data(osp_exp, yards, line)
    return ld.features


def main(start=None, end=None):
    ensure_dirs()
    mine, osp_exp, yards = load_sources()
    yc = load_yard_change()
    # 기간 필터 (--start/--end). 지정 시 해당 구간으로 모든 산출물 재계산.
    if start or end:
        yc = filter_period(yc, start, end, "datetime")
        yards = {ln: filter_period(df, start, end, "datetime") for ln, df in yards.items()}
    period_txt = ""
    if start or end:
        period_txt = f" · 기간 {start or '처음'}~{end or '끝'}"
    lines = {ln: build_line_data(osp_exp, yards, ln) for ln in S.YARD_PAIR}
    cfg = AlertConfig()
    statuses = {ln: monitor_line(ld, cfg) for ln, ld in lines.items()}

    # ── 예측·벤치마크 ──
    pred_secs, bench_secs, ctrl_secs, metric_rows, reco_rows, kpi_rows = [], [], [], [], [], []
    for ln, ld in lines.items():
        feats = ld.features
        d = feats.dropna(subset=F.AR_CORE + ["cao"])
        k = int(len(d) * 0.7)
        model, fcols = F.fit_final(d.iloc[:k])
        te = d.iloc[k:]
        pr = model.predict(te[fcols].fillna(0).values)
        mae = float(np.abs(te["cao"].values - pr).mean())
        oos = (pr < V.TARGET - 0.5) | (pr > V.TARGET + 0.5)
        pred_secs.append(("", V.prediction_timeseries(te.index, te["cao"].values, pr, oos,
                          f"{ln} → {ld.alias} · 검증 MAE={mae:.2f}")))
        metric_rows.append(f"<tr><td>{ln}</td><td>{ld.alias}</td><td><b>{mae:.2f}</b></td></tr>")
        bench = benchmark(feats, use_upstream=False)
        bench_secs.append(("", V.model_benchmark_bar(bench, f"{ln} → {ld.alias}: 10개 모델 CV MAE")))
        reco_rows.append(f"<tr><td>{ln}→{ld.alias}</td><td><b>{recommend(bench)}</b></td>"
                         f"<td>{bench[~bench['is_baseline']]['MAE'].min():.3f}</td></tr>")
        st = statuses[ln]
        act = st.series["actual"].values
        fin = act[np.isfinite(act)]
        insp = float(np.mean((fin >= cfg.lo) & (fin <= cfg.hi)) * 100) if len(fin) else 0.0
        kpi_rows.append(f"<tr><td>{ln}→{ld.alias}</td><td>{insp:.0f}%</td></tr>")
        ctrl_secs.append(("", V.control_chart(st.series["datetime"], act, cfg.lo, cfg.hi,
                          f"{ln} → {ld.alias} 관리도 (규격내 {insp:.0f}%)")))

    # ── 개요 지표 ──
    ycna = yards[S.LINE_NEW]["cao"]; y45 = yards[S.LINE_OLD]["cao"]
    overview = (
        "<p>광산 → OSP → 야드 전 공정 CaO 추적 매칭 + 예측·모니터링 통합 리포트. "
        "원본 <code>data_v1.xlsx</code>(야드변경 포함 8시트).</p>"
        "<table><tr><th>항목</th><th>값</th></tr>"
        f"<tr><td>품질 목표</td><td>CaO {S.TARGET.cao_mean}±{S.TARGET.tol}%</td></tr>"
        f"<tr><td>야드 CNA(신설) 평균/표준편차</td><td>{ycna.mean():.2f} / {ycna.std():.2f}</td></tr>"
        f"<tr><td>야드 45Q(기존) 평균/표준편차</td><td>{y45.mean():.2f} / {y45.std():.2f}</td></tr>"
        f"<tr><td>확정 예측모델</td><td>Ridge (선형, AR 피처)</td></tr>"
        "</table>"
        '<div class="ok"><b>핵심:</b> 평균은 목표에 근접, 과제는 <b>변동성(표준편차) 축소</b>. '
        '예측·관리도·경보로 모니터링, 야드변경 추적으로 흐름 파악.</div>'
        '<div class="note"><b>정직한 한계:</b> 상류(OSP)가 야드 CaO를 거의 설명하지 못해(상관 0.18) '
        '예측은 지속성(AR) 기반. 목표 MAE&lt;0.5 미달 — 데이터 축적 시 개선.</div>')

    # ── 배합 최적화 데모 ──
    demo = recommend_blend([BlendSource("구역45(기존)", 44.1, 2000), BlendSource("구역55(신설)", 45.4, 2000),
                            BlendSource("구역60", 46.0, 1500)], demand_ton=3000, target_cao=S.TARGET.cao_mean)

    # ── 모니터 상태 카드 ──
    cards = []
    for ln, st in statuses.items():
        icon, label = BADGE[st.level]
        al = "".join(f"<li>[{a.level.label}] {a.message}</li>" for a in st.alerts) or "<li>경보 없음</li>"
        cards.append(f'<div class="note" style="border-color:#12395c"><b>{icon} {ln} → {st.alias} · {label}</b>'
                     f'<br>최신 CaO {st.latest_actual:.2f}% (예측 {st.latest_pred:.2f}) · 최근 MAE {st.recent_mae:.2f}'
                     f'<ul>{al}</ul></div>')

    tabs = [
        {"name": "📋 개요", "sections": [("프로젝트 개요 & 핵심 지표", overview)]},
        {"name": "🌊 추적 흐름", "sections": [
            ("야드 변경 타임라인 (언제 어느 야드로) — CaO/MgO 버튼", V.yardchange_gantt(yc, "CaO")),
            ("야드변경 기반 Sankey (라인→야드, CaO/MgO 버튼)", V.build_yardchange_sankey(yc, "CaO")),
            ("물류 개요 Sankey (광산→OSP→야드, 누적)", V.build_tracking_sankey(mine, osp_exp, yards)),
        ]},
        {"name": "📈 변경일자별 추이", "sections": [
            ("변경일자별 야드 CaO·MgO 추이", V.yardchange_trend(yc)),
            ("야드별 표준편차 (변경데이터)", V.yardchange_std_summary(yc, "yard")),
            ("라인별 표준편차 (변경데이터)", V.yardchange_std_summary(yc, "line")),
            ("라인별 표준편차 (연속 야드측정 CNA/45Q)", V.continuous_std_summary(yards)),
            ("변경일자별 상세", "<table><tr><th>변경일시</th><th>라인</th><th>야드</th><th>CaO</th><th>MgO</th><th>야드물량</th></tr>"
             + "".join(f"<tr><td>{r.datetime:%Y/%m/%d %H:%M}</td><td>{r.line}</td><td>{r.yard}</td>"
                      f"<td>{r.cao:.2f}</td><td>{r.mgo:.2f}</td><td>{r.tonnage:,.0f}</td></tr>"
                      for r in yc.sort_values('datetime').itertuples()) + "</table>"),
        ]},
        {"name": "🤖 예측·모델", "sections": [
            ("최적 모델 벤치마크 (10개)", "<table><tr><th>라인→야드</th><th>추천</th><th>최적 MAE</th></tr>"
             + "".join(reco_rows) + "</table>"
             '<div class="ok">선형(Ridge)이 최적 — 부스팅은 소표본 과적합으로 열위.</div>'),
            ("", bench_secs[0][1]), ("", bench_secs[1][1]),
            ("라인별 예측 실측 대비", "<table><tr><th>라인</th><th>야드</th><th>검증 MAE</th></tr>" + "".join(metric_rows) + "</table>"),
            ("", pred_secs[0][1]), ("", pred_secs[1][1]),
        ]},
        {"name": "📊 관리도", "sections": [
            ("규격내 시간 비율 (KPI)", "<table><tr><th>라인→야드</th><th>규격내 비율</th></tr>" + "".join(kpi_rows) + "</table>"),
            ("", ctrl_secs[0][1]), ("", ctrl_secs[1][1]),
        ]},
        {"name": "🚨 모니터·경보", "sections": [("라인별 실시간 상태", "".join(cards))]},
        {"name": "⚗️ 배합 최적화", "sections": [
            ("배합 최적화 (경로 2 · 향후용)", f"<pre>{demo.summary()}</pre>"
             "<p>구조 완성. 데이터 축적으로 구역-품위 추정이 정밀해지면 처방 정밀도 상승.</p>")]},
    ]

    # 데이터 전체 기간 → 날짜 직접입력 컨트롤 범위
    alldt = pd.concat([yc["datetime"]] + [y["datetime"] for y in yards.values() if len(y)])
    dr = (pd.to_datetime(alldt.min()).strftime("%Y-%m-%d"),
          pd.to_datetime(alldt.max()).strftime("%Y-%m-%d")) if len(alldt) else None
    html = V.assemble_tabbed_html("석회석 광산-야드 CaO 추적·예측 통합 리포트" + period_txt, tabs, date_range=dr)
    out = OUTPUTS_DIR / "final_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] 최종 통합 리포트: {out} ({out.stat().st_size // 1024} KB){period_txt}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="최종 통합 리포트 생성 (기간 지정 가능)")
    ap.add_argument("--start", help="시작일 YYYY-MM-DD (미지정=처음)")
    ap.add_argument("--end", help="종료일 YYYY-MM-DD (미지정=끝)")
    args = ap.parse_args()
    main(args.start, args.end)
