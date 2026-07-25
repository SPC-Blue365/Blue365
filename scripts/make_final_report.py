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

    def cap(t):
        return f'<p class="cap">💬 {t}</p>'

    # ── 경영 요약 (Executive Summary) ──
    overall = max((st.level for st in statuses.values()), key=lambda x: int(x))
    ov_icon, ov_label = BADGE[overall]
    status_line = " · ".join(f"{BADGE[st.level][0]} {ln} {BADGE[st.level][1]}" for ln, st in statuses.items())
    exec_summary = (
        '<div class="exec">'
        f'<h2 style="border:none;margin:10px 0 4px">📌 경영 요약</h2>'
        f'<p style="font-size:1.05rem"><b>현재 상태: {ov_icon} {ov_label}</b> &nbsp;({status_line})</p>'
        '<div class="kpirow">'
        f'<div class="kpi"><div class="v">{S.TARGET.cao_mean}±{S.TARGET.tol}%</div><div class="l">품질 목표 (CaO 평균±표준편차)</div></div>'
        f'<div class="kpi"><div class="v">{ycna.mean():.1f}%</div><div class="l">신설 야드 평균 (변동 ±{ycna.std():.1f})</div></div>'
        f'<div class="kpi"><div class="v">{y45.mean():.1f}%</div><div class="l">기존 야드 평균 (변동 ±{y45.std():.1f})</div></div>'
        f'<div class="kpi"><div class="v">±{statuses["신설"].recent_mae:.1f}%p</div><div class="l">예측 정확도(오차, 낮을수록 정확)</div></div>'
        '</div>'
        '<p><b>핵심 진단:</b> 야드 품위 <b>평균은 목표에 근접</b>하나, 시점별 <b>변동성(표준편차)이 목표(0.5)보다 큼</b>. '
        '→ 과제는 평균 이동이 아니라 <b>변동성 축소(안정화)</b>.</p>'
        '<p><b>앞으로 이렇게 관리하겠습니다:</b> '
        '① <b>실시간 모니터링·조기경보</b>로 규격 이탈을 즉시 감지 → '
        '② <b>야드 변경·품위 추적</b>으로 원인(어느 야드·시점)을 규명 → '
        '③ 데이터가 쌓이면 <b>배합 최적화</b>로 목표 품위를 사전 제어. '
        '데이터가 축적될수록 예측·제어 정밀도는 계속 향상됩니다.</p>'
        '</div>'
    )
    guide = (
        '<h2>이 대시보드 읽는 법</h2>'
        '<ul>'
        '<li><b>🌊 추적 흐름</b> — 캔 원석이 어느 라인·야드로, 언제 흘렀는지(물류·품위)</li>'
        '<li><b>📈 변경일자별 추이</b> — 시간에 따른 품위 변화와 변동성(표준편차)</li>'
        '<li><b>🤖 예측·모델</b> — 야드 품위를 얼마나 정확히 미리 맞히는지</li>'
        '<li><b>📊 관리도</b> — 규격 이탈 여부를 감시(품질관리 표준 차트)</li>'
        '<li><b>🚨 모니터·경보</b> — 지금 상태를 신호등으로 즉시 확인</li>'
        '<li><b>⚗️ 배합 최적화</b> — 향후 목표품위 자동 배합(로드맵)</li>'
        '</ul>'
        '<p style="color:#667;font-size:.9rem">※ 각 그래프 위 날짜창·버튼으로 원하는 기간만 확대해 볼 수 있습니다.</p>'
    )
    glossary = (
        '<h2>용어 (간단 풀이)</h2>'
        '<dl class="glossary">'
        '<dt>표준편차</dt><dd>값들이 평균에서 얼마나 흩어졌는지. 작을수록 일정(안정). 목표 0.5.</dd>'
        '<dt>예측 오차(MAE)</dt><dd>예측이 실제와 평균 몇 %p 어긋나는지. 작을수록 정확.</dd>'
        '<dt>관리도(UCL/LCL)</dt><dd>공정이 정상 범위(관리 상·하한) 안에 있는지 보는 품질관리 차트.</dd>'
        '<dt>Sankey(흐름도)</dt><dd>물량·흐름의 크기를 띠 굵기로 보여주는 그림.</dd>'
        '<dt>예측 모델(Ridge)</dt><dd>여러 기법 비교 후 채택한, 데이터가 적을 때 가장 안정적인 예측 방식.</dd>'
        '</dl>'
    )

    tabs = [
        {"name": "📋 개요", "sections": [
            ("", exec_summary), ("", guide), ("", glossary),
            ("프로젝트 개요 & 세부 지표", overview)]},
        {"name": "🌊 추적 흐름", "sections": [
            ("야드 변경 타임라인 (언제 어느 야드로) — CaO/MgO 버튼",
             cap("각 라인이 <b>언제 어느 야드(Y1/Y2)</b>를 썼는지와 그때 품위. 막대 색이 진할수록 CaO 높음(우측 범례). 상단 날짜창·버튼으로 기간 확대.")),
            ("", V.yardchange_gantt(yc, "CaO")),
            ("야드변경 기반 Sankey (라인→야드)",
             cap("라인별로 두 야드에 실린 <b>총 물량(띠 굵기)</b>과 <b>평균 품위(색)</b>. CaO/MgO 버튼으로 성분 전환.")),
            ("", V.build_yardchange_sankey(yc, "CaO")),
            ("물류 개요 Sankey (광산→OSP→야드)",
             cap("광산(49Q·47Q)에서 캔 원석이 <b>어느 라인·야드로 얼마나</b> 흘렀는지 전체 물류를 한눈에. 굵을수록 물량 많음.")),
            ("", V.build_tracking_sankey(mine, osp_exp, yards)),
        ]},
        {"name": "📈 변경일자별 추이", "sections": [
            ("변경일자별 야드 CaO·MgO 추이",
             cap("야드 변경 시점마다 <b>CaO(실선·왼쪽축)·MgO(점선·오른쪽축)</b>가 어떻게 움직였는지. 초록 띠=목표 규격, 마커 클수록 물량 많음.")),
            ("", V.yardchange_trend(yc)),
            ("야드별 표준편차 (변경데이터)",
             cap("<b>품위가 얼마나 들쭉날쭉한지</b>(표준편차, 막대 낮을수록 안정). 초록 점선=목표 0.5.")),
            ("", V.yardchange_std_summary(yc, "yard")),
            ("라인별 표준편차 (변경데이터)",
             cap("위와 같되 <b>라인(기존/신설) 단위</b>로 묶어 본 변동성.")),
            ("", V.yardchange_std_summary(yc, "line")),
            ("라인별 표준편차 (연속 야드측정 CNA/45Q)",
             cap("<b>실시간 분석기 실측</b> 기준 변동성 — 대표값(위)보다 실제 변동이 훨씬 큼(목표 0.5와 큰 격차). <b>이 격차 축소가 핵심 과제.</b>")),
            ("", V.continuous_std_summary(yards)),
            ("변경일자별 상세", "<table><tr><th>변경일시</th><th>라인</th><th>야드</th><th>CaO</th><th>MgO</th><th>야드물량</th></tr>"
             + "".join(f"<tr><td>{r.datetime:%Y/%m/%d %H:%M}</td><td>{r.line}</td><td>{r.yard}</td>"
                      f"<td>{r.cao:.2f}</td><td>{r.mgo:.2f}</td><td>{r.tonnage:,.0f}</td></tr>"
                      for r in yc.sort_values('datetime').itertuples()) + "</table>"),
        ]},
        {"name": "🤖 예측·모델", "sections": [
            ("최적 모델 벤치마크 (10개)",
             cap("여러 예측기법을 <b>같은 조건에서 겨뤄</b> 오차(MAE, 낮을수록 정확)를 비교. 소량 데이터엔 선형(Ridge)이 최적.")
             + "<table><tr><th>라인→야드</th><th>추천</th><th>최적 MAE</th></tr>"
             + "".join(reco_rows) + "</table>"),
            ("", bench_secs[0][1]), ("", bench_secs[1][1]),
            ("라인별 예측 실측 대비",
             cap("검증 구간에서 <b>예측(빨강)과 실제(파랑)</b>가 가까울수록 정확. 주황 삼각형=규격 이탈 경보 지점. 표는 오차(MAE, %).")
             + "<table><tr><th>라인</th><th>야드</th><th>검증 MAE</th></tr>" + "".join(metric_rows) + "</table>"),
            ("", pred_secs[0][1]), ("", pred_secs[1][1]),
        ]},
        {"name": "📊 관리도", "sections": [
            ("규격내 시간 비율 (KPI)",
             cap("품위가 <b>규격(44.1~45.1%) 안에 머문 시간 비율</b>. 높을수록 안정.")
             + "<table><tr><th>라인→야드</th><th>규격내 비율</th></tr>" + "".join(kpi_rows) + "</table>"),
            ("", ctrl_secs[0][1]), ("", ctrl_secs[1][1]),
        ]},
        {"name": "🚨 모니터·경보", "sections": [
            ("라인별 실시간 상태",
             cap("현재 상태를 <b>신호등</b>으로. 🔴=규격 이탈/지속, 🟡=주의, 🟢=정상. 새 데이터가 오면 자동 갱신.")
             + "".join(cards))]},
        {"name": "⚗️ 배합 최적화", "sections": [
            ("배합 최적화 (향후 로드맵)",
             cap("목표 품위(44.6%)를 맞추려면 <b>각 구역에서 몇 톤을 섞을지</b> 역산. 지금은 방향성 가이드, 데이터 축적 시 정밀 처방.")
             + f"<pre>{demo.summary()}</pre>")]},
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
