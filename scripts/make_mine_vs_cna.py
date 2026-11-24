"""광산 품위(49Q 암분 + 47Q 감마레이) ↔ 신설 야드 CNA 비교 [Synthesis-Agent].

질문 (품질담당, 2026-11-24):
  "49Q 랑 47Q 까지 반영해서 증설(신설)라인 야드에 적재되는 CaO 를 비교하고 싶다.
   CNA 와 암분 품위 비교."

비교 두 가지 (src/visualization/mine_cna_data.py):
  ① 같은 날 — 광산이 그날 캔 돌(물량 가중) vs 그날 CNA 평균 (수준 비교)
  ② 추적    — OSP 더미 혼합 + 경로별 Time-Lag 로 야드 시각에 맞춘 광산 품위 vs CNA

실행: python scripts/make_mine_vs_cna.py [--month 2026-11]  →  outputs/mine_vs_cna_<월>.html
      (--month 없이 실행하면 메뉴용 outputs/mine_vs_cna.html 도 만든다)
"""

from __future__ import annotations

import argparse
import html
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths as P                                         # noqa: E402
from config import schema as S                                        # noqa: E402
from scripts.make_grade_swing import PAGE_CSS, Axis, _legend, _sc, _cl  # noqa: E402
from src.models.dataset import build_line_data, load_sources, load_yard_change  # noqa: E402
from src.visualization import mine_cna_data as M                      # noqa: E402
from src.visualization import swing_data as W                         # noqa: E402
from src.visualization.qmsstyle import DOC_STYLE, foot, hero, nav     # noqa: E402

E = html.escape
TARGET, TOL, HI, LO = W.TARGET, W.TOL, W.HI, W.LO
C_CNA, C_49, C_47, C_TR = "var(--ink)", "var(--s2)", "var(--s5)", "var(--s3)"


def _path(ax: Axis, s: pd.Series, gap: pd.Timedelta) -> str:
    """시계열 → polyline 여러 개 (gap 보다 긴 빈 곳은 끊는다)."""
    out, cur, prev = [], [], None
    for t, v in s.dropna().items():
        if prev is not None and t - prev > gap:
            out.append(cur)
            cur = []
        cur.append(f"{ax.x(t):.1f},{ax.y(v):.1f}")
        prev = t
    out.append(cur)
    return "".join(f'<polyline points="{" ".join(c)}"' + ' fill="none" stroke-linejoin="round" ' + "{st}/>"
                   for c in out if len(c) > 1)


def daily_svg(t0, t1, cna_d, traced_d, md) -> str:
    """일별: CNA 평균(검정) · 추적 광산 품위(초록) · 그날 캔 49Q(주황 점) · 47Q(분홍 네모)."""
    ax = Axis(t0, t1, 52, 984, 40, 51, 30, 330)
    o = ['<svg viewBox="0 0 1000 364" class="chart sw" role="img" aria-label="일별 광산 품위와 CNA 비교">']
    o += ax.frame(range(40, 52, 2), "일별 CaO (%)")
    one = pd.Timedelta(days=1, hours=12)
    o.append(_path(ax, traced_d, one).replace("{st}", f'stroke="{C_TR}" stroke-width="2.5"'))
    o.append(_path(ax, cna_d, one).replace("{st}", f'stroke="{C_CNA}" stroke-width="2.5"'))
    for t, v in md["49Q"].dropna().items():
        o.append(f'<circle cx="{ax.x(t + pd.Timedelta(hours=12)):.1f}" cy="{ax.y(v):.1f}" r="4.5" fill="{C_49}">'
                 f'<title>{t:%m/%d} 49Q 암분 {v:.2f}%</title></circle>')
    for t, v in md["47Q"].dropna().items():
        x, y = ax.x(t + pd.Timedelta(hours=12)), ax.y(v)
        o.append(f'<rect x="{x - 4:.1f}" y="{y - 4:.1f}" width="8" height="8" fill="{C_47}">'
                 f'<title>{t:%m/%d} 47Q 감마레이 {v:.2f}%</title></rect>')
    for t, v in cna_d.dropna().items():
        o.append(f'<circle cx="{ax.x(t):.1f}" cy="{ax.y(v):.1f}" r="3" fill="{C_CNA}">'
                 f'<title>{t:%m/%d} CNA {v:.2f}%</title></circle>')
    o += ax.days(t0, t1)
    o.append("</svg>")
    return "".join(o)


def pile_svg(pc: pd.DataFrame) -> str:
    """파일별 — 추적 광산 품위(초록) · CNA(검정) · 시트 확정(빈 원). 가로 거리 = 차이."""
    p = pc[(pc["traced_n"] > 0) | (pc["cna_n"] > 0)].reset_index(drop=True)
    if not len(p):
        return ""
    lo_v, hi_v, x0, x1, rh, pt = 41, 50, 190, 960, 30, 30
    sx = lambda v: _sc(_cl(v, lo_v, hi_v), lo_v, hi_v, x0, x1)       # noqa: E731
    H = pt + rh * len(p) + 10
    o = [f'<svg viewBox="0 0 1000 {H}" class="chart sw" role="img" aria-label="파일별 광산 추적 품위와 CNA">',
         f'<rect x="{sx(LO):.1f}" y="{pt - 12}" width="{sx(HI) - sx(LO):.1f}" height="{rh * len(p)}" fill="var(--band)"/>']
    for v in range(lo_v, hi_v + 1):
        o.append(f'<line x1="{sx(v):.1f}" y1="{pt - 12}" x2="{sx(v):.1f}" y2="{pt - 12 + rh * len(p)}" class="gr"/>')
        o.append(f'<text x="{sx(v):.1f}" y="{pt - 17}" text-anchor="middle">{v}</text>')
    for i, r in p.iterrows():
        y = pt + i * rh
        lab = f'{r["start"]:%m/%d %H시} → ' + (f'{r["end"]:%m/%d %H시}' if r["closed"] else "쌓는 중")
        o.append(f'<text x="{x0 - 10}" y="{y + 4}" text-anchor="end">{lab}</text>')
        if pd.notna(r["traced"]) and pd.notna(r["cna"]):
            o.append(f'<line x1="{sx(r["cna"]):.1f}" y1="{y}" x2="{sx(r["traced"]):.1f}" y2="{y}" '
                     f'stroke="var(--faint)" stroke-width="3"/>')
            d = r["traced"] - r["cna"]
            o.append(f'<text x="{max(sx(r["cna"]), sx(r["traced"])) + 10:.1f}" y="{y + 4}">{d:+.2f}%p</text>')
        if pd.notna(r["sheet_cao"]):
            o.append(f'<circle cx="{sx(r["sheet_cao"]):.1f}" cy="{y}" r="7" fill="none" stroke="{C_CNA}" '
                     f'stroke-width="1.5"><title>시트 확정 {r["sheet_cao"]:.2f}%</title></circle>')
        if pd.notna(r["cna"]):
            o.append(f'<circle cx="{sx(r["cna"]):.1f}" cy="{y}" r="5" fill="{C_CNA}">'
                     f'<title>CNA {r["cna"]:.2f}% ({r["cna_n"]}시간)</title></circle>')
        if pd.notna(r["traced"]):
            o.append(f'<circle cx="{sx(r["traced"]):.1f}" cy="{y}" r="5" fill="{C_TR}">'
                     f'<title>광산 추적 {r["traced"]:.2f}% ({r["traced_n"]}시간)</title></circle>')
    o.append("</svg>")
    return "".join(o)


def anomaly_svg(a: pd.Series, b: pd.Series) -> str:
    """일별 편차 산점도 — 각자 월평균을 뺀 값. 수준 차이를 지우고 '같이 오르내리나' 만 본다."""
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(j) < 3:
        return ""
    j = j - j.mean()
    mx = max(float(j.abs().max().max()), 1.0)
    step = 2.0 if mx > 3 else 1.0 if mx > 1.5 else 0.5
    lim = float(np.ceil(mx / step) * step)
    S_, pad = 340, 46
    sx = lambda v: _sc(v, -lim, lim, pad, S_ - 10)                    # noqa: E731
    sy = lambda v: _sc(v, -lim, lim, S_ - pad + 10, 14)               # noqa: E731
    o = [f'<svg viewBox="0 0 {S_} {S_}" class="chart" style="max-width:420px" role="img" '
         'aria-label="일별 편차 산점도">']
    for v in np.arange(-lim, lim + .01, step):
        o.append(f'<line x1="{sx(v):.1f}" y1="14" x2="{sx(v):.1f}" y2="{S_ - pad + 10}" class="gr"/>')
        o.append(f'<line x1="{pad}" y1="{sy(v):.1f}" x2="{S_ - 10}" y2="{sy(v):.1f}" class="gr"/>')
        o.append(f'<text x="{sx(v):.1f}" y="{S_ - pad + 26}" text-anchor="middle">{v:+g}</text>')
        o.append(f'<text x="{pad - 6}" y="{sy(v) + 4:.1f}" text-anchor="end">{v:+g}</text>')
    o.append(f'<line x1="{sx(-lim):.1f}" y1="{sy(-lim):.1f}" x2="{sx(lim):.1f}" y2="{sy(lim):.1f}" '
             f'stroke="var(--primary)" stroke-dasharray="4 4"/>')
    for t, r in j.iterrows():
        o.append(f'<circle cx="{sx(r["a"]):.1f}" cy="{sy(r["b"]):.1f}" r="4.5" fill="{C_TR}" fill-opacity=".8">'
                 f'<title>{t:%m/%d} 광산 추적 {r["a"]:+.2f} · CNA {r["b"]:+.2f}</title></circle>')
    o.append(f'<text x="{(pad + S_) / 2:.0f}" y="{S_ - 4}" text-anchor="middle">광산 추적 편차 (%p)</text>')
    o.append(f'<text x="12" y="{S_ / 2:.0f}" text-anchor="middle" transform="rotate(-90 12 {S_ / 2:.0f})">'
             'CNA 편차 (%p)</text></svg>')
    return "".join(o)


def build(month: str, line: str = S.LINE_NEW) -> str:
    mine, osp_exp, yards = load_sources(validate=False, verbose=False)
    yc = load_yard_change()
    m0 = pd.Timestamp(f"{month}-01")
    m1 = m0 + pd.offsets.MonthBegin(1)
    cna_raw = yards[line]
    ld = build_line_data(osp_exp, yards, line)

    mm = M.mine_period(mine, line, m0, m1)
    ms = M.mine_summary(mm)
    md = M.mine_daily(mm)
    cna_h = W.hourly(cna_raw, m0, m1)
    tr_all = M.traced_hourly(ld)
    tr_h = tr_all[(tr_all.index >= m0) & (tr_all.index < m1)]
    cna_d, tr_d = cna_h.resample("1D").mean(), tr_h.resample("1D").mean()
    ag_h, ag_d = M.agreement(tr_h, cna_h), M.agreement(tr_d, cna_d)
    ag_same = M.agreement(md["all"], cna_d)
    sw = W.month_swing(month, mine, yc, {line: cna_raw})[line]
    pc = M.pile_compare(sw.piles, tr_h, cna_h)
    pcd = pc[pc["closed"]].dropna(subset=["traced", "cna"])
    t_end = max(cna_h.index.max(), md.index.max() + pd.Timedelta(days=1)) if len(cna_h) else m1
    cna_m = float(cna_h.mean())
    ym = f"{m0.year}년 {m0.month}월"
    rl = ld.routes
    route_txt = ", ".join(f"{k}→{rl.dest} {v}시간" for k, v in rl.lags.items()) if rl is not None else ""

    def k(v, unit, label, note, cls=""):
        return (f'<div class="k {cls}"><div class="kv">{v}<span class="ku">{unit}</span></div>'
                f'<div class="kl">{label}</div><div class="kn">{note}</div></div>')

    kpis = "".join([
        k(f"{ms['49Q']['cao']:.2f}", "%", "광산 49Q 암분 XRF", f"{ym} {line} · {ms['49Q']['ton']:,.0f}톤 물량 가중"),
        k(f"{ms['47Q']['cao']:.2f}", "%", "광산 47Q 감마레이", f"{ym} {line} · {ms['47Q']['ton']:,.0f}톤 물량 가중"),
        k(f"{ms['all']['cao']:.2f}", "%", "광산 합계 (49Q+47Q)", f"{ms['all']['ton']:,.0f}톤"),
        k(f"{cna_m:.2f}", "%", "야드 CNA 평균", f"1시간 평균 {len(cna_h)}건", "good" if LO <= cna_m <= HI else "bad"),
        k(f"{ag_h['bias']:+.2f}", "%p", "광산 추적 − CNA", f"OSP 혼합·시간차 반영 · {ag_h['n']}시간 대조", "warn"),
        k(f"{ag_d['r']:.2f}", "", "일별 상관 (추적 vs CNA)", f"{ag_d['n']}일 · 1시간 단위 {ag_h['r']:.2f}", "warn"),
    ])
    lg = _legend([("야드 CNA", C_CNA, "ln"), ("광산 추적(OSP 혼합·시간차)", C_TR, "ln"),
                  ("그날 캔 49Q 암분", C_49, ""), ("그날 캔 47Q 감마레이", C_47, ""),
                  ("목표 44.1~45.1", "var(--band)", "")])
    period = f"{m0:%Y-%m-%d} ~ {t_end:%Y-%m-%d}"

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>암분 vs CNA</title>
<style>{DOC_STYLE}{PAGE_CSS}</style></head><body>
{nav(active="암분 vs CNA")}
{hero(
  eyebrow=f"{ym} · {line} 라인 · 광산 49Q+47Q → 야드 CNA",
  title=f"광산은 <em>{ms['all']['cao']:.1f}%</em>,<br>야드 CNA는 {cna_m:.1f}%",
  lead=f"{ym} {line} 라인으로 간 광산 원석의 품위(49Q 암분·47Q 감마레이, 물량 가중)는 "
       f"<b>{ms['all']['cao']:.2f}%</b>, 같은 기간 {line} 야드 CNA 평균은 <b>{cna_m:.2f}%</b>입니다. "
       f"OSP 더미 혼합과 운반 시간차를 반영해 맞춰도 광산 쪽이 <b>{ag_h['bias']:+.2f}%p</b> 높고, "
       f"날마다 오르내리는 방향도 약하게만 같이 움직입니다(일별 상관 {ag_d['r']:.2f}).",
  strip=f"데이터 {E(period)} · 원본 data/raw/{E(S.DATA_FILE)} · 생성 {S.now_local():%Y-%m-%d %H:%M}")}

<div class="wrap doc">
<div class="kpis">{kpis}</div>

<section>
  <h2>일별 비교</h2>
  <p class="q">광산 품위와 CNA는 날마다 얼마나 차이 나나?</p>
  <p class="a">초록 선(야드 시각으로 옮긴 광산 품위)이 검은 선(CNA)보다 높은 날이
    <strong>{int((tr_d - cna_d).dropna().gt(0).sum())}일 / {int((tr_d - cna_d).dropna().size)}일</strong>입니다.
    같은 날 캔 돌로 단순 비교해도 평균 <strong>{ag_same['bias']:+.2f}%p</strong>({ag_same['n']}일) 차이입니다.</p>
  <div class="card">{lg}{daily_svg(m0, t_end, cna_d, tr_d, md)}</div>
  <p class="note">주황 점(49Q 암분)·분홍 네모(47Q 감마레이)는 <b>그날 캔</b> 돌의 물량 가중 품위입니다. 이 돌이 야드에
    닿는 날은 다릅니다. 초록 선은 파이프라인이 광산 적재 품위를 OSP 더미 재고에 비례해 섞고, 경로별 운반 시간
    ({E(route_txt)})만큼 밀어 <b>야드에 도착하는 시각</b>에 맞춘 값입니다. 검은 선은 {line} 야드 CNA의 일평균입니다.</p>
</section>

<section>
  <h2>파일별</h2>
  <p class="q">야드 파일 하나 단위로 보면?</p>
  <p class="a">완료 파일 {len(pcd)}개 중 <strong>{int((pcd['traced'] > pcd['cna']).sum())}개</strong>에서 광산 추적값이
    CNA보다 높고, 차이는 <strong>{(pcd['traced'] - pcd['cna']).min():+.2f}~{(pcd['traced'] - pcd['cna']).max():+.2f}%p</strong>입니다.
    빈 원(시트 확정 품위)과 CNA의 평균 차이는 {(pcd['sheet_cao'] - pcd['cna']).abs().mean():.2f}%p로, <b>야드 시트의 확정 품위는 CNA 기준 값</b>으로 보입니다.</p>
  <div class="card">{_legend([("광산 추적", C_TR, ""), ("CNA", C_CNA, ""), ("목표 구간", "var(--band)", "")])}{pile_svg(pc)}</div>
  <p class="note">한 줄이 파일 하나입니다(야드변경 시각 사이). 회색 막대 길이가 광산 추적값과 CNA의 차이이며,
    오른쪽 숫자가 그 값입니다.</p>
</section>

<section>
  <h2>같이 움직이나</h2>
  <p class="q">수준 차이를 빼면, 오르내림은 맞나?</p>
  <p class="a">각자의 월평균을 빼고 날마다의 편차만 비교하면 상관은 <strong>{ag_d['r']:.2f}</strong>입니다.
    광산이 높게 들어온 날 CNA도 높아지는 경향은 <b>있지만 약합니다</b>. 1시간 단위 상관은 {ag_h['r']:.2f}입니다.</p>
  <div class="card" style="display:flex;justify-content:center">{anomaly_svg(tr_d, cna_d)}</div>
  <p class="note">점 하나가 하루입니다. 점선(기울기 1) 위에 모일수록 광산 변동이 야드에 그대로 전달된 것입니다.
    가로로 길게 퍼져 있으면 광산 쪽 흔들림이 OSP·야드에서 섞이며 줄어든 것입니다.</p>
</section>

<section>
  <h2>읽는 기준</h2>
  <ul class="facts">
    <li><b>암분 = 49Q XRF</b>(시추코어·암분 분석)이고, <b>47Q는 감마레이</b> 계측입니다. 두 계측을 물량 가중으로 합쳤습니다.</li>
    <li>광산 쪽이 2%p 남짓 높은 차이는 이 페이지만으로는 원인을 가릴 수 없습니다. 후보는 XRF·감마레이와 CNA의 계측 기준 차이,
      OSP에 남아 있던 기존 재고(품위 기록 없음)의 혼입, 광산 품위 시료의 대표성입니다.</li>
    <li>추적값의 시간차는 데이터로 추정한 경로별 값입니다({E(route_txt)}, 상관이 가장 높은 시간).</li>
    <li>계산 코드: <span class="mono">src/visualization/mine_cna_data.py</span> ·
      생성: <span class="mono">scripts/make_mine_vs_cna.py --month {month}</span></li>
  </ul>
</section>
</div>
{foot("석회석 광산–야드 품위(CaO) 매칭 및 추적 시스템 · SAMPYO")}
</body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="YYYY-MM (기본: 야드변경 마지막 기록의 월)")
    a = ap.parse_args([] if argv is None else argv)
    month = a.month or f"{load_yard_change()['datetime'].max():%Y-%m}"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = build(month)
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = P.OUTPUTS_DIR / f"mine_vs_cna_{month}.html"
    dst.write_text(doc, encoding="utf-8")
    if a.month is None:
        (P.OUTPUTS_DIR / "mine_vs_cna.html").write_text(doc, encoding="utf-8")
    print(f"[OK] 암분 vs CNA: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")
    return dst


if __name__ == "__main__":
    main(sys.argv[1:])
