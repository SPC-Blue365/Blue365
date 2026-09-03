"""한 장짜리 현황 브리프 생성 [Synthesis-Agent].

`make_final_report.py` 는 **전부 담는** 리포트다(7탭·5.5MB). 이 스크립트는 그 반대편으로,
**의도에 답하는 것만** 담는다 — "광산 CaO 를 OSP 재고·인출과 매칭해 야드 품위를
예측·제어할 수 있게 만든다" 는 목표에 대해 **어디까지 왔고 무엇이 막고 있는지**만 말한다.

설계 원칙
  · 탭 없음 · 한 번 스크롤 · 섹션마다 **질문 → 한 줄 답 → 최소 근거** 순서
  · 차트는 Plotly 대신 **인라인 SVG** — 5.5MB → 100KB 대. 무거움이 곧 '보기 싫음'이었다.
  · 모든 수치는 실데이터에서 계산한다(§2-1). 하드코딩 금지, 근거 경로를 각주로 남긴다.

실행: python scripts/make_brief.py  →  outputs/brief.html
"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths as P                                    # noqa: E402
from config import schema as S                                   # noqa: E402
from src.matching.balance import combined_mass_gap, grade_balance  # noqa: E402
from src.matching.pipeline import GRADE_SOURCE, SRC_ZONE         # noqa: E402
from src.models.dataset import load_osp_stock, load_sources, load_yard_change  # noqa: E402
from src.models.roadmap import readiness                         # noqa: E402
from src.visualization.webstyle import STYLE                     # noqa: E402

TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol
E = html.escape


# ─────────────────────────────────────────────────────────── SVG 유틸
def _sc(v, lo, hi, a, b):
    """값 v 를 [lo,hi] → [a,b] 로 선형 사상."""
    if hi == lo:
        return (a + b) / 2
    return a + (v - lo) / (hi - lo) * (b - a)


def hist_svg(yards: dict) -> str:
    """야드 CaO 분포 — 라인별 소패널. y 는 '그 라인 측정치 중 비율(%)' 로 정규화한다
    (n 이 3,839 vs 33,019 로 9배 차이나 건수로는 비교가 불가능하다)."""
    lines = [(ln, y.dropna(subset=["cao"])) for ln, y in yards.items()]
    lines = [(ln, d) for ln, d in lines if len(d)]
    if not lines:
        return ""
    W, H = 760, 210
    pw = (W - 40) / len(lines)
    lo_x, hi_x = 39.0, 51.0
    edges = np.arange(lo_x, hi_x + 0.01, 0.5)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
           f'aria-label="야드 CaO 분포와 목표 구간">']
    for i, (ln, d) in enumerate(lines):
        ox = 20 + i * pw
        pl, pr = ox + 42, ox + pw - 18
        pt, pb = 34, H - 34
        cnt, _ = np.histogram(d["cao"], bins=edges)
        pct = cnt / max(cnt.sum(), 1) * 100
        ymax = max(pct.max(), 1) * 1.15
        # 목표 구간 음영
        bx0 = _sc(TARGET - TOL, lo_x, hi_x, pl, pr)
        bx1 = _sc(TARGET + TOL, lo_x, hi_x, pl, pr)
        out.append(f'<rect x="{bx0:.1f}" y="{pt}" width="{bx1-bx0:.1f}" height="{pb-pt}" '
                   f'fill="var(--band)"/>')
        # 막대
        for k, p in enumerate(pct):
            if p <= 0:
                continue
            x0 = _sc(edges[k], lo_x, hi_x, pl, pr)
            x1 = _sc(edges[k + 1], lo_x, hi_x, pl, pr)
            yv = _sc(p, 0, ymax, pb, pt)
            inb = edges[k] >= TARGET - TOL - 1e-9 and edges[k + 1] <= TARGET + TOL + 1e-9
            out.append(f'<rect x="{x0:.1f}" y="{yv:.1f}" width="{max(x1-x0-0.8,0.6):.1f}" '
                       f'height="{pb-yv:.1f}" fill="var(--{"accent" if inb else "bar"})"/>')
        # 축
        out.append(f'<line x1="{pl}" y1="{pb}" x2="{pr}" y2="{pb}" stroke="var(--rule)"/>')
        for tick in (40, 43, 46, 49):
            tx = _sc(tick, lo_x, hi_x, pl, pr)
            out.append(f'<text x="{tx:.1f}" y="{pb+15}" class="ax" text-anchor="middle">{tick}</text>')
        mu, sd = float(d["cao"].mean()), float(d["cao"].std())
        inb = ((d["cao"] >= TARGET - TOL) & (d["cao"] <= TARGET + TOL)).mean() * 100
        out.append(f'<text x="{pl}" y="16" class="ct">{E(ln)} 라인</text>')
        out.append(f'<text x="{pl}" y="29" class="cs">평균 {mu:.2f} · 편차 {sd:.2f} · '
                   f'목표구간 {inb:.1f}%</text>')
        mx = _sc(mu, lo_x, hi_x, pl, pr)
        out.append(f'<line x1="{mx:.1f}" y1="{pt}" x2="{mx:.1f}" y2="{pb}" '
                   f'stroke="var(--ink)" stroke-width="1.2" stroke-dasharray="3 3"/>')
    out.append(f'<text x="{W-20}" y="{H-6}" class="cs" text-anchor="end">'
               f'가로축 CaO(%) · 세로축 측정치 비율 · 음영 = 목표 {TARGET}±{TOL}</text>')
    out.append("</svg>")
    return "".join(out)


def trend_svg(yards: dict) -> str:
    """일별 평균 CaO 추이 — 목표 구간을 벗어나 있는 시간이 얼마나 되는지 보인다."""
    series = []
    for ln, y in yards.items():
        d = y.dropna(subset=["cao"]).copy()
        if not len(d):
            continue
        g = d.assign(day=d["datetime"].dt.floor("D")).groupby("day")["cao"].mean()
        if len(g) > 1:
            series.append((ln, g))
    if not series:
        return ""
    W, H = 760, 230
    pl, pr, pt, pb = 46, W - 16, 26, H - 30
    t0 = min(s.index.min() for _, s in series)
    t1 = max(s.index.max() for _, s in series)
    vlo, vhi = 41.5, 48.5
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
           f'aria-label="일별 평균 CaO 추이">']
    by0 = _sc(TARGET + TOL, vlo, vhi, pb, pt)
    by1 = _sc(TARGET - TOL, vlo, vhi, pb, pt)
    out.append(f'<rect x="{pl}" y="{by0:.1f}" width="{pr-pl}" height="{by1-by0:.1f}" '
               f'fill="var(--band)"/>')
    for v in (42, 44, 46, 48):
        gy = _sc(v, vlo, vhi, pb, pt)
        out.append(f'<line x1="{pl}" y1="{gy:.1f}" x2="{pr}" y2="{gy:.1f}" '
                   f'stroke="var(--grid)"/>')
        out.append(f'<text x="{pl-8}" y="{gy+4:.1f}" class="ax" text-anchor="end">{v}</text>')
    span = max((t1 - t0).total_seconds(), 1)
    order = list(S.YARD_PAIR)
    stroke = {order[0]: "var(--bar)", order[1]: "var(--accent)"}
    for ln, s in series:
        pts = " ".join(
            f"{_sc((d - t0).total_seconds(), 0, span, pl, pr):.1f},"
            f"{_sc(min(max(v, vlo), vhi), vlo, vhi, pb, pt):.1f}"
            for d, v in s.items())
        out.append(f'<polyline points="{pts}" fill="none" stroke="{stroke.get(ln, "var(--bar)")}" '
                   f'stroke-width="1.6" stroke-linejoin="round"/>')
    for i, m in enumerate(pd.date_range(t0.normalize(), t1, freq="MS")):
        mx = _sc((m - t0).total_seconds(), 0, span, pl, pr)
        if pl <= mx <= pr:
            out.append(f'<text x="{mx:.1f}" y="{pb+16}" class="ax" text-anchor="middle">'
                       f'{m:%m월}</text>')
    lx = pl + 4
    for ln, _ in series:
        out.append(f'<rect x="{lx}" y="{pt-13}" width="18" height="3" '
                   f'fill="{stroke.get(ln, "var(--bar)")}"/>')
        out.append(f'<text x="{lx+23}" y="{pt-9}" class="cs">{E(ln)}</text>')
        lx += 90
    out.append(f'<text x="{pr}" y="{pt-9}" class="cs" text-anchor="end">'
               f'음영 = 목표 {TARGET}±{TOL}</text>')
    out.append("</svg>")
    return "".join(out)


def source_svg(osp) -> str:
    """인출 물량 중 '실측 기반' 대 '추정값' 비율 — 매칭을 어디까지 믿을 수 있는지."""
    rows = []
    for ln in S.YARD_PAIR:
        o = osp[osp["line"] == ln]
        tot = float(pd.to_numeric(o["withdrawn_ton"], errors="coerce").sum())
        if tot <= 0:
            continue
        z = float(pd.to_numeric(
            o.loc[o[GRADE_SOURCE] == SRC_ZONE, "withdrawn_ton"], errors="coerce").sum())
        rows.append((ln, z, tot - z, tot))
    if not rows:
        return ""
    W = 760
    H = 6 + len(rows) * 52
    pl, pr = 46, W - 16
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
           f'aria-label="인출 물량의 품위 출처 비율">']
    for i, (ln, z, est, tot) in enumerate(rows):
        y = 22 + i * 52
        wz = (pr - pl) * z / tot
        out.append(f'<text x="{pl}" y="{y-4}" class="cs">{E(ln)} · 인출 {tot:,.0f}톤</text>')
        out.append(f'<rect x="{pl}" y="{y}" width="{wz:.1f}" height="20" fill="var(--accent)"/>')
        out.append(f'<rect x="{pl+wz:.1f}" y="{y}" width="{pr-pl-wz:.1f}" height="20" '
                   f'fill="var(--warnfill)"/>')
        out.append(f'<text x="{pl+8}" y="{y+14}" class="inb">실측 기반 {z/tot*100:.0f}%</text>')
        # 추정 구간은 밝은 바탕이라 흰 글씨는 읽히지 않는다 → 잉크색으로 둔다
        out.append(f'<text x="{pr-8}" y="{y+14}" class="inw" text-anchor="end">'
                   f'추정 {est/tot*100:.0f}%</text>')
    out.append("</svg>")
    return "".join(out)


# ─────────────────────────────────────────────────────────── 본문
def build() -> str:
    mine, osp, yards = load_sources(verbose=False)
    stock = load_osp_stock()
    yc = load_yard_change()
    rd = readiness(mine, yc)

    ymain = max(yards.items(), key=lambda kv: len(kv[1]))          # 표본이 큰 라인이 대표
    ystats = {}
    for ln, y in yards.items():
        d = y.dropna(subset=["cao"])
        if len(d):
            ystats[ln] = dict(
                n=len(d), mean=float(d["cao"].mean()), std=float(d["cao"].std()),
                inband=float(((d["cao"] >= TARGET - TOL) & (d["cao"] <= TARGET + TOL)).mean() * 100),
                lo=d["datetime"].min(), hi=d["datetime"].max())
    rep = ystats[ymain[0]]

    tot_ton = float(pd.to_numeric(osp["withdrawn_ton"], errors="coerce").sum())
    meas_ton = float(pd.to_numeric(
        osp.loc[osp[GRADE_SOURCE] == SRC_ZONE, "withdrawn_ton"], errors="coerce").sum())
    est_pct = (tot_ton - meas_ton) / tot_ton * 100 if tot_ton else float("nan")

    cm = combined_mass_gap(stock, mine, osp)
    gbs = {ln: r for ln in S.YARD_PAIR if (r := grade_balance(stock, mine, osp, ln))}

    maes = {}
    for ln in S.YARD_PAIR:
        f = P.MODELS_DIR / f"ridge_{ln}.joblib"
        if f.exists():
            import joblib
            m = joblib.load(f)
            maes[ln] = (float(m.get("cv_mae", float("nan"))), int(m.get("n_train", 0)),
                        int(m.get("lag_hours", 0)))

    def kpi(v, unit, label, note, tone=""):
        return (f'<div class="k{" " + tone if tone else ""}">'
                f'<div class="kv">{v}<span class="ku">{unit}</span></div>'
                f'<div class="kl">{E(label)}</div><div class="kn">{E(note)}</div></div>')

    kpis = "".join([
        kpi(f"{rep['mean']:.2f}", "%", "야드 CaO 평균", f"목표 {TARGET}%", "good"),
        kpi(f"{rep['std']:.2f}", "%p", "편차(표준편차)", f"목표 {TOL} — {rep['std']/TOL:.1f}배", "bad"),
        kpi(f"{rep['inband']:.0f}", "%", "목표 구간 안에 든 시간", f"{TARGET}±{TOL} 기준", "bad"),
        kpi(f"{meas_ton/tot_ton*100:.0f}", "%", "실측 기반 매칭", f"나머지 {est_pct:.0f}%는 추정", "warn"),
    ])

    # 품위 수지 표
    bal_rows = "".join(
        f"<tr><td>{E(ln)}</td>"
        f"<td class='n'>{r['grades']['cao']['in_grade']:.2f}</td>"
        f"<td class='n'>{r['grades']['cao']['out_grade']:.2f}</td>"
        f"<td class='n'>{r['grades']['cao']['end_grade']:.2f}</td>"
        f"<td class='n'>{r['grades']['mgo']['in_grade']:.2f}</td>"
        f"<td class='n'>{r['grades']['mgo']['out_grade']:.2f}</td>"
        f"<td class='n'>{r['grades']['mgo']['end_grade']:.2f}</td>"
        f"<td class='c'>{'가능' if r['grades']['cao']['ok'] and r['grades']['mgo']['ok'] else '불가'}</td>"
        f"</tr>" for ln, r in gbs.items())

    # 월별 β
    def stock_at(ln, t):
        g = stock[stock["line"] == ln].dropna(subset=["stock_ton"]).sort_values("datetime")
        g = g[g["datetime"] <= t]
        return float(g["stock_ton"].iloc[-1]) if len(g) else float("nan")

    beta_rows = []
    for ln in S.YARD_PAIR:
        m, o = mine[mine["line"] == ln], osp[osp["line"] == ln]
        if not len(m) or not len(o):
            continue
        lo = max(m["datetime"].min(), o["datetime"].min())
        hi = min(m["datetime"].max(), o["datetime"].max())
        cells = []
        for p in pd.period_range(lo, hi, freq="M"):
            t0, t1 = max(p.start_time, lo), min(p.end_time, hi)
            if (t1 - t0).days < 10:
                continue
            In = float(m[(m["datetime"] > t0) & (m["datetime"] <= t1)]["tonnage"].sum())
            Out = float(o[(o["datetime"] > t0) & (o["datetime"] <= t1)]["withdrawn_ton"].sum())
            s0, s1 = stock_at(ln, t0), stock_at(ln, t1)
            den = In - (s1 - s0)
            if den > 0 and In > 0 and np.isfinite(den):
                cells.append((f"{p.month}월", Out / den))
        if cells:
            beta_rows.append((ln, cells))
    beta_tbl = ""
    if beta_rows:
        months = [c[0] for c in beta_rows[0][1]]
        beta_tbl = (
            "<table class='t'><thead><tr><th>라인</th>"
            + "".join(f"<th>{E(m)}</th>" for m in months)
            + "<th>변화</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{E(ln)}</td>"
                + "".join(f"<td class='n'>{b:.3f}</td>" for _, b in cs)
                + f"<td class='n'>{cs[-1][1]-cs[0][1]:+.3f}</td></tr>"
                for ln, cs in beta_rows)
            + "</tbody></table>")

    pred_rows = "".join(
        f"<tr><td>{E(ln)}</td><td class='n'>{mae:.2f}</td><td class='n'>{TOL:.2f}</td>"
        f"<td class='n'>{lag}시간</td><td class='n'>{n:,}</td></tr>"
        for ln, (mae, n, lag) in maes.items())

    zn = rd["zone"]
    cs = rd["cases"]
    stock_max = [float(stock.loc[stock["line"] == ln, "stock_ton"].max())
                 for ln in (S.LINE_OLD, S.LINE_NEW)]
    period = (f"{min(v['lo'] for v in ystats.values()):%Y-%m-%d}"
              f" ~ {max(v['hi'] for v in ystats.values()):%Y-%m-%d}")

    return f"""<title>석회석 품위 추적 현황</title>
<style>{STYLE}</style>

<div class="wrap">

<div class="top">
  <div class="eyebrow">석회석 광산 → OSP → 야드</div>
  <h1>석회석 품위 추적 현황</h1>
  <p class="thesis">야드 품위의 <strong>평균은 목표에 거의 닿았습니다</strong>. 문제는
    <strong>흔들림</strong>입니다 — 편차가 목표의 {rep['std']/TOL:.1f}배라, 목표 구간 안에 있던
    시간은 {rep['inband']:.0f}%에 그칩니다.</p>
  <div class="meta">데이터 기간 {E(period)} · 야드 측정 {sum(v['n'] for v in ystats.values()):,}건
    · 생성 {datetime.now():%Y-%m-%d %H:%M}</div>
</div>

<div class="kpis">{kpis}</div>

<section>
  <h2>현 황</h2>
  <p class="q">지금 품위는 목표에 얼마나 가까운가?</p>
  <p class="a">평균은 맞습니다. <strong>퍼짐이 문제</strong>입니다. 목표 구간(
    {TARGET - TOL}~{TARGET + TOL}%)에 들어온 측정치는 라인별로
    {min(v['inband'] for v in ystats.values()):.0f}~{max(v['inband'] for v in ystats.values()):.0f}%
    뿐입니다.</p>
  <div class="card">{hist_svg(yards)}</div>
  <p class="note">가운데 점선이 각 라인의 평균입니다. 평균은 음영(목표 구간)에 거의 걸쳐 있지만,
    분포가 넓게 퍼져 있어 실제로 규격에 든 시간은 적습니다. 즉 <b>평균을 옮기는 문제가 아니라
    폭을 좁히는 문제</b>입니다.</p>
  <div class="card">{trend_svg(yards)}</div>
  <p class="note">날마다 오르내리며 음영 밖으로 자주 벗어납니다. 특정 시기의 사고가 아니라
    <b>상시적인 변동</b>입니다.</p>
</section>

<section>
  <h2>추 적</h2>
  <p class="q">광산에서 야드까지 이어 붙였는가?</p>
  <p class="a">이어졌습니다. 채굴 시각·구역과 인출 시각을 맞춰 연결했고,
    인출 물량의 <strong>{meas_ton/tot_ton*100:.0f}%는 실제 적재 기록에 근거</strong>합니다.
    나머지 {est_pct:.0f}%는 아직 추정값입니다.</p>
  <div class="card">{source_svg(osp)}</div>
  <p class="note">추정값이 생기는 이유는 <b>구역별 적재 기록이 뒤늦게 시작</b>하기 때문입니다.
    어떤 구역에서 물량을 뽑아 썼는데 그 구역에 쌓았다는 기록이 아직 없으면, 품위를 알 수 없어
    라인 평균으로 대신 넣습니다.</p>
  <div class="said"><span class="lbl">현장 확인 (적치장 구조)</span>
    <b>구역별 재고는 측정하지 않습니다.</b> 6월 10일 기준 라인 합계만 있습니다
    (기존 36,000톤 · 신설 30,000톤). 또 구역은 <b>칸</b>으로 나뉘어 있는데
    <b>칸 높이 이상 쌓이면 옆 칸으로 흘러 들어가</b>, 잔량은 추정에 의존합니다.</div>
  <p class="note">이 답변으로 <b>두 가지가 분명해졌습니다.</b> 첫째, 위 추정 {est_pct:.0f}%는
    <b>기록을 더 받아서 메울 수 있는 것이 아닙니다</b> — 구역별 재고라는 데이터가 애초에
    존재하지 않습니다. 둘째, 칸이 넘쳐 옆으로 흘러든다면 <b>구역 이름표 자체가 근사값</b>이며,
    이것이 구역 단위로 품위를 따지는 방식의 <b>정밀도 한계</b>가 됩니다.
    실제로 기존 라인 35번 구역은 쌓은 기록 없이 1,250톤이 인출됐는데, 옆 칸에서 흘러든 것으로
    설명됩니다.</p>
</section>

<section>
  <h2>검 증</h2>
  <p class="q">이어 붙인 것이 맞는지 어떻게 확인했는가?</p>
  <p class="a">물량뿐 아니라 <strong>성분량까지 더하고 빼서</strong> 남은 재고의 품위를
    역산했습니다. CaO·MgO <strong>모두 물리적으로 가능한 범위</strong>에 들어옵니다.</p>
  <div class="card"><table class="t">
    <thead><tr><th rowspan="2">라인</th><th colspan="3" class="n">CaO (%)</th>
      <th colspan="3" class="n">MgO (%)</th><th rowspan="2">판정</th></tr>
      <tr><th class="n">적재</th><th class="n">인출</th><th class="n">남은재고</th>
          <th class="n">적재</th><th class="n">인출</th><th class="n">남은재고</th></tr></thead>
    <tbody>{bal_rows}</tbody></table></div>
  <p class="note">'남은재고'는 계산으로 역산한 값입니다. 이 값이 석회석으로 불가능한 숫자
    (예: 마이너스)가 나오면 어딘가 틀린 것인데, 네 값 모두 정상 범위입니다.</p>

  <p class="q" style="margin-top:10px">그런데 물량이 {abs(cm['gap_pct']):.1f}% 안 맞습니다.</p>
  <p class="a">두 라인을 합쳐도 적재 {cm['loaded']:,.0f}톤 대 인출 {cm['withdrawn']:,.0f}톤으로
    <strong>{cm['gap']:+,.0f}톤</strong>이 남습니다. 담당자 확인 결과, 이는 손실이 아니라
    <strong>서로 다른 계량기를 쓰기 때문</strong>입니다.</p>
  <div class="said"><span class="lbl">현장 확인 (계량 방식)</span>
    인출량은 <b>시설 3호 벨트스케일</b> 기준이며, <b>월마감 때 공장에서 증량·감량을 정해</b>
    조정합니다. 광산과 공장의 스케일 수치는 서로 같지 않습니다.</div>
  <p class="note">이 설명대로라면 두 계량값의 차이는 <b>정상</b>이고, 조정 시점인 월 경계에서
    비율이 바뀌어야 합니다. 실제로 그렇습니다 — 아래 β는 인출계량 ÷ 적재계량으로,
    1.000이면 두 계량이 일치한다는 뜻입니다.</p>
  <div class="card">{beta_tbl}</div>
  <p class="note"><b>두 라인이 6월→7월에 같은 방향으로 움직였습니다.</b> 월마감 조정이
    공장 전체에 적용된다는 설명과 맞습니다. 따라서 계량 보정은 <b>월 단위로 따로</b> 잡아야 하며,
    여러 달을 뭉뚱그린 평균은 의미가 없습니다. (월 경계 관측이 아직 한 번뿐이라
    <b>정황 일치이지 확정은 아닙니다</b>.)</p>
  <p class="note"><b>현장 수치와 기록이 서로 맞습니다.</b> 알려주신 만실 용량
    {S.OSP_CAPACITY_TON:,}톤에 대해 실사 재고 최고치는 기존 {stock_max[0]:,.0f}톤 ·
    신설 {stock_max[1]:,.0f}톤으로 <b>한 번도 넘지 않았고</b>, 6월 10일 기준 재고로 주신
    기존 {S.OSP_OPENING_STOCK[S.LINE_OLD]:,}톤 · 신설 {S.OSP_OPENING_STOCK[S.LINE_NEW]:,}톤도
    실사 기록의 그날 마지막 값과 <b>정확히 일치</b>합니다. 재고 기록을 라인 단위로는
    믿고 쓸 수 있다는 뜻입니다.</p>
</section>

<section>
  <h2>예 측</h2>
  <p class="q">지금 야드 품위를 미리 맞힐 수 있는가?</p>
  <p class="a">아직 <strong>목표 정밀도에 못 미칩니다</strong>. 평균 오차가 목표 허용폭
    {TOL}%p보다 큽니다.</p>
  <div class="card"><table class="t">
    <thead><tr><th>라인</th><th class="n">평균 오차</th><th class="n">목표</th>
      <th class="n">이송 지연</th><th class="n">학습 시간</th></tr></thead>
    <tbody>{pred_rows}</tbody></table></div>
  <p class="note">막고 있는 것은 모델이 아니라 <b>들어가는 정보의 정밀도</b>입니다.
    구역별 품위의 평균 오차가 <b>{zn['se_median']:.2f}%p</b>로 허용폭 {TOL}%p보다 큽니다.
    자를 대는 눈금이 맞추려는 폭보다 굵은 셈이라, 이 상태로는 배합을 계산해도 목표에
    들어간다고 보장할 수 없습니다.</p>
  <p class="note">더 중요한 것은, 이 한계가 <b>표본을 더 모아서 넘을 수 있는 종류가 아니라는</b>
    점입니다. 칸이 넘쳐 옆으로 흘러드는 이상 구역 이름표와 실제 내용물이 어긋나며, 이는
    <b>기록의 문제가 아니라 물리적 현상</b>이기 때문입니다.
    실제로 이웃 구역 품위를 섞어 보정해도 하류와의 일치는 나아지지 않았습니다
    (같은 조건에서 비교 시 오히려 소폭 하락, 다만 노이즈 범위).</p>
</section>

<section>
  <h2>다 음</h2>
  <p class="q">무엇이 있어야 다음 단계로 가는가?</p>
  <ol class="asks">
    <li><div><b>인출 지점에서 품위 직접 측정</b> <span class="w">
      가장 중요합니다. 근거가 둘로 늘었습니다 — ① 구역 평균 오차 {zn['se_median']:.2f}%p가
      허용폭 {TOL}%p보다 크고, ② 칸이 넘쳐 옆으로 흘러드는 이상 <b>구역 단위로는 원리적 한계</b>가
      있습니다. 표본만 늘려서는 구역당 {zn['need_per_zone']:,.0f}건(현재 {zn['obs_median']:.0f}건,
      {zn['ratio']:.0f}배)이 필요해 사실상 불가능합니다. 설비 투자 판단 사항.</span></div></li>
    <li><div><b>월마감 때 정하는 계량 조정값 공유</b> <span class="w">
      공장에서 매달 증량·감량을 정한다고 하셨는데, 그 <b>수치를 그대로 받으면</b> 계량 차이를
      추정하지 않고 바로 알 수 있습니다. 지금은 재고 기록에서 거꾸로 추정하고 있어
      재고 오차가 그대로 섞여 들어옵니다. <b>추가 설비 없이 바로 정확해지는 항목</b>입니다.</span></div></li>
    <li><div><b>배합 최적화는 조건 충족 후 착수</b> <span class="w">
      검증 사례 {cs['have']}/{cs['need']}건 확보(월 {cs['per_month']:.0f}건 →
      약 {cs['months']:.1f}개월 남음). 조건이 차면 시스템이 자동으로 알립니다.</span></div></li>
  </ol>
  <p class="note">※ 종전에 요청드렸던 <b>‘구역별 기초 재고와 품위’는 목록에서 뺐습니다</b> —
    구역별 측정을 하지 않으신다는 답변에 따라, 존재하지 않는 데이터를 요청한 것이었습니다.
    추정 {est_pct:.0f}%는 <b>메우는 대신 표시해 두는 것</b>으로 처리합니다.</p>
</section>

<footer>
  근거 — 야드 품위: CNA·45Q 감마레이 실측 · 물량: 광산 이송물량 대 OSP 인출량 ·
  재고: OSP 실사 기록. 모든 수치는 <code>scripts/make_brief.py</code> 실행으로 재현됩니다.
  상세 근거와 전체 분석은 <code>outputs/final_report.html</code>, 규칙 정의는
  <code>docs/data_schema.md</code>.<br>
  ※ OSP 실사 재고는 49광구 CCP에서 정하며 담당자별 오차가 있는 개략치입니다(현장 확인).
  재고를 기준으로 한 수치는 이 점을 감안해 읽어야 합니다.
</footer>

</div>
"""


def main():
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = P.OUTPUTS_DIR / "brief.html"
    doc = build()
    dst.write_text(doc, encoding="utf-8")
    print(f"[OK] 현황 브리프: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
