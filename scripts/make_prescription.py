"""배합 처방서 생성 [Synthesis-Agent] — 프로젝트의 **최종 산출물**.

사용자 의도를 그대로 답한다:
  "OSP 몇 번 위치에서 몇 톤을, 지금부터 몇 시간 야드로 적재하면 기준값에 들어오는가"

그래서 이 문서는 **처방으로 시작**한다. 추적·매칭·검증은 처방을 뒷받침하는 근거일 뿐이므로
뒤로 보내고, 앞에는 답과 **그 답을 믿어도 되는지**만 놓는다.

⭐️ 설계 원칙 — **확률 없는 처방은 내지 않는다.** 배합 계산은 쉽게 풀리지만, 들어가는 구역
   품위가 부정확하면 "계산상 44.6%" 는 공허하다. 규격 적중 확률을 늘 함께 낸다(§2-1).

실행: python scripts/make_prescription.py  →  outputs/prescription.html
"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths as P                                       # noqa: E402
from config import schema as S                                      # noqa: E402
from src.matching.inventory import zone_inventory                   # noqa: E402
from src.models.dataset import load_osp_stock, load_sources         # noqa: E402
from src.optimization.prescribe import prescribe, zone_balance_health  # noqa: E402
from src.visualization.webstyle import STYLE                        # noqa: E402

TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol
E = html.escape
HORIZONS = (4, 8, 12)


def _conf(p: float) -> tuple[str, str]:
    """적중 확률 → (등급, 색 클래스). 기준은 운전 판단에 쓸 수 있는가로 잡는다."""
    if not np.isfinite(p):
        return "판정 불가", "bad"
    if p >= 0.80:
        return "믿고 쓸 수 있음", "good"
    if p >= 0.60:
        return "참고용", "warn"
    return "아직 못 씀", "bad"


def _balance_svg(h: dict) -> str:
    """구역별 '적재 대비 인출 배율' — 1.0 에서 멀수록 그 구역 기록이 물리와 어긋난다."""
    d = h.get("table")
    if d is None or d.empty:
        return ""
    d = d[(d["loaded"] > 0) | (d["drawn"] > 0)].copy()
    d["r"] = (d["drawn"] / d["loaded"].replace(0, np.nan)).clip(upper=25)
    W, H = 760, 190
    pl, pr, pt, pb = 46, W - 14, 22, H - 30
    n = len(d)
    bw = (pr - pl) / max(n, 1)

    def ys(v):                       # 로그축 (배율은 1을 기준으로 대칭이라 로그가 맞다)
        v = min(max(v, 0.04), 25)
        return pb - (np.log10(v) + 1.4) / 2.8 * (pb - pt)

    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="구역별 적재 대비 인출 배율">']
    out.append(f'<rect x="{pl}" y="{ys(2):.1f}" width="{pr-pl}" height="{ys(0.5)-ys(2):.1f}" '
               f'fill="var(--band)"/>')
    for v, lab in ((0.1, "0.1"), (1, "1.0"), (10, "10")):
        gy = ys(v)
        out.append(f'<line x1="{pl}" y1="{gy:.1f}" x2="{pr}" y2="{gy:.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{pl-7}" y="{gy+4:.1f}" class="ax" text-anchor="end">{lab}</text>')
    out.append(f'<line x1="{pl}" y1="{ys(1):.1f}" x2="{pr}" y2="{ys(1):.1f}" '
               f'stroke="var(--ink)" stroke-width="1.1"/>')
    for i, r in enumerate(d.itertuples()):
        x = pl + i * bw + bw * 0.18
        w = bw * 0.64
        if not np.isfinite(r.r):
            out.append(f'<rect x="{x:.1f}" y="{pt}" width="{w:.1f}" height="{pb-pt}" '
                       f'fill="var(--warnfill)" opacity=".5"/>')
        else:
            y0, y1 = ys(r.r), ys(1)
            ok = 0.5 <= r.r <= 2
            out.append(f'<rect x="{x:.1f}" y="{min(y0,y1):.1f}" width="{w:.1f}" '
                       f'height="{abs(y1-y0):.1f}" fill="var(--{"accent" if ok else "badfill"})"/>')
        out.append(f'<text x="{x+w/2:.1f}" y="{pb+14}" class="ax" text-anchor="middle">'
                   f'{int(r.zone)}</text>')
    out.append(f'<text x="{pr}" y="{pt-6}" class="cs" text-anchor="end">'
               f'가로축 = OSP 구역 번호 · 세로축 = 인출÷적재 (로그) · 음영 = 0.5~2배</text>')
    out.append("</svg>")
    return "".join(out)


def _presc_block(p, health: dict) -> str:
    grade, tone = _conf(p.p_in_spec)
    rows = "".join(
        f"<tr><td><b>{int(r.zone)}번</b></td><td class='n'>{r.ton:,.0f}</td>"
        f"<td class='n'>{r.share:.0f}%</td><td class='n'>{r.cao:.2f}</td>"
        f"<td class='n'>{r.mgo:.2f}</td><td class='n'>±{r.se:.2f}</td>"
        f"<td class='n'>{r.available:,.0f}</td></tr>"
        for r in p.allocation.itertuples())
    warn = ""
    if not p.feasible:
        warn = (f"<div class='said'><span class='lbl'>목표 달성 불가</span>{E(p.message)}"
                + (f" 병목: {E(' · '.join(p.bottleneck))}." if p.bottleneck else "")
                + " 억지로 맞추지 않고 <b>가장 근접한 배합</b>을 냈습니다.</div>")
    return f"""
<div class="pcard">
  <div class="phead"><span class="pline">{E(p.line)} 라인</span>
    <span class="ptag {tone}">규격 적중 확률 {p.p_in_spec*100:.0f}% · {E(grade)}</span></div>
  <p class="psent">{E(p.sentence())}</p>
  <div class="pmeta">총 {p.demand_ton:,.0f}톤 · 인출 속도 {p.rate_tph:,.0f} 톤/시간 ·
    예상 CaO {p.achieved_cao:.2f}% <b>± {p.blend_se:.2f}</b> ·
    기준 {TARGET}±{TOL} · 기준시각 {p.at:%m/%d %H:%M}</div>
  {warn}
  <table class="t"><thead><tr><th>구역</th><th class="n">뽑을 양(톤)</th><th class="n">비중</th>
    <th class="n">CaO(%)</th><th class="n">MgO(%)</th><th class="n">품위 오차</th>
    <th class="n">재고(톤)</th></tr></thead><tbody>{rows}</tbody></table>
</div>"""


def build() -> str:
    mine, osp, yards = load_sources(verbose=False)
    stock = load_osp_stock()

    lines, healths, invs = [], {}, {}
    for ln in S.YARD_PAIR:
        inv = zone_inventory(mine, osp, stock, ln)
        if inv is None:
            continue
        invs[ln] = inv
        healths[ln] = zone_balance_health(mine, osp, ln)
        p = prescribe(mine, osp, stock, ln, hours=8, inv=inv)
        if p is not None and not p.allocation.empty:
            lines.append(p)
    if not lines:
        return "<title>배합 처방서</title><p>처방을 만들 수 있는 데이터가 없습니다.</p>"

    pmax = max(p.p_in_spec for p in lines if np.isfinite(p.p_in_spec))
    grade, tone = _conf(pmax)

    # 시간대별 표 — 캡션은 실제 추세에서 만든다(고정 문구를 쓰면 데이터와 어긋난다)
    hz_rows, trends = "", []
    for ln in [p.line for p in lines]:
        cells, ps = [], []
        for h in HORIZONS:
            q = prescribe(mine, osp, stock, ln, hours=h, inv=invs[ln])
            if q and not q.allocation.empty:
                ps.append(q.p_in_spec)
                cells.append(f"<td class='n'>{q.demand_ton:,.0f}톤<br>"
                             f"<span class='sub'>CaO {q.achieved_cao:.2f} · "
                             f"적중 {q.p_in_spec*100:.0f}%</span></td>")
            else:
                cells.append("<td class='n'>—</td>")
        hz_rows += f"<tr><td>{E(ln)}</td>{''.join(cells)}</tr>"
        if len(ps) >= 2:
            trends.append((ln, ps[0], ps[-1]))
    drops = [t for t in trends if t[1] - t[2] > 0.05]
    flats = [t for t in trends if abs(t[1] - t[2]) <= 0.05]
    bits = []
    if drops:
        bits.append(" · ".join(
            f"<b>{E(ln)}</b>은 길게 뽑을수록 오히려 떨어집니다"
            f"({a*100:.0f}% → {b*100:.0f}%)" for ln, a, b in drops)
            + " — 품위를 맞춰 줄 <b>재고가 먼저 바닥나기</b> 때문입니다")
    if flats:
        bits.append(" · ".join(f"<b>{E(ln)}</b>은 시간과 무관하게 {a*100:.0f}% 로 변화가 없습니다"
                               for ln, a, _ in flats)
                    + " — 재고가 넉넉해 <b>구역 품위를 모르는 것만</b> 남기 때문입니다")
    hz_note = "최근 2주 인출 속도로 환산한 값입니다. " + ". ".join(bits) + "."

    bad = max(healths.values(), key=lambda h: h.get("bad_share", 0))
    bad_ln = [k for k, v in healths.items() if v is bad][0]

    return f"""<title>배합 처방서</title>
<style>{STYLE}
.pcard {{ background:var(--surface); border:1px solid var(--rule); border-radius:3px;
          padding:20px; box-shadow:var(--shadow); display:flex; flex-direction:column; gap:12px;
          overflow-x:auto; }}
.phead {{ display:flex; align-items:center; justify-content:space-between; gap:12px;
          flex-wrap:wrap; }}
.pline {{ font-size:13px; font-weight:700; letter-spacing:.1em; color:var(--muted); }}
.ptag {{ font-size:12px; font-weight:700; padding:4px 11px; border-radius:99px;
         border:1px solid currentColor; white-space:nowrap; }}
.ptag.good {{ color:var(--good); }} .ptag.warn {{ color:var(--warn); }}
.ptag.bad {{ color:var(--bad); }}
.psent {{ font-size:19px; line-height:1.6; font-weight:600; margin:0; text-wrap:balance; }}
.pmeta {{ font-size:13px; color:var(--muted); margin:0; }}
.pmeta b {{ color:var(--ink); }}
.sub {{ font-size:11.5px; color:var(--muted); font-weight:400; }}
.verdict {{ border:1px solid var(--rule); border-left:3px solid var(--bad);
            background:var(--surface); border-radius:3px; padding:16px 18px; }}
.verdict h3 {{ margin:0 0 8px; font-size:16px; color:var(--bad); }}
.verdict p {{ margin:0 0 8px; font-size:15px; }}
.verdict p:last-child {{ margin-bottom:0; }}
</style>

<div class="wrap">

<div class="top">
  <div class="eyebrow">석회석 광산 → OSP → 야드 · 최종 산출</div>
  <h1>배합 처방서</h1>
  <p class="thesis">어느 구역에서 몇 톤을 몇 시간 동안 뽑으면 목표 품위
    <strong>{TARGET}±{TOL}%</strong>에 드는지 계산한 결과입니다.
    계산은 나왔지만 <strong>지금은 그대로 쓰기에 이릅니다</strong> — 이유를 아래에 적었습니다.</p>
  <div class="meta">기준시각 {max(p.at for p in lines):%Y-%m-%d %H:%M} ·
    생성 {datetime.now():%Y-%m-%d %H:%M}</div>
</div>

<section>
  <h2>처 방</h2>
  <p class="q">지금 뽑는다면, 이렇게 뽑으십시오</p>
  {"".join(_presc_block(p, healths.get(p.line, {})) for p in lines)}
  <p class="note"><b>‘품위 오차’</b>는 그 구역 품위를 얼마나 정확히 아는지입니다. 이 오차들이
    배합 비중대로 합쳐져 맨 위의 <b>± 값</b>이 되고, 거기서 <b>규격 적중 확률</b>이 나옵니다.
    확률이 낮으면 계산된 CaO가 목표와 같아도 <b>실제로는 벗어날 수 있다</b>는 뜻입니다.</p>
</section>

<section>
  <h2>시 간</h2>
  <p class="q">몇 시간 뽑으면 몇 톤인가?</p>
  <div class="card"><table class="t">
    <thead><tr><th>라인</th>{"".join(f"<th class='n'>{h}시간</th>" for h in HORIZONS)}</tr></thead>
    <tbody>{hz_rows}</tbody></table></div>
  <p class="note">{hz_note}</p>
</section>

<section>
  <h2>신 뢰 도</h2>
  <p class="q">이 처방을 믿고 써도 되는가?</p>
  <div class="verdict">
    <h3>아직 아닙니다 — 규격 적중 확률이 최대 {pmax*100:.0f}%입니다</h3>
    <p>동전 던지기와 비슷한 수준입니다. 처방대로 뽑아도 <b>절반 정도는 규격을 벗어납니다.</b>
      계산이 틀린 것이 아니라, <b>계산에 넣는 구역 품위를 정확히 모르기</b> 때문입니다.</p>
    <p>운전에 쓰려면 적중 확률이 <b>80% 이상</b>은 되어야 한다고 봅니다.</p>
  </div>
  <p class="q" style="margin-top:6px">왜 구역 품위를 모르는가?</p>
  <p class="a">가장 큰 이유는 <strong>인출 기록의 구역 번호가 그 물량을 쌓은 곳을
    가리키지 않기</strong> 때문입니다. 구역별로 쌓은 양과 뽑은 양을 맞춰 보면 어긋납니다.</p>
  <div class="card">{_balance_svg(bad)}</div>
  <p class="note">막대가 <b>가운데 굵은 선(1.0)에 가까울수록</b> 그 구역의 기록이 물리와 맞습니다.
    <b>{E(bad_ln)} 라인은 {bad['n_zones']}개 구역 중 {bad['n_bad']}개가 벗어나</b>
    전체 인출의 <b>{bad['bad_share']:.0f}%</b>를 차지하며, 최악은 <b>{bad['worst']:.0f}배</b>입니다.
    쌓은 적이 거의 없는 구역에서 대량으로 뽑아 갔다는 뜻이라, 그 물량의 품위를 알 수 없습니다.</p>
  <div class="said"><span class="lbl">현장 확인과 일치합니다</span>
    <b>90·100번에서 뽑고 90번 이전을 채운다</b>고 하셨습니다. 실제로 적재는 95·100번에 몰리고
    인출은 60~90번에서 일어납니다. 또 <b>칸 높이를 넘으면 옆 칸으로 흘러</b>들고
    <b>구역별 재고는 측정하지 않으므로</b>, 구역 번호는 위치 표시일 뿐 그 안의 품위를
    특정하지 못합니다.</div>
</section>

<section>
  <h2>다 음</h2>
  <p class="q">무엇을 하면 이 처방을 쓸 수 있게 되는가?</p>
  <ol class="asks">
    <li><div><b>인출 지점에서 품위를 직접 측정</b>
      <span class="w">이것 하나로 위 문제가 전부 풀립니다. 구역 번호로 품위를 <b>추정</b>할
      필요가 없어지고, 뽑는 순간의 값을 <b>그대로</b> 쓰게 됩니다. 적중 확률이 곧바로
      올라가는 유일한 방법입니다. 설비 투자 판단 사항.</span></div></li>
    <li><div><b>인출 기록에 ‘어디서 쌓은 물량인지’ 함께 남기기</b>
      <span class="w">설비 없이 할 수 있는 개선입니다. 지금은 <b>뽑은 위치</b>만 적히는데,
      그 물량이 <b>언제 어디서 온 것인지</b>가 함께 남으면 품위를 되짚을 수 있습니다.
      위 어긋남의 상당 부분이 여기서 해소됩니다.</span></div></li>
    <li><div><b>월마감 계량 조정값 공유</b>
      <span class="w">공장에서 정하는 증량·감량 수치를 받으면 물량을 추정하지 않아도 됩니다.
      처방의 ‘몇 톤’ 이 정확해집니다.</span></div></li>
  </ol>
  <p class="note">처방을 만드는 <b>계산 장치는 이미 완성되어 동작합니다</b>(위 표가 그
    결과물입니다). 남은 것은 <b>넣을 값의 정확도</b>뿐이며, 위 세 가지가 채워지는 만큼
    같은 화면의 확률이 그대로 올라갑니다.</p>
</section>

<footer>
  처방 계산 <code>src/optimization/prescribe.py</code> ·
  구역 재고 복원 <code>src/matching/inventory.py</code> ·
  재현 <code>python scripts/make_prescription.py</code>.
  현황은 <code>outputs/brief.html</code>, 상세 근거는 <code>outputs/final_report.html</code>.<br>
  ※ 구역별 재고는 측정값이 아니라 <b>적재−인출 흐름에서 복원한 추정치</b>이며, 라인 합계를
  실사 재고에 맞춰 보정했습니다. 구역별 수치는 이 한계를 감안해 읽어야 합니다.
</footer>

</div>
"""


def main():
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = P.OUTPUTS_DIR / "prescription.html"
    doc = build()
    dst.write_text(doc, encoding="utf-8")
    print(f"[OK] 배합 처방서: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
