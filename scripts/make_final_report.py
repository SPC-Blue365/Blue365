"""최종 통합 리포트 (3종 종합, 탭 단일 HTML) [Synthesis-Agent].

실행: python scripts/make_final_report.py → outputs/final_report.html (로컬 전용)
탭: 개요 · 추적 흐름 · 변경일자별 추이 · 예측·모델 · 관리도 · 모니터·경보 · 배합 최적화
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from config import schema as S
from config.paths import OUTPUTS_DIR, ensure_dirs
from src.matching.segments import LAG_CAUTION, segment_warnings, yard_change_segments
from src.models import forecast as F
from src.models.benchmark import benchmark, recommend
from src.models.dataset import (
    build_line_data, calibrate_flow, calibration_windows, filter_period, load_osp_stock,
    load_sources, load_yard_change, stock_vs_flow,
)
from src.monitoring import monitor_all
from src.monitoring.monitor import MIN_ROWS as _MIN

from src.monitoring.alerts import AlertConfig, Level
from src.optimization.blend import BlendSource, recommend_blend
from src.visualization import figures as V

MIN_MODEL_ROWS = F.MIN_TRAIN_ROWS   # 시계열 CV·학습에 필요한 최소 행수

BADGE = {Level.GREEN: ("🟢", "정상"), Level.YELLOW: ("🟡", "주의"), Level.RED: ("🔴", "경고")}


TOLS = [0.5, 1.0, 1.5, 2.0]      # 사용자가 고를 수 있는 허용폭(%p)
GAIN_TIE = 5.0                    # 기준선 대비 개선폭이 이보다 작으면 '사실상 동급'


def _verdict(mae, mae_persist, gain, tol) -> tuple[str, str]:
    """허용폭별 판정 문장 + 스타일. 실제 검증 수치에서만 생성한다 (§2-1).

    두 축으로 나눠 판단한다 — ⓐ 허용폭 안에 드는가, ⓑ '직전값 그대로 쓰기'를 넘는가.
    ⓑ가 미미하면 '사실상 동급'이라고 분명히 밝힌다(개선폭 %만 보면 실제보다 좋아 보인다).
    """
    within = mae <= tol
    a = (f"평균 오차 <b>{mae:.2f}%p</b>로 허용폭 ±{tol}%p <b>이내</b>입니다." if within
         else f"평균 오차 <b>{mae:.2f}%p</b>로 허용폭 ±{tol}%p를 <b>넘습니다</b>.")

    if gain < GAIN_TIE:
        tie = True
        b = (f"다만 '직전값 그대로 쓰기'({mae_persist:.2f})와 <b>사실상 동급</b>({gain:+.0f}%)이라, "
             "현재 모델은 <b>독자적인 예측력이 거의 없습니다</b> — "
             "품위가 시간당 크게 변하지 않아 '방금 값'만으로도 이만큼 맞는 것입니다.")
    else:
        tie = False
        b = f"'직전값 그대로 쓰기'({mae_persist:.2f})보다 <b>{gain:.0f}% 정확</b>합니다."

    if within and not tie:
        c, cls = ("예측값을 보고 배합을 조정하는 <b>선제적 제어</b>를 시도할 수 있습니다.", "ok")
    elif within and tie:
        c, cls = ("허용폭 안에 들지만 <b>모델 덕분이 아니라 품위가 안정적이기 때문</b>이므로, "
                  "이 수치를 모델 성능으로 보고하면 안 됩니다.", "note")
    else:
        c, cls = ("<b>이상 감지·조기경보</b>에는 쓸 수 있으나, <b>정밀 배합 제어는 아직 이릅니다.</b>", "note")
    return f"{a} {b} {c}", cls


def _pred_block(ln, ld, te, err, mae, mae_persist, mae_naive, gain) -> tuple[str, dict]:
    """라인별 예측 성적 KPI 타일 + 평문 판정 (임원용).

    반환: (HTML, 허용폭별 수치·판정 dict) — dict 는 JS 가 허용폭 전환 시 갈아끼운다.
    """
    stat = {}
    for t in TOLS:
        v, cls = _verdict(mae, mae_persist, gain, t)
        stat[f"{t}"] = dict(hit=round(float((err <= t).mean() * 100)), verdict=v, cls=cls)
    d0 = stat[f"{TOLS[0]}"]
    span = f"{te.index.min():%m/%d %H시} ~ {te.index.max():%m/%d %H시}"
    html = (
        f"<h3 style='margin:18px 0 4px;color:#12395c'>{ln} 라인 → {ld.alias}</h3>"
        f"<div class='kpirow'>"
        f"<div class='kpi'><div class='v'><span id='hit-{ln}'>{d0['hit']}</span>%</div>"
        f"<div class='l'>오차 ±<span class='tolv'>{TOLS[0]}</span>%p 이내 적중률</div></div>"
        f"<div class='kpi'><div class='v'>{mae:.2f}<span style='font-size:.9rem'>%p</span></div>"
        f"<div class='l'>평균 오차 (허용폭 ±<span class='tolv'>{TOLS[0]}</span> 이하 목표)</div></div>"
        f"<div class='kpi'><div class='v'>{gain:+.0f}%</div>"
        f"<div class='l'>'직전값 쓰기' 대비 개선</div></div>"
        f"<div class='kpi'><div class='v'>{len(te)}<span style='font-size:.9rem'>시간</span></div>"
        f"<div class='l'>검증 구간 ({span})</div></div>"
        f"</div>"
        f"<div class='{d0['cls']}' id='verdict-{ln}'><b>판정:</b> {d0['verdict']}</div>"
    )
    return html, stat


def _balance_note(mine, osp_exp) -> str:
    """라인별 적재량 vs 인출량 = OSP 재고 증감. 실제 수치로 근거를 보인다."""
    if mine is None or osp_exp is None or not len(mine) or not len(osp_exp):
        return ""
    parts = []
    for ln in S.YARD_PAIR:
        m = float(pd.to_numeric(mine.loc[mine["line"] == ln, "tonnage"], errors="coerce").sum())
        o = float(pd.to_numeric(osp_exp.loc[osp_exp["line"] == ln, "withdrawn_ton"],
                                errors="coerce").sum())
        if m <= 0 and o <= 0:
            continue
        parts.append(f"<b>{ln}</b> 적재 {m:,.0f}톤 · 인출 {o:,.0f}톤 → 재고 {m - o:+,.0f}톤")
    return ("<br>이 기간 실제: " + " / ".join(parts)) if parts else ""


def _inventory_note(mine, osp_exp) -> str:
    """재고 차트를 읽을 때 필요한 데이터 커버리지 고지 (실제 수치로)."""
    if mine is None or osp_exp is None or not len(mine) or not len(osp_exp):
        return ""
    notes = []
    for ln in S.YARD_PAIR:
        m = mine[mine["line"] == ln]
        o = osp_exp[osp_exp["line"] == ln]
        if not len(m) or not len(o):
            continue
        m0 = pd.to_datetime(m["datetime"]).min()
        pre = o[pd.to_datetime(o["datetime"]) < m0]
        t = float(pd.to_numeric(pre["withdrawn_ton"], errors="coerce").sum())
        tot = float(pd.to_numeric(o["withdrawn_ton"], errors="coerce").sum())
        if t > 0 and tot > 0:
            notes.append(f"<b>{ln}</b>은 광산 기록({m0:%m/%d}) 이전 인출이 "
                         f"{t:,.0f}톤({t / tot * 100:.1f}%) 있어 초반 하락이 다소 과장됩니다")
    return ("ℹ️ " + " · ".join(notes) + ".") if notes else ""


def _stock_gap_note(stock, mine, osp_exp) -> str:
    """실사 재고와 흐름 계산의 격차를 실제 수치로 고지 (원인은 단정하지 않는다)."""
    parts = []
    for ln in S.YARD_PAIR:
        r = stock_vs_flow(stock, mine, osp_exp, ln)
        if not r:
            continue
        parts.append(
            f"<b>{ln}</b>: 실사 {r['s0']:,.0f}→{r['s1']:,.0f}톤({r['actual']:+,.0f}) vs "
            f"흐름 계산 {r['calc']:+,.0f}톤 → <b>격차 {r['gap']:+,.0f}톤</b>({r['gap_per_day']:+,.0f}톤/일)")
    if not parts:
        return ""
    return ("<br><b>⚠️ 이 기간 실측 격차</b> — " + " / ".join(parts)
            + "<br><b>실사 재고는 정상 범위를 유지</b>하는데(2년간 기존 28~45천톤·신설 22~40천톤), "
              "적재−인출로 계산하면 재고가 <b>마이너스</b>가 되어야 합니다 — 물리적으로 불가능합니다.<br>"
              "사용자 확인: <b>OSP 재고에는 49Q 물량만</b> 들어가며 다른 채굴장 물량은 포함되지 않습니다. "
              "49Q만으로 계산하면 격차가 <b>더 커지므로</b>, 원인은 유입원이 아니라 "
              "<b>적재량 과소 기록 또는 인출량 과대 기록</b> 쪽입니다. 확인 전까지 어느 한쪽을 "
              "맞다고 단정하지 않고 <b>둘 다 표시</b>합니다(§2-1).")


def _calib_note(calib: dict) -> str:
    """실사에 맞춘 흐름 보정 결과 (경험적 보정임을 분명히 밝힌다)."""
    parts = []
    for ln, c in (calib or {}).items():
        if not c:
            continue
        parts.append(
            f"<b>{ln}</b>: {c['method']} = <b>{c['coef']:.3f}</b> "
            f"(오차 {c['resid_std_raw']:,.0f}→{c['resid_std']:,.0f}톤, {c['improve']:.0f}% 개선)")
    if not parts:
        return ""
    noise = [c["noise_std"] for c in calib.values() if c and c.get("noise_std") == c.get("noise_std")]
    nz = f"{min(noise):,.0f}~{max(noise):,.0f}톤" if noise else "-"
    return ("<br><b>🔧 실사에 맞춘 보정</b> — " + " / ".join(parts)
            + "<br>실사 재고에 가장 잘 맞는 배율을 <b>데이터로 추정</b>해 흐름 곡선을 보정했습니다"
              "(굵은 점선). 옅은 점선이 보정 전입니다. 두 라인 모두 <b>인출이 7~9% 과대 기록</b>된 "
              "것으로 나오는데, 이는 서로 독립적인 두 라인에서 같은 방향으로 나온 결과입니다.<br>"
              f"<b>남은 오차의 하한은 육안 실사 자체의 흔들림</b>입니다 — 교대 간 실사값이 "
              f"표준편차 <b>{nz}</b>만큼 튀고 해상도도 1,000톤 단위라, 보정으로 이 아래까지 "
              "줄이는 것은 불가능합니다.<br>"
              "<b>⚠️ 경험적 보정이지 원인 규명이 아닙니다.</b> 어느 기록이 실제와 다른지는 현장 "
              "확인이 필요합니다.<br>"
              "<b>💡 운영상 '지금 재고'가 필요하면 가장 최근 실사값을 쓰십시오</b> — 흐름 계산은 "
              "실사와 실사 사이를 메우는 용도로만 신뢰할 수 있습니다.")


def _drift_note(win: dict) -> str:
    """구간별 β 가 흘러가는지 판정 (추세 vs 들쭉날쭉)."""
    out = []
    for ln, ws in (win or {}).items():
        if len(ws) < 3:
            continue
        b = np.array([w["beta"] for w in ws])
        slope = float(np.polyfit(np.arange(len(b)), b, 1)[0])
        rng = f"{b.min():.3f}~{b.max():.3f}"
        if abs(slope) >= 0.03:
            kind = (f"<b>한 방향으로 흘러갑니다</b>({b[0]:.3f}→{b[-1]:.3f}, "
                    f"10일당 {slope:+.3f}) — 계량기 지시가 점점 변하고 있어 <b>교정 점검 대상</b>")
        else:
            kind = f"뚜렷한 추세 없이 <b>들쭉날쭉</b>합니다({rng}) — 그때그때 조건에 따라 흔들리는 형태"
        out.append(f"<b>{ln}</b>: {kind}")
    return ("<br><b>📈 판정</b> — " + " / ".join(out)) if out else ""


def _seg_selector(segs: list[dict]) -> str:
    """야드변경 구간 드롭다운 (라인별 그룹). 선택 시 두 Sankey가 그 구간으로 바뀐다."""
    if not segs:
        return ""
    groups = {}
    for sg in segs:
        groups.setdefault(sg["line"], []).append(sg)
    opt = "<option value=''>전체 기간 (누적)</option>"
    for ln, items in groups.items():
        opt += f"<optgroup label='{ln} 라인 야드변경 구간 ({len(items)}개)'>"
        opt += "".join(f"<option value='{s['key']}'>{s['label']} ({s['hours']}h)</option>"
                       for s in items)
        opt += "</optgroup>"
    return (
        "<div class='tolbar'>🔀 <b>야드변경 구간</b> "
        f"<select id='segSel' onchange='setSeg(this.value)'>{opt}</select>"
        "<span class='hint'>구간은 <b>라인별</b>입니다 — 두 라인의 변경 시점이 다르기 때문입니다.</span>"
        "</div><div id='segInfo' class='cap' style='display:none'></div>"
    )


def _seg_script(segs: list[dict]) -> str:
    """구간 선택 JS. 두 Sankey를 그 라인·구간으로 재계산하고, 선택 링크를 강조한다.

    경고 문구는 src.matching.segments 에서 만들어 실어 보낸다(리포트·대시보드 문구 통일).
    """
    payload = {}
    for s in segs:
        payload[s["key"]] = {k: v for k, v in s.items() if k not in ("start", "end")}
        payload[s["key"]]["warn"] = segment_warnings(s)
    return (
        "<script>window.YCLAG=" + json.dumps(LAG_CAUTION, ensure_ascii=False) + ";"
        "window.YCSEG=" + json.dumps(payload, ensure_ascii=False) + ";"
        "window.YCHL=null; window.YCLINE=null;"
        "window.setSeg=function(k){"
        "  var box=document.getElementById('segInfo');"
        "  if(!k){ window.YCHL=null; window.YCLINE=null; if(box)box.style.display='none';"
        "          if(window.recomputeSankeys)recomputeSankeys(DR_MIN,DR_MAX); return; }"
        "  var g=(window.YCSEG||{})[k]; if(!g){return;}"
        "  window.YCHL=g.link; window.YCLINE=g.line;"
        "  if(window.recomputeSankeys)recomputeSankeys(g.s,g.e);"
        # 시간축 차트(재고 추이·타임라인 등)도 같은 구간으로 확대 — 탭 안에서 기간이 어긋나지 않게
        "  if(window._timeGraphs){_timeGraphs().forEach(function(gd){"
        "    Plotly.relayout(gd,{'xaxis.range':[g.s.slice(0,10)+' 00:00:00',"
        "                                       g.e.slice(0,10)+' 23:59:59']});});}"
        "  if(box){"
        "    box.innerHTML='<b>'+g.label+'</b> ('+g.hours+'시간) · 이 구간은 <b>'+g.line+' 라인만</b> 표시합니다'"
        "      +'<br>변경 시점 품위 CaO '+(g.cao==null?'-':g.cao)+'% · MgO '+(g.mgo==null?'-':g.mgo)+'%'"
        "      +' · 이 구간 데이터: 광산 '+g.n_mine+'행 · OSP 인출 '+g.n_osp+'행 · 야드 측정 '+g.n_own+'건'"
        "      +'<br><span style=\"color:#8a6d1a\">⚠️ '+window.YCLAG+'</span>'"
        "      +((g.warn&&g.warn.length)?'<br><span style=\"color:#b23\">⚠️ '+g.warn.join(' ')+'</span>':'');"
        "    box.style.display='block';"
        "  }"
        "};</script>"
    )


def _tol_script(pred_stats: dict) -> str:
    """허용폭 전환 JS. 적중률·판정문·스코어카드 기준선을 한꺼번에 갈아끼운다."""
    return (
        "<script>window.PREDSTAT=" + json.dumps(pred_stats, ensure_ascii=False) + ";"
        "window.setTol=function(t){"
        "  var s=window.PREDSTAT||{};"
        "  Object.keys(s).forEach(function(ln){"
        "    var d=s[ln][t]; if(!d){return;}"
        "    var h=document.getElementById('hit-'+ln); if(h)h.innerText=d.hit;"
        "    var th=document.getElementById('thit-'+ln); if(th)th.innerText=d.hit;"
        "    var v=document.getElementById('verdict-'+ln);"
        "    if(v){v.innerHTML='<b>판정:</b> '+d.verdict; v.className=d.cls;}"
        "  });"
        "  document.querySelectorAll('.tolv').forEach(function(e){e.innerText=t;});"
        # 스코어카드(가로 막대)의 목표 기준선·주석을 새 허용폭으로 이동
        "  document.querySelectorAll('.plotly-graph-div').forEach(function(gd){"
        "    var m=gd.layout&&gd.layout.meta; if(!m||m.kind!=='scorecard'){return;}"
        "    var x=parseFloat(t);"
        "    Plotly.relayout(gd,{'shapes[0].x0':x,'shapes[0].x1':x,"
        "                        'annotations[0].x':x,'annotations[0].text':'허용폭 ±'+t+'%p'});"
        "  });"
        "};</script>"
    )


def _tol_selector() -> str:
    """허용폭(±%p) 선택 드롭다운. 적중률·판정문·스코어카드 기준선이 함께 바뀐다."""
    opts = "".join(f"<option value='{t}'>±{t}%p</option>" for t in TOLS)
    return (
        "<div class='tolbar'>🎯 <b>허용폭 기준</b> "
        f"<select id='tolSel' onchange='setTol(this.value)'>{opts}</select>"
        "<span class='hint'>기준을 넓히면 적중률이 올라갑니다 — 실제 관리 목표는 ±0.5%p입니다.</span></div>"
    )


def _expand(secs: list, what: str) -> list:
    """라인 수에 맞춰 그래프 섹션을 펼친다. 하나도 없으면 사유를 안내한다.

    (라인이 가동 중지이거나 기간이 짧으면 섹션 수가 줄어든다 — 고정 인덱싱 금지.)
    """
    if secs:
        return [("", fig) for _, fig in secs]
    return [("", f"<p class='muted'>표시할 {what}가 없습니다 — "
                 f"선택한 기간에 모델링 가능한 라인이 없습니다(가동 중지 또는 데이터 부족).</p>")]


def _line_feats(osp_exp, yards, line):
    ld = build_line_data(osp_exp, yards, line)
    return ld.features


def main(start=None, end=None):
    ensure_dirs()
    mine, osp_exp, yards = load_sources()
    yc = load_yard_change()
    stock = load_osp_stock()          # OSP 실사 재고 (시트 없으면 빈 프레임)
    # 기간 필터 (--start/--end). 지정 시 해당 구간으로 모든 산출물 재계산.
    if start or end:
        yc = filter_period(yc, start, end, "datetime")
        yards = {ln: filter_period(df, start, end, "datetime") for ln, df in yards.items()}
        mine = filter_period(mine, start, end, "datetime")    # 광산도 동일 기간(교대 시각 기준)
        osp_exp = filter_period(osp_exp, start, end, "datetime")
    period_txt = ""
    if start or end:
        period_txt = f" · 기간 {start or '처음'}~{end or '끝'}"
    lines = {ln: build_line_data(osp_exp, yards, ln) for ln in S.YARD_PAIR}
    cfg = AlertConfig()
    statuses = monitor_all(lines, cfg)

    # ── 예측·벤치마크 ──
    pred_secs, bench_secs, ctrl_secs, metric_rows, reco_rows, kpi_rows = [], [], [], [], [], []
    pred_stats: dict[str, dict] = {}   # 라인 → 허용폭별 적중률·판정 (HTML 내 JS가 전환)
    skipped: list[str] = []
    for ln, ld in lines.items():
        feats = ld.features
        d = feats.dropna(subset=F.AR_CORE + ["cao"])
        k = int(len(d) * 0.7)
        try:
            # 학습분할(70%)·벤치마크 모두 최소 행수를 넘겨야 한다 (부족하면 InsufficientDataError)
            F.require_rows(k, MIN_MODEL_ROWS, "리포트 모델링")
            model, fcols = F.fit_final(d.iloc[:k])
            bench = benchmark(feats, use_upstream=False)
        except F.InsufficientDataError:
            # 데이터 부족(가동 중지·짧은 기간) → 지어내지 않고 생략 (CLAUDE.md §2-1)
            msg = f"데이터 부족({len(d)}행) — 해당 기간 모델링 생략"
            metric_rows.append(f"<tr><td>{ln}</td><td>{ld.alias}</td><td>-</td></tr>")
            reco_rows.append(f"<tr><td>{ln}→{ld.alias}</td><td>-</td><td>-</td></tr>")
            kpi_rows.append(f"<tr><td>{ln}→{ld.alias}</td><td>-</td><td>-</td></tr>")
            skipped.append(f"{ln}→{ld.alias}: {msg}")
            continue
        te = d.iloc[k:]
        pr = model.predict(te[fcols].fillna(0).values)
        err = np.abs(te["cao"].values - pr)
        mae = float(err.mean())
        # 기준선: '직전값 그대로 쓰기'(persist)와 '그냥 평균 쓰기'(naive) — 모델의 값어치 판단용
        mae_persist = float(np.abs(te["cao"].values - te["ar1"].values).mean())
        mae_naive = float(np.abs(te["cao"].values - d["cao"].iloc[:k].mean()).mean())
        gain = (mae_persist - mae) / mae_persist * 100 if mae_persist else 0.0
        oos = (pr < V.TARGET - 0.5) | (pr > V.TARGET + 0.5)

        block, stat = _pred_block(ln, ld, te, err, mae, mae_persist, mae_naive, gain)
        pred_stats[ln] = stat
        pred_secs.append(("", block))
        pred_secs.append(("", V.prediction_scorecard(
            [("이 예측 모델", mae, True), ("직전값 그대로 쓰기", mae_persist, False),
             ("그냥 평균값 쓰기", mae_naive, False)],
            tol=TOLS[0],
            title=f"{ln} → {ld.alias} · 예측 방법별 평균 오차 (짧을수록 정확)")))
        pred_secs.append(("", V.prediction_timeseries(te.index, te["cao"].values, pr, oos,
                          f"{ln} → {ld.alias} · 검증 구간만 표시 "
                          f"({te.index.min():%m/%d}~{te.index.max():%m/%d}, 모델이 못 본 뒤 30%)")))
        tie = " <span style='color:#8a6d1a'>(동급)</span>" if gain < GAIN_TIE else ""
        metric_rows.append(f"<tr><td>{ln}</td><td>{ld.alias}</td><td><b>{mae:.2f}</b></td>"
                           f"<td>{mae_persist:.2f}{tie}</td>"
                           f"<td><span id='thit-{ln}'>{stat[f'{TOLS[0]}']['hit']}</span>%</td></tr>")
        bench_secs.append(("", V.model_benchmark_bar(bench, f"{ln} → {ld.alias}: 10개 모델 CV MAE")))
        reco_rows.append(f"<tr><td>{ln}→{ld.alias}</td><td><b>{recommend(bench)}</b></td>"
                         f"<td>{bench[~bench['is_baseline']]['MAE'].min():.3f}</td></tr>")
        # ⭐️ 관리도는 **리포트 기간 전체**의 시간별 야드 실측을 쓴다.
        #    모니터의 series 는 경보용 '최근 20% 감시창'이라, 그걸 쓰면 x축이 최근 며칠만
        #    나오고 규격내 비율도 그 구간 기준이 되어 기간 설정과 어긋난다(실제 발생 버그).
        ys = ld.yard_series
        cx, act = ys.index, ys.values
        fin = act[np.isfinite(act)]
        insp = float(np.mean((fin >= cfg.lo) & (fin <= cfg.hi)) * 100) if len(fin) else 0.0
        kpi_rows.append(f"<tr><td>{ln}→{ld.alias}</td><td>{insp:.0f}%</td>"
                        f"<td>{len(fin):,}시간</td></tr>")
        ctrl_secs.append(("", V.control_chart(cx, act, cfg.lo, cfg.hi,
                          f"{ln} → {ld.alias} 관리도 (규격내 {insp:.0f}% · {len(fin):,}시간)")))

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
        icon, label = st.badge
        al = "".join(f"<li>[{a.level.label}] {a.message}</li>" for a in st.alerts) or "<li>경보 없음</li>"
        stale_css = "#8a6d1a" if st.is_stale else "#12395c"
        asof = (f'<span style="color:{stale_css}">📅 기준 {st.as_of} ({st.age_text})'
                + (" · ⏸️ 데이터 갱신 중단" if st.is_stale else "") + "</span>")
        note = f'<br><i style="color:#8a6d1a">※ {st.note}</i>' if st.note else ""
        cards.append(f'<div class="note" style="border-color:{stale_css}"><b>{icon} {ln} → {st.alias} · {label}</b>'
                     f'<br>{asof}{note}'
                     f'<br>최신 CaO {st.latest_actual:.2f}% (예측 {st.latest_pred:.2f}) · 최근 MAE {st.recent_mae:.2f}'
                     f'<ul>{al}</ul></div>')

    def cap(t):
        return f'<p class="cap">💬 {t}</p>'

    # ── 경영 요약 (Executive Summary) ──
    # ⭐️ '전체 기간'은 Sankey 가 쓰는 모든 소스를 덮어야 한다. 야드/야드변경만으로 잡으면
    #    그보다 먼저 시작하는 OSP(신설 06/01)·광산 물량이 '전체'에서 빠진다(6,000톤 누락 버그).
    _parts = [yc["datetime"]] + [y["datetime"] for y in yards.values() if len(y)]
    if osp_exp is not None and len(osp_exp):
        _parts.append(pd.to_datetime(osp_exp["datetime"]))
    if mine is not None and len(mine):
        _parts.append(pd.to_datetime(mine["date"]))
    _a = pd.concat(_parts) if any(len(x) for x in _parts) else pd.Series(dtype="datetime64[ns]")
    _mn, _mx = (pd.to_datetime(_a.min()), pd.to_datetime(_a.max())) if len(_a) else (pd.NaT, pd.NaT)
    rmin = "-" if pd.isna(_mn) else _mn.strftime("%Y/%m/%d")
    rmax = "-" if pd.isna(_mx) else _mx.strftime("%Y/%m/%d")
    # 가동 중인(데이터 최신) 라인만 종합 상태에 반영, 중지 라인은 별도 표기
    live = [st for st in statuses.values() if not st.is_stale]
    overall = max((st.level for st in live), key=lambda x: int(x)) if live else Level.GREEN
    ov_icon, ov_label = BADGE[overall]
    if not live:
        ov_icon, ov_label = "⏸️", "전 라인 가동 중지"
    status_line = " · ".join(
        f"{st.badge[0]} {ln} {st.badge[1]}({st.age_text})" for ln, st in statuses.items())

    # 일별 CaO 집계(개수/합/제곱합) → HTML 내 JS가 기간별 평균·표준편차를 정확 재계산
    def _daily_cao(df):
        d = df.dropna(subset=["datetime", "cao"]).copy()
        d["d"] = d["datetime"].dt.strftime("%Y-%m-%d")
        rows = []
        for dd, gg in d.groupby("d"):
            c = gg["cao"].values.astype(float)
            rows.append([dd, int(len(c)), float(c.sum()), float((c ** 2).sum())])
        return rows
    sumagg_json = json.dumps({"신설": _daily_cao(yards[S.LINE_NEW]), "기존": _daily_cao(yards[S.LINE_OLD])},
                             ensure_ascii=False)
    stock_p = filter_period(stock, start, end, "datetime") if (start or end) else stock
    # 실사에 맞춘 흐름 보정계수 (라인별). 실사가 5회 미만이면 빈 dict → 보정 없이 표시
    calib = {ln: calibrate_flow(stock_p, mine, osp_exp, ln) for ln in S.YARD_PAIR}
    calib_win = {ln: calibration_windows(stock_p, mine, osp_exp, ln) for ln in S.YARD_PAIR}
    segments = yard_change_segments(yc, mine, osp_exp, yards)
    sankey_agg = V.sankey_daily_aggregates(mine, osp_exp, yards, yc)
    sankey_script = ("<script>window.SANKEYAGG=" + json.dumps(sankey_agg, ensure_ascii=False) + ";</script>")
    sum_script = (
        "<script>window.SUMAGG=" + sumagg_json + ";"
        "window.recomputeSummary=function(s,e){s=s||'0000';e=e||'9999';var res={};"
        "[['신설','New'],['기존','Old']].forEach(function(p){var a=(window.SUMAGG[p[0]]||[]),n=0,su=0,ss=0;"
        "a.forEach(function(r){if(r[0]>=s&&r[0]<=e){n+=r[1];su+=r[2];ss+=r[3];}});"
        "var m=null,sd=null;if(n>0){m=su/n;sd=Math.sqrt(Math.max(0,ss/n-m*m));}res[p[1]]={m:m,sd:sd};"
        "var em=document.getElementById('sum'+p[1]+'Mean'),es=document.getElementById('sum'+p[1]+'Std');"
        "if(em)em.innerText=(m==null?'-':m.toFixed(1));if(es)es.innerText=(sd==null?'-':sd.toFixed(1));});"
        # 핵심 진단(규칙 기반): 기간별 최대 표준편차/목표(0.5) 비율로 문장 자동 생성
        "var dg=document.getElementById('sumDiag');if(dg){"
        "var sds=[res.New.sd,res.Old.sd].filter(function(x){return x!=null;});"
        "if(sds.length===0){dg.innerHTML='<b>핵심 진단:</b> 해당 기간 데이터가 없습니다.';}else{"
        "var mx=Math.max.apply(null,sds),ratio=mx/0.5;"
        "var ms=[res.New.m,res.Old.m].filter(function(x){return x!=null;});"
        "var nearMean=ms.every(function(m){return Math.abs(m-44.6)<=0.5;});"
        "if(ratio<=1.0){dg.innerHTML='<b>핵심 진단:</b> 평균·변동 모두 목표 수준(변동 최대 ±'+mx.toFixed(1)+' ≤ 0.5) → <b>안정 상태 유지·관리</b>.';}"
        "else{var meanTxt=nearMean?'평균은 목표(44.6)에 근접하나':'평균이 목표(44.6)와 다소 차이가 있으나';"
        "var v=(ratio<=2.0)?'<b>안정화 진행 필요</b>':'<b>변동성 축소(안정화)가 최우선 과제</b>';"
        "dg.innerHTML='<b>핵심 진단:</b> '+meanTxt+' 시점별 변동성(표준편차) 최대 ±'+mx.toFixed(1)+' — 목표(0.5)의 <b>약 '+ratio.toFixed(1)+'배</b> → '+v+'.';}}}"
        "};</script>"
    )
    exec_summary = (
        '<div class="exec">'
        f'<h2 style="border:none;margin:10px 0 4px">📌 경영 요약</h2>'
        f'<p style="font-size:1.05rem"><b>현재 상태: {ov_icon} {ov_label}</b> &nbsp;({status_line})</p>'
        f'<p style="color:#245;background:#eef5ff;padding:6px 10px;border-radius:4px;font-size:.86rem;margin:6px 0">'
        f'ℹ️ 상단 <b>기간 직접설정</b>을 적용하면 아래 <b>야드 평균·변동 수치가 그 기간으로 자동 갱신</b>됩니다 '
        f'(기본: 전체 {rmin}~{rmax}). 현재 상태·예측 정확도는 최신/모델 기준이라 기간과 무관합니다. '
        f'각 그래프의 버튼·슬라이더는 그 그래프만 확대합니다.</p>'
        '<div class="kpirow">'
        f'<div class="kpi"><div class="v">{S.TARGET.cao_mean}±{S.TARGET.tol}%</div><div class="l">품질 목표 (CaO 평균±표준편차)</div></div>'
        f'<div class="kpi"><div class="v"><span id="sumNewMean">{ycna.mean():.1f}</span>%</div><div class="l">신설 야드 평균 (변동 ±<span id="sumNewStd">{ycna.std():.1f}</span>)</div></div>'
        f'<div class="kpi"><div class="v"><span id="sumOldMean">{y45.mean():.1f}</span>%</div><div class="l">기존 야드 평균 (변동 ±<span id="sumOldStd">{y45.std():.1f}</span>)</div></div>'
        f'<div class="kpi"><div class="v">±{statuses["신설"].recent_mae:.1f}%p</div><div class="l">예측 정확도(오차, 낮을수록 정확)</div></div>'
        '</div>'
        '<p id="sumDiag"><b>핵심 진단:</b> 야드 품위 평균은 목표에 근접하나, 시점별 변동성(표준편차)이 목표(0.5)보다 큼 '
        '→ 변동성 축소(안정화)가 과제.</p>'
        '<p><b>앞으로 이렇게 관리하겠습니다:</b> '
        '① <b>실시간 모니터링·조기경보</b>로 규격 이탈을 즉시 감지 → '
        '② <b>야드 변경·품위 추적</b>으로 원인(어느 야드·시점)을 규명 → '
        '③ 데이터가 쌓이면 <b>배합 최적화</b>로 목표 품위를 사전 제어. '
        '데이터가 축적될수록 예측·제어 정밀도는 계속 향상됩니다.</p>'
        '</div>' + sum_script + sankey_script + _tol_script(pred_stats) + _seg_script(segments)
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
            ("특정 야드변경 구간만 보기",
             cap("아래에서 <b>야드변경 구간</b>을 고르면 두 Sankey가 <b>그 라인 · 그 구간만</b>으로 다시 계산됩니다. "
                 "데이터는 라인별로 구분되어 있으므로 <b>다른 라인의 흐름은 제외</b>됩니다(제목에 '○○ 라인만' 표시).<br>"
                 "<b>구간은 라인별입니다</b> — 기존(9회)과 신설(24회)은 변경 시점이 거의 겹치지 않아 "
                 "'두 라인 공통의 야드변경 기간'은 존재하지 않습니다.")
             + _seg_selector(segments)),
            ("야드 변경 타임라인 (언제 어느 야드로) — CaO/MgO 버튼",
             cap("각 라인이 <b>언제 어느 야드(Y1/Y2)</b>를 썼는지와 그때 품위. 막대 색이 진할수록 CaO 높음(우측 범례). 상단 날짜창·버튼으로 기간 확대.")),
            ("", V.yardchange_gantt(yc, "CaO")),
            ("야드변경 기반 Sankey (라인→야드)",
             cap("라인별로 두 야드에 실린 <b>물량(띠 굵기)</b>과 <b>평균 품위(색)</b>. CaO/MgO 버튼으로 성분 전환. <b>상단 기간을 적용하면 그 기간 기준으로 다시 계산</b>되며 제목에 기간이 표시됩니다.")),
            ("", V.build_yardchange_sankey(yc, "CaO")),
            ("물류 개요 Sankey (광산→OSP→야드)",
             cap("광산(49Q·47Q)에서 캔 원석이 <b>어느 라인·야드로 얼마나</b> 흘렀는지 한눈에. 굵을수록 물량 많음. "
                 "<b>상단 기간·구간에 따라 재계산</b>됩니다(제목에 표시).<br>"
                 "<b>⚠️ 좌우 물량 합이 일치하지 않는 것이 정상입니다.</b> 왼쪽은 광산에서 OSP로 <b>적재한 양</b>, "
                 "오른쪽은 OSP에서 야드로 <b>인출한 양</b>으로 <b>공정 단계가 다른 물량</b>이며, "
                 "그 사이 <b>OSP가 재고(버퍼)</b> 역할을 하므로 차이가 곧 <b>재고 증감</b>입니다."
                 + _balance_note(mine, osp_exp) +
                 "<br>ℹ️ 광산 물량은 <b>채굴 교대 시각</b>(1차 08~16 · 2차 16~24 · 3차 00~08의 중점)과 "
                 "47Q의 <b>실측 시작·종료 시각</b>으로 시간축에 배치됩니다.")),
            ("", V.build_tracking_sankey(mine, osp_exp, yards)),
            ("OSP 재고 증감 추이 (적재 − 인출 누적)",
             cap("위 Sankey 의 좌우 차이가 <b>시간에 따라 어떻게 쌓였는지</b>. "
                 "<b>선이 내려가면 쓴 양이 들어온 양보다 많아 재고가 줄고 있다는 뜻</b>이고, "
                 "올라가면 재고가 늘고 있다는 뜻입니다. "
                 "회색 0선은 <b>리포트 기간 시작 수준</b>.<br>"
                 "<b>⚠️ 절대 재고량이 아닙니다</b> — 시작 시점의 재고가 데이터에 없어 "
                 "<b>증감분만</b> 표시합니다(지어내지 않음). 판단에는 <b>기울기</b>를 보십시오.<br>"
                 + _inventory_note(mine, osp_exp))),
            ("", V.inventory_trend(mine, osp_exp)),
            ("OSP 실사 재고 — 실제 재고량 vs 흐름 계산",
             cap("교대마다 직접 파악한 <b>실사 재고량(실선)</b>과, 광산 적재−인출만으로 "
                 "계산한 <b>추정 재고(점선)</b>를 겹쳐 본 것입니다. "
                 "<b>두 선이 벌어지면 광산 기록에 잡히지 않은 유입이 있다</b>는 뜻입니다.<br>"
                 "ℹ️ 실사값은 <b>1,000톤 단위 개략치</b>이고, 교대 중간(1차 12:30·2차 20:30·3차 04:30)에 파악합니다."
                 + _stock_gap_note(stock_p, mine, osp_exp)
                 + _calib_note(calib))),
            ("", V.stock_trend(stock_p, mine, osp_exp, calibrations=calib)),
            ("인출 벨트스케일 지시 배율 추이 (교정 시점 판단)",
             cap("인출량은 <b>벨트스케일</b>로 계량합니다(사용자 확인). 벨트스케일 오차는 "
                 "<b>통과 물량에 비례</b>하므로 배율 β 로 나타내는 것이 물리적으로 맞습니다.<br>"
                 "<b>β = 실제 ÷ 계량기 지시값</b> — <b>1.0이면 정확</b>, 1.0보다 낮으면 "
                 "계량기가 실제보다 <b>많이 찍고 있다</b>는 뜻입니다(0.90 → 약 10% 과대).<br>"
                 "오차막대는 95% 신뢰구간입니다. <b>구간끼리 겹치지 않으면 실제로 변한 것</b>이며, "
                 "노이즈로 설명되지 않습니다."
                 + _drift_note(calib_win))),
            ("", V.calibration_drift(calib_win)),
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
            ("이 예측, 실제로 쓸 만한가? (라인별 성적)",
             cap("<b>질문:</b> 1시간 뒤 야드 CaO를 미리 맞출 수 있는가?<br>"
                 "<b>방법:</b> 데이터를 시간순으로 놓고 <b>앞 70%만 학습</b>시킨 뒤, "
                 "<b>모델이 못 본 뒤 30% 구간</b>에서 예측값과 실제 측정값을 비교했습니다.<br>"
                 "<b>⚠️ 아래 그래프의 x축은 리포트 기간 전체가 아니라 <u>검증 구간(뒤 30%)</u>입니다</b> — "
                 "모델이 학습에 쓰지 않은 구간에서만 성적을 재기 때문입니다.<br>"
                 "<b>읽는 법:</b> <b>적중률</b>이 높고 <b>평균 오차</b>가 목표 0.5%p보다 작아야 "
                 "'예측 보고 배합을 조절'할 수 있습니다. 아직 못 미치면 <b>조기경보 용도</b>로만 씁니다.")
             + _tol_selector()
             + "<table><tr><th>라인</th><th>야드</th><th>모델 평균오차</th>"
               "<th>직전값 쓰기</th><th>±<span class='tolv'>" + f"{TOLS[0]}" + "</span> 적중률</th></tr>"
             + "".join(metric_rows) + "</table>"),
            *_expand(pred_secs, "예측 성적"),
            ("(참고) 최적 모델 벤치마크 — 10개 기법 비교",
             cap("<b>어떤 기법을 쓸지 고른 근거</b>입니다(기술 검토용). 여러 예측기법을 같은 조건에서 겨뤄 "
                 "오차를 비교했고, 데이터가 적을 때는 단순한 선형(Ridge)이 가장 안정적이었습니다.<br>"
                 "<b>※ 위 성적표와 숫자가 다른 이유:</b> 위는 <b>마지막 30% 한 구간</b>으로 시험한 값이고, "
                 "아래는 <b>구간을 옮겨가며 여러 번</b> 시험한 평균(시계열 교차검증)입니다. 둘 다 실제 검증 결과입니다.")
             + "<table><tr><th>라인→야드</th><th>추천</th><th>최적 MAE</th></tr>"
             + "".join(reco_rows) + "</table>"),
            *_expand(bench_secs, "벤치마크"),
        ]},
        {"name": "📊 관리도", "sections": [
            ("규격내 시간 비율 (KPI)",
             cap("품위가 <b>규격(44.1~45.1%) 안에 머문 시간 비율</b>. 높을수록 안정.<br>"
                 "<b>리포트 기간 전체</b>의 시간별 야드 실측 기준입니다(상단 기간을 바꾸면 다시 생성해야 반영).")
             + "<table><tr><th>라인→야드</th><th>규격내 비율</th><th>집계 시간</th></tr>"
             + "".join(kpi_rows) + "</table>"),
            *_expand(ctrl_secs, "관리도"),
        ]},
        {"name": "🚨 모니터·경보", "sections": [
            ("라인별 실시간 상태",
             cap("현재 상태를 <b>신호등</b>으로. 🔴=규격 이탈/지속, 🟡=주의, 🟢=정상, <b>⏸️=가동 중지·데이터 갱신 중단</b>. 각 라인의 <b>📅 기준 시각</b>을 함께 표기하므로 언제 기준 상태인지 바로 알 수 있습니다.")
             + "".join(cards))]},
        {"name": "⚗️ 배합 최적화", "sections": [
            ("배합 최적화 (향후 로드맵)",
             cap("목표 품위(44.6%)를 맞추려면 <b>각 구역에서 몇 톤을 섞을지</b> 역산. 지금은 방향성 가이드, 데이터 축적 시 정밀 처방.")
             + f"<pre>{demo.summary()}</pre>")]},
    ]

    # 데이터 전체 기간 → 날짜 직접입력 컨트롤 범위
    dr = (_mn.strftime("%Y-%m-%d"), _mx.strftime("%Y-%m-%d")) if not pd.isna(_mn) else None
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
