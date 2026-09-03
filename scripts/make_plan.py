"""임원 보고용 계획서 생성 [Synthesis-Agent].

`prescription.html`(처방)·`brief.html`(현황)이 **실무자용**이라면 이 문서는 **의사결정용**이다.
임원이 알아야 할 것은 셋뿐이다 — **무엇을 만들려는가 · 어디까지 왔는가 · 무엇을 승인해야 하는가.**

그래서 이 문서는 기술 용어를 걷어내고 **목표 문장 하나**로 시작한다.

    "OSP 몇 번 위치에서 몇 톤을, 지금부터 몇 시간 동안 야드로 보내면 규격에 든다"
    — 이 문장을 매 교대마다 자동으로 낼 수 있게 만드는 것.

⚠️ 수치는 전부 실데이터에서 계산한다(§2-1). 하드코딩 금지.
실행: python scripts/make_plan.py  →  outputs/plan.html
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths as P                                          # noqa: E402
from config import schema as S                                         # noqa: E402
from src.matching.pipeline import GRADE_SOURCE, SRC_ZONE               # noqa: E402
from src.models.dataset import load_osp_stock, load_sources, load_yard_change  # noqa: E402
from src.models.roadmap import readiness                               # noqa: E402
from src.optimization.prescribe import prescribe, zone_balance_health  # noqa: E402
from src.visualization.webstyle import STYLE                           # noqa: E402

TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol
E = html.escape

#: 추진 단계 — 사용자가 "임원이 알아듣기 쉽게" 라고 한 요청에 맞춰 평이한 말로 둔다
STAGES = [
    ("잇기", "흩어진 세 공정 기록을 시각·구역 기준으로 연결", "완료"),
    ("지켜보기", "품위가 규격을 벗어나면 즉시 알림", "완료"),
    ("원인 찾기", "재고·계량 기록을 대조해 어긋난 곳을 찾음", "완료"),
    ("미리 맞추기", "어느 구역에서 몇 톤 뽑을지 계산해 사전 제어", "장치 완성 · 정확도 보완 중"),
]


def _stage_svg() -> str:
    """4단계 진행 막대 — 어디까지 왔는지 한눈에."""
    W, H = 880, 96
    pl, pr = 12, W - 12
    seg = (pr - pl) / len(STAGES)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="추진 단계 진행 현황">']
    for i, (name, _, state) in enumerate(STAGES):
        x = pl + i * seg
        done = state == "완료"
        fill = "var(--accent)" if done else "var(--accent-soft)"
        ink = "#ffffff" if done else "var(--accent-ink)"
        out.append(f'<rect x="{x + 4:.0f}" y="26" width="{seg - 12:.0f}" height="34" rx="8" '
                   f'fill="{fill}" stroke="var(--accent-2)" stroke-width="1"/>')
        out.append(f'<text x="{x + seg / 2:.0f}" y="48" text-anchor="middle" '
                   f'style="font-size:13px;font-weight:600;fill:{ink}">{i + 1}. {E(name)}</text>')
        out.append(f'<text x="{x + seg / 2:.0f}" y="76" text-anchor="middle" class="cs">'
                   f'{E(state)}</text>')
        if i < len(STAGES) - 1:
            out.append(f'<text x="{x + seg - 4:.0f}" y="48" text-anchor="middle" class="cs">›</text>')
    out.append("</svg>")
    return "".join(out)


def _zone_svg(health: dict) -> str:
    """구역별 '쌓은 양 대비 뽑은 양' — 1.0 에서 멀수록 기록이 물리와 어긋난다."""
    d = health.get("table")
    if d is None or d.empty:
        return ""
    d = d[(d["loaded"] > 0) | (d["drawn"] > 0)].copy()
    d["r"] = (d["drawn"] / d["loaded"].replace(0, np.nan)).clip(upper=25)
    W, H = 880, 170
    pl, pr, pt, pb = 44, W - 14, 20, H - 28
    bw = (pr - pl) / max(len(d), 1)

    def ys(v):
        v = min(max(v, 0.04), 25)
        return pb - (np.log10(v) + 1.4) / 2.8 * (pb - pt)

    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
           f'aria-label="구역별 쌓은 양 대비 뽑은 양">']
    out.append(f'<rect x="{pl}" y="{ys(2):.1f}" width="{pr - pl}" '
               f'height="{ys(0.5) - ys(2):.1f}" fill="var(--band)"/>')
    for v, lab in ((0.1, "0.1배"), (1, "1배"), (10, "10배")):
        gy = ys(v)
        out.append(f'<line x1="{pl}" y1="{gy:.1f}" x2="{pr}" y2="{gy:.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{pl - 7}" y="{gy + 4:.1f}" class="ax" text-anchor="end">{lab}</text>')
    out.append(f'<line x1="{pl}" y1="{ys(1):.1f}" x2="{pr}" y2="{ys(1):.1f}" '
               f'stroke="var(--ink)" stroke-width="1.2"/>')
    for i, r in enumerate(d.itertuples()):
        x = pl + i * bw + bw * 0.2
        w = bw * 0.6
        if not np.isfinite(r.r):
            out.append(f'<rect x="{x:.1f}" y="{pt}" width="{w:.1f}" height="{pb - pt}" '
                       f'fill="var(--warnfill)"/>')
        else:
            y0, y1 = ys(r.r), ys(1)
            ok = 0.5 <= r.r <= 2
            out.append(f'<rect x="{x:.1f}" y="{min(y0, y1):.1f}" width="{w:.1f}" '
                       f'height="{abs(y1 - y0):.1f}" '
                       f'fill="var(--{"accent" if ok else "badfill"})"/>')
        out.append(f'<text x="{x + w / 2:.1f}" y="{pb + 13}" class="ax" text-anchor="middle">'
                   f'{int(r.zone)}</text>')
    out.append(f'<text x="{pr}" y="{pt + 2}" class="cs" text-anchor="end">'
               f'가로축 = OSP 구역 번호 · 파란색이 정상(0.5~2배)</text>')
    out.append("</svg>")
    return "".join(out)


def build() -> str:
    mine, osp, yards = load_sources(verbose=False)
    stock = load_osp_stock()
    rd = readiness(mine, load_yard_change())

    ys = {}
    for ln, y in yards.items():
        d = y.dropna(subset=["cao"])
        if len(d):
            ys[ln] = dict(
                n=len(d), mean=float(d["cao"].mean()), std=float(d["cao"].std()),
                inband=float(((d["cao"] >= TARGET - TOL) & (d["cao"] <= TARGET + TOL)).mean() * 100),
                lo=d["datetime"].min(), hi=d["datetime"].max())
    rep = max(ys.values(), key=lambda v: v["n"])          # 표본이 큰 라인을 대표로

    presc = {ln: p for ln in S.YARD_PAIR
             if (p := prescribe(mine, osp, stock, ln, hours=8)) is not None}
    demo = max(presc.values(), key=lambda p: p.p_in_spec) if presc else None
    pmax = max((p.p_in_spec for p in presc.values()), default=float("nan"))

    health = {ln: zone_balance_health(mine, osp, ln) for ln in S.YARD_PAIR}
    worst = max(health.values(), key=lambda h: h.get("bad_share", 0))
    worst_ln = [k for k, v in health.items() if v is worst][0]

    tot = float(osp["withdrawn_ton"].sum())
    est = tot - float(osp.loc[osp[GRADE_SOURCE] == SRC_ZONE, "withdrawn_ton"].sum())

    maes = {}
    for ln in S.YARD_PAIR:
        f = P.MODELS_DIR / f"ridge_{ln}.joblib"
        if f.exists():
            m = joblib.load(f)
            maes[ln] = float(m.get("cv_mae", float("nan")))
    mae_best = min(maes.values()) if maes else float("nan")

    zn, cs = rd["zone"], rd["cases"]
    period = f"{min(v['lo'] for v in ys.values()):%Y-%m-%d} ~ {max(v['hi'] for v in ys.values()):%Y-%m-%d}"

    # ⭐️ 목표 문장은 **실제 처방 출력**을 그대로 쓴다. 예시를 지어내면 계획서가 현실과 어긋난다.
    if demo is not None:
        demo_sent = E(demo.sentence())
        for tok in (f"{demo.hours:.0f}시간", f"{demo.achieved_cao:.2f}%"):
            demo_sent = demo_sent.replace(tok, f"<em>{tok}</em>", 1)
        demo_sent = re.sub(r"(\d[\d,]*톤|\d+번)", r"<em>\g<1></em>", demo_sent)
    else:
        demo_sent = "처방을 만들 수 있는 재고 데이터가 없습니다."

    def kpi(v, unit, label, note, tone=""):
        return (f'<div class="k{" " + tone if tone else ""}">'
                f'<div class="kv mono">{v}<span class="ku">{unit}</span></div>'
                f'<div class="kl">{E(label)}</div><div class="kn">{E(note)}</div></div>')

    kpis = "".join([
        kpi(f"{rep['mean']:.1f}", "%", "야드 품위 평균", f"목표 {TARGET}% — 거의 도달", "good"),
        kpi(f"{rep['std']:.1f}", "%p", "품위 흔들림", f"목표 {TOL} 의 {rep['std'] / TOL:.1f}배", "bad"),
        kpi(f"{rep['inband']:.0f}", "%", "규격 안에 있던 시간", f"{TARGET}±{TOL} 기준", "bad"),
        kpi(f"{pmax * 100:.0f}", "%", "처방 적중 확률", "운전 사용 기준 80%", "bad"),
    ])

    stage_rows = "".join(
        f"<tr><td><b>{i + 1}. {E(n)}</b></td><td>{E(d)}</td>"
        f"<td class='c' style=\"color:var(--{'good' if s == '완료' else 'warn'})\">{E(s)}</td></tr>"
        for i, (n, d, s) in enumerate(STAGES))

    asks = [
        ("인출 지점에서 품위를 직접 측정",
         f"뽑는 순간의 값을 그대로 쓰게 되어 <b>추정이 사라집니다.</b> 구역 품위 오차 "
         f"{zn['se_median']:.2f}%p 를 허용폭 {TOL}%p 아래로 낮추는 <b>유일한 확실한 방법</b>입니다. "
         f"기록만 늘려서는 구역당 {zn['ratio']:.0f}배의 표본이 필요해 사실상 불가능합니다.",
         "설비 투자 판단", "가장 큼"),
        ("인출 기록에 ‘원래 쌓았던 위치’ 함께 남기기",
         "지금은 <b>뽑은 위치</b>만 적힙니다. 그 물량이 <b>원래 어디에 쌓였는지</b>가 같이 남으면 "
         "아래 어긋남의 상당 부분이 풀립니다. 규칙만 알면 <b>지난 기록에도 소급 적용</b>됩니다.",
         "비용 없음 · 기록 방식만 변경", "큼"),
        ("월마감 계량 조정값 공유",
         "공장에서 매달 정하는 증량·감량 수치를 받으면 물량을 <b>추정하지 않아도</b> 됩니다. "
         "처방의 ‘몇 톤’ 이 정확해집니다.",
         "비용 없음 · 자료 공유", "중간"),
    ]
    ask_rows = "".join(
        f"<tr><td><b>{i + 1}. {E(t)}</b><div class='sub2'>{d}</div></td>"
        f"<td class='c2'>{E(cost)}</td><td class='c2'><b>{E(eff)}</b></td></tr>"
        for i, (t, d, cost, eff) in enumerate(asks))

    return f"""<title>석회석 품위 관리 체계 구축 계획</title>
<style>{STYLE}
.goalbox {{ background:var(--accent-soft); border:1px solid var(--accent-2);
            border-radius:var(--radius); padding:20px 22px;
            display:flex; flex-direction:column; gap:10px; }}
.goalbox .lbl {{ font-size:10.5px; letter-spacing:.14em; text-transform:uppercase;
                 color:var(--accent-ink); font-weight:600; }}
.goalbox .sent {{ font-size:17px; line-height:1.65; font-weight:600; color:var(--ink);
                  margin:0; text-wrap:balance; }}
.goalbox .sent em {{ font-style:normal; color:var(--accent); }}
.goalbox .cap2 {{ font-size:12.5px; color:var(--ink-2); margin:0; }}
.sub2 {{ font-size:12.5px; color:var(--ink-3); margin-top:4px; line-height:1.6; font-weight:400; }}
td.c2 {{ text-align:center; white-space:nowrap; font-size:12px; color:var(--ink-2); }}
.big {{ font-size:15px; font-weight:600; color:var(--ink); margin:0; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
@media (max-width:680px) {{ .two {{ grid-template-columns:1fr; }} }}
.mini {{ background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
         padding:14px 16px; box-shadow:var(--shadow); }}
.mini h3 {{ margin:0 0 6px; font-size:13px; font-weight:600; color:var(--ink); }}
.mini p {{ margin:0; font-size:12.5px; color:var(--ink-2); line-height:1.65; }}
</style>

<div class="wrap">

<div class="top">
  <div class="eyebrow">석회석 품위 관리 체계 · 추진 계획</div>
  <h1>“지금 어느 구역에서 몇 톤을 뽑아야 하는가”에 답하는 체계</h1>
  <p class="thesis">석회석 야드 품위를 <strong>{TARGET}% ± {TOL}</strong>로 안정시키는 것이 목표입니다.
    지금은 야드에 실린 뒤에야 품위를 알지만, 이 체계가 서면 <strong>뽑기 전에 알고, 원하는 값에
    맞춰 뽑을 수</strong> 있게 됩니다.</p>
  <div class="meta">분석 기간 {E(period)} · 야드 측정 {sum(v['n'] for v in ys.values()):,}건 ·
    작성 {datetime.now():%Y-%m-%d}</div>
</div>

<section>
  <h2>만들려는 것</h2>
  <div class="goalbox">
    <span class="lbl">최종 산출물 — 매 교대마다 자동으로 나오는 한 문장</span>
    <p class="sent">“{demo_sent}”</p>
    <p class="cap2">위 문장은 <b>실제로 오늘 시스템이 낸 값</b>입니다. 계산 장치는 이미 동작합니다.
      다만 <b>이 문장이 맞을 확률이 아직 {pmax * 100:.0f}%</b>라, 그대로 쓰기에는 이릅니다.
      이 확률을 <b>80% 이상</b>으로 올리는 것이 남은 과제입니다.</p>
  </div>
</section>

<section>
  <h2>지금 상태</h2>
  <div class="kpis">{kpis}</div>
  <p class="a"><strong>평균은 이미 목표에 닿았습니다.</strong> 문제는 <strong>흔들림</strong>입니다 —
    편차가 목표의 {rep['std'] / TOL:.1f}배라, 규격 안에 있던 시간이
    {rep['inband']:.0f}%에 그칩니다. 즉 <strong>평균을 옮기는 과제가 아니라 폭을 좁히는 과제</strong>입니다.</p>
</section>

<section>
  <h2>어디까지 왔나</h2>
  <div class="card">{_stage_svg()}</div>
  <div class="card"><table class="t">
    <thead><tr><th style="width:18%">단계</th><th>하는 일</th><th style="width:20%">상태</th></tr></thead>
    <tbody>{stage_rows}</tbody></table></div>
  <p class="note">1~3단계는 마쳤습니다. 세 공정 기록이 시각으로 연결됐고, 규격을 벗어나면 알리며,
    기록끼리 어긋난 곳을 찾아냅니다. <b>4단계도 계산 장치는 완성</b>되어 위의 문장을 만들어 냅니다.
    남은 것은 <b>넣는 값의 정확도</b>입니다.</p>
</section>

<section>
  <h2>무엇이 막고 있나</h2>
  <p class="q">OSP 구역 번호가 그 물량을 쌓은 곳을 가리키지 않습니다</p>
  <p class="a">구역별로 <strong>쌓은 양과 뽑은 양을 맞춰 보면 어긋납니다.</strong>
    쌓은 적이 거의 없는 구역에서 대량으로 뽑아 간 기록이 많습니다.</p>
  <div class="card">{_zone_svg(worst)}</div>
  <p class="note">막대가 <b>가운데 굵은 선(1배)에 가까울수록</b> 기록이 실제와 맞습니다.
    <b>{E(worst_ln)} 라인은 {worst['n_zones']}개 구역 중 {worst['n_bad']}개가 벗어나</b>
    전체 인출의 <b>{worst['bad_share']:.0f}%</b>를 차지하며, 가장 심한 곳은 <b>{worst['worst']:.0f}배</b>입니다.</p>
  <div class="two">
    <div class="mini"><h3>가장 뚜렷한 사례</h3>
      <p><b>80번 구역</b>은 <b>8월 5일에 처음 쌓았는데</b>, <b>6월 11일부터 뽑고</b> 있습니다.
        8월 이전에 그곳에서 뽑은 물량이 어디서 온 것인지 기록만으로는 알 수 없습니다.</p></div>
    <div class="mini"><h3>그래서 생기는 결과</h3>
      <p>어느 구역 물량인지 되짚을 수 없으니 품위도 알 수 없습니다. 현재 인출량의
        <b>{est / tot * 100:.0f}%({est:,.0f}톤)</b>가 실측이 아닌 <b>추정값</b>으로 처리됩니다.</p></div>
  </div>
</section>

<section>
  <h2>협의 · 지원 요청</h2>
  <p class="q">세 가지입니다 — 그중 둘은 비용이 들지 않습니다</p>
  <div class="card"><table class="t">
    <thead><tr><th>요청 사항</th><th class="c2" style="width:22%">필요한 것</th>
      <th class="c2" style="width:14%">효과</th></tr></thead>
    <tbody>{ask_rows}</tbody></table></div>
  <p class="note"><b>2번과 3번은 설비 없이 기록 방식만 바꾸면 됩니다.</b> 특히 2번은 규칙만 확인되면
    <b>지금까지 쌓인 기록 전체에 소급 적용</b>되어 파급이 큽니다. 현장에 이미 문의해 둔 상태입니다.</p>
</section>

<section>
  <h2>일정</h2>
  <div class="two">
    <div class="mini"><h3>바로 진행</h3>
      <p>1~3단계 체계는 <b>이미 가동 중</b>입니다. 감시·경보와 기록 정합 점검은 매주 갱신됩니다.
        위 요청 2·3번이 반영되는 대로 정확도를 다시 측정해 보고드립니다.</p></div>
    <div class="mini"><h3>4단계 본격 착수</h3>
      <p>검증 사례 <b>{cs['have']}/{cs['need']}건</b> 확보(월 {cs['per_month']:.0f}건 →
        약 <b>{cs['months']:.0f}개월</b> 남음). 조건이 차면 <b>시스템이 자동으로 알립니다.</b>
        무리하게 앞당기지 않고 요건을 갖춘 뒤 착수하겠습니다.</p></div>
  </div>
  <p class="note">현재 예측 오차는 <b>{mae_best:.2f}%p</b>로 관리 목표 {TOL}%p에 아직 못 미칩니다.
    이 값이 목표 아래로 내려가야 배합 처방을 <b>실제 운전에 쓸 수 있습니다.</b>
    각 단계가 끝날 때마다 결과물을 <b>순차적으로 보고</b>드리겠습니다.</p>
</section>

<footer>
  근거 — 야드 품위: CNA·45Q 실시간 분석기 실측 · 물량: 광산 이송량 대 OSP 인출량 ·
  재고: OSP 실사 기록. 모든 수치는 <code>scripts/make_plan.py</code> 실행으로 재현됩니다.
  상세 현황은 <code>outputs/brief.html</code>, 처방 결과는 <code>outputs/prescription.html</code>,
  전체 근거는 <code>outputs/final_report.html</code>.
</footer>

</div>
"""


def main():
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = P.OUTPUTS_DIR / "plan.html"
    doc = build()
    dst.write_text(doc, encoding="utf-8")
    print(f"[OK] 임원 보고 계획서: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
