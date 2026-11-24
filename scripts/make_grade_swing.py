"""월간 품위 번갈음 비교 — '평균은 맞췄지만 고·저품위를 번갈아 쌓아 맞췄다' [Synthesis-Agent].

질문 (품질담당, 2026-11-24):
  "야드 평균 CaO 는 목표를 맞췄지만 고품위를 쌓았다가 저품위를 쌓았다가 하면서
   평균으로 맞춘 것을 보여 달라."

데이터 (실데이터만, §2-1):
  · 광산 49Q XRF 암분 분석  `광산(49Q)_XRF`      → 교대별 CaO (src.visualization.swing_data.mine_shifts)
  · 야드 CNA 분석기(신설)    `CNA data`           → 1시간 평균 (swing_data.hourly)
  · 야드변경 기존·신설       `*라인 야드변경`     → 파일(더미)별 확정 품위 (swing_data.piles)
  야드변경 행 CaO 는 **그 시각에 끝난 파일의 품위**로 읽는다 — 근거는 swing_data 머리말과
  이 페이지의 '읽는 기준' 절(매번 재계산).

차트는 인라인 SVG(외부 라이브러리 없음) · QMS DOC_STYLE.

실행: python scripts/make_grade_swing.py [--month 2026-11]  →  outputs/grade_swing_<월>.html
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
from src.data import clean as C                                       # noqa: E402
from src.models.dataset import RAW_DIR, load_sources, load_yard_change  # noqa: E402
from src.visualization import swing_data as W                         # noqa: E402
from src.visualization.qmsstyle import DOC_STYLE, foot, hero, nav     # noqa: E402

E = html.escape
TARGET, TOL, HI, LO = W.TARGET, W.TOL, W.HI, W.LO
C_HI, C_LO, C_IN = "var(--s2)", "var(--s1)", "var(--faint)"

PAGE_CSS = """
.lg { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--muted); margin: 0 0 10px }
.lg span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap }
.lg i { display: inline-block; width: 14px; height: 10px; border-radius: 3px }
.lg i.ln { height: 4px; border-radius: 2px }
.sw { min-width: 680px }
svg.chart text { font-size: 13px; fill: var(--muted); font-variant-numeric: tabular-nums }
svg.chart text.v { fill: var(--ink); font-weight: 700 }
svg.chart text.t { fill: var(--ink2); font-weight: 700 }
svg.chart .gr { stroke: var(--line) }
.facts { margin: 0; padding-left: 18px; color: var(--muted); font-size: 14px; line-height: 1.8; max-width: 80ch }
.facts b { color: var(--ink2) }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px }
"""


# ───────────────────────────────────────────────────────── SVG 유틸
def _sc(v, lo, hi, a, b):
    return a + (v - lo) / (hi - lo) * (b - a) if hi != lo else (a + b) / 2


def _cl(v, lo, hi):
    return min(max(v, lo), hi)


class Axis:
    """시간축(x) + 품위축(y) 하나."""

    def __init__(self, t0, t1, x0, x1, vlo, vhi, y0, y1):
        self.t0, self.span = pd.Timestamp(t0), max((pd.Timestamp(t1) - pd.Timestamp(t0)).total_seconds(), 1)
        self.x0, self.x1, self.vlo, self.vhi, self.y0, self.y1 = x0, x1, vlo, vhi, y0, y1

    def x(self, t):
        return _sc((pd.Timestamp(t) - self.t0).total_seconds(), 0, self.span, self.x0, self.x1)

    def y(self, v):
        return _sc(_cl(v, self.vlo, self.vhi), self.vlo, self.vhi, self.y1, self.y0)

    def frame(self, ticks, label: str) -> list[str]:
        o = [f'<rect x="{self.x0}" y="{self.y(HI):.1f}" width="{self.x1 - self.x0}" '
             f'height="{self.y(LO) - self.y(HI):.1f}" fill="var(--band)"/>']
        for v in ticks:
            gy = self.y(v)
            o.append(f'<line x1="{self.x0}" y1="{gy:.1f}" x2="{self.x1}" y2="{gy:.1f}" class="gr"/>')
            o.append(f'<text x="{self.x0 - 8}" y="{gy + 4:.1f}" text-anchor="end">{v:g}</text>')
        o.append(f'<line x1="{self.x0}" y1="{self.y(TARGET):.1f}" x2="{self.x1}" y2="{self.y(TARGET):.1f}" '
                 f'stroke="var(--primary)" stroke-dasharray="4 4" stroke-width="1"/>')
        o.append(f'<text x="{self.x0}" y="{self.y0 - 8}" class="t">{label}</text>')
        return o

    def days(self, t0, t1, step: int = 2) -> list[str]:
        o = []
        for d in pd.date_range(pd.Timestamp(t0).normalize(), t1, freq=f"{step}D"):
            gx = self.x(d)
            if self.x0 <= gx <= self.x1:
                o.append(f'<line x1="{gx:.1f}" y1="{self.y1}" x2="{gx:.1f}" y2="{self.y1 + 5}" class="gr"/>')
                o.append(f'<text x="{gx:.1f}" y="{self.y1 + 19}" text-anchor="middle">{d.month}/{d.day}</text>')
        return o


def _lollipops(ax: Axis, sh: pd.DataFrame) -> list[str]:
    """광산 교대 CaO — 목표선에서 위(고품위)/아래(저품위)로 뻗는 막대. 점 크기 = 이송 물량."""
    o, ty = [], ax.y(TARGET)
    tmax = float(sh["tonnage"].max()) if len(sh) else 1.0
    for _, r in sh.iterrows():
        x, y = ax.x(r["datetime"]), ax.y(r["cao"])
        col = C_HI if r["cao"] > HI else C_LO if r["cao"] < LO else C_IN
        rad = 2.6 + 4.4 * np.sqrt(max(r["tonnage"], 0) / tmax) if tmax > 0 else 3
        o.append(f'<line x1="{x:.1f}" y1="{ty:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="2"/>')
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="{col}">'
                 f'<title>{r["datetime"]:%m/%d} {E(str(r["shift"]))} · CaO {r["cao"]:.2f}% · '
                 f'{r["tonnage"]:,.0f}톤</title></circle>')
    return o


def _pile_steps(ax: Axis, piles: pd.DataFrame, t_lo, t_hi, label_every: int = 1) -> list[str]:
    """파일 확정 품위 — 파일 구간 전체를 덮는 굵은 수평선 + 값. 진행 중 파일은 점선."""
    o = []
    for i, r in piles.iterrows():
        s, e = max(r["start"], t_lo), min(r["end"], t_hi)
        if e <= s:
            continue
        xs, xe = ax.x(s), ax.x(e)
        o.append(f'<line x1="{xs:.1f}" y1="{ax.y0}" x2="{xs:.1f}" y2="{ax.y1}" class="gr" '
                 f'stroke-dasharray="2 3"/>')
        if r["closed"] and pd.notna(r["sheet_cao"]):
            y = ax.y(r["sheet_cao"])
            o.append(f'<line x1="{xs + 1:.1f}" y1="{y:.1f}" x2="{xe - 1:.1f}" y2="{y:.1f}" '
                     f'stroke="var(--ink)" stroke-width="4" stroke-linecap="round">'
                     f'<title>파일 {r["start"]:%m/%d %H:%M} → {r["end"]:%m/%d %H:%M} · '
                     f'확정 CaO {r["sheet_cao"]:.2f}% · {r["sheet_ton"]:,.0f}톤</title></line>')
            if i % label_every == 0 and xe - xs > 34:
                o.append(f'<text x="{(xs + xe) / 2:.1f}" y="{y - 9:.1f}" text-anchor="middle" class="v">'
                         f'{r["sheet_cao"]:.2f}</text>')
        elif not r["closed"]:
            v = r.get("cna_mean")
            if pd.notna(v):
                y = ax.y(v)
                o.append(f'<line x1="{xs + 1:.1f}" y1="{y:.1f}" x2="{xe - 1:.1f}" y2="{y:.1f}" '
                         f'stroke="var(--ink)" stroke-width="3" stroke-dasharray="5 4"/>')
            o.append(f'<text x="{(xs + xe) / 2:.1f}" y="{ax.y0 + 14}" text-anchor="middle">쌓는 중</text>')
    return o


def _hourly_area(ax: Axis, h: pd.Series, cid: str) -> list[str]:
    """분석기 1시간 값 — 목표선 위는 주황(고품위), 아래는 파랑(저품위)으로 채운다. 2시간 넘게 빈 곳은 끊는다."""
    if not len(h):
        return []
    runs, cur, prev = [], [], None
    for t, v in h.items():
        if prev is not None and (t - prev) > pd.Timedelta(hours=2):
            runs.append(cur)
            cur = []
        cur.append((ax.x(t), ax.y(v)))
        prev = t
    runs.append(cur)
    ty = ax.y(TARGET)
    o = [f'<defs><clipPath id="{cid}u"><rect x="{ax.x0}" y="{ax.y0}" width="{ax.x1 - ax.x0}" '
         f'height="{ty - ax.y0:.1f}"/></clipPath>'
         f'<clipPath id="{cid}d"><rect x="{ax.x0}" y="{ty:.1f}" width="{ax.x1 - ax.x0}" '
         f'height="{ax.y1 - ty:.1f}"/></clipPath></defs>']
    for run in runs:
        if len(run) < 2:
            continue
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in run)
        poly = f"{run[0][0]:.1f},{ty:.1f} {pts} {run[-1][0]:.1f},{ty:.1f}"
        o.append(f'<polygon points="{poly}" fill="{C_HI}" fill-opacity=".38" clip-path="url(#{cid}u)"/>')
        o.append(f'<polygon points="{poly}" fill="{C_LO}" fill-opacity=".38" clip-path="url(#{cid}d)"/>')
        o.append(f'<polyline points="{pts}" fill="none" stroke="var(--muted)" stroke-width="1" '
                 f'stroke-linejoin="round"/>')
    return o


def timeline_svg(sw: W.LineSwing, t0, t1, analyzer_name: str | None) -> str:
    """위: 광산 49Q 교대 / 아래: 야드 분석기 1시간 + 파일 확정 품위. 같은 시간축."""
    Wd, pl, pr = 1000, 52, 984
    top = Axis(t0, t1, pl, pr, 38, 54, 30, 170)
    has_h = len(sw.hourly) > 0
    lo_v, hi_v = (39, 50) if has_h else (42, 51)
    bot = Axis(t0, t1, pl, pr, lo_v, hi_v, 222, 452)
    o = [f'<svg viewBox="0 0 {Wd} 486" class="chart sw" role="img" '
         f'aria-label="{E(sw.line)} 라인 광산 교대 품위와 야드 파일 품위 추이">']
    o += top.frame((40, 44, 48, 52), "광산 49Q 암분 분석 · 교대별 CaO (점 크기 = 이송 물량)")
    o += _lollipops(top, sw.shifts)
    lab = (f"야드 {analyzer_name} 1시간 평균 + 파일별 확정 품위(굵은 선)" if has_h
           else "야드 파일별 확정 품위(굵은 선 · 야드변경 시트)")
    o += bot.frame(range(int(np.ceil(lo_v)), int(hi_v) + 1, 2), lab)
    o += _hourly_area(bot, sw.hourly, f"c{abs(hash(sw.line)) % 9999}")
    o += _pile_steps(bot, sw.piles, pd.Timestamp(t0), pd.Timestamp(t1))
    o += bot.days(t0, t1)
    o.append("</svg>")
    return "".join(o)


def pile_swing_svg(sw: W.LineSwing, analyzer: pd.DataFrame) -> str:
    """파일별 흔들림 — 파일 하나에 저품위·목표·고품위 세 칸. 점 = 1시간 값,
    상자 = 평균 ± 표준편차, 가는 선 = 최소~최대. 칸 위 숫자 = 그 구간 표준편차."""
    p = sw.piles[sw.piles["n_hours"] > 0].reset_index(drop=True)
    if not len(p):
        return ""
    x0, x1, pt, pb, lo_v, hi_v = 52, 990, 34, 330, 38, 51
    sy = lambda v: _sc(_cl(v, lo_v, hi_v), lo_v, hi_v, pb, pt)        # noqa: E731
    cw = (x1 - x0) / len(p)
    o = [f'<svg viewBox="0 0 1000 384" class="chart sw" role="img" aria-label="파일별 저·목표·고품위 흔들림">',
         f'<rect x="{x0}" y="{sy(HI):.1f}" width="{x1 - x0}" height="{sy(LO) - sy(HI):.1f}" fill="var(--band)"/>']
    for v in range(lo_v + 1, hi_v + 1, 2):
        o.append(f'<line x1="{x0}" y1="{sy(v):.1f}" x2="{x1}" y2="{sy(v):.1f}" class="gr"/>')
        o.append(f'<text x="{x0 - 8}" y="{sy(v) + 4:.1f}" text-anchor="end">{v}</text>')
    rng = np.random.default_rng(11)
    cols = {"lo": C_LO, "in": "var(--muted)", "hi": C_HI}
    for i, r in p.iterrows():
        cx0 = x0 + i * cw
        if i:
            o.append(f'<line x1="{cx0:.1f}" y1="{pt - 20}" x2="{cx0:.1f}" y2="{pb + 6}" class="gr"/>')
        h = W.hourly(analyzer, r["start"], r["end"])
        sub = cw / 3
        for j, (k, part) in enumerate(W.band_parts(h).items()):
            cx = cx0 + sub * (j + .5)
            col = cols[k]
            for v in part:
                o.append(f'<circle cx="{cx + rng.uniform(-sub * .32, sub * .32):.1f}" cy="{sy(v):.1f}" r="2.2" '
                         f'fill="{col}" fill-opacity=".45"/>')
            if len(part):
                m = part.mean()
                sd = part.std() if len(part) > 1 else 0.0
                o.append(f'<line x1="{cx:.1f}" y1="{sy(part.min()):.1f}" x2="{cx:.1f}" y2="{sy(part.max()):.1f}" '
                         f'stroke="{col}" stroke-width="1.2"/>')
                o.append(f'<rect x="{cx - sub * .28:.1f}" y="{sy(m + sd):.1f}" width="{sub * .56:.1f}" '
                         f'height="{max(sy(m - sd) - sy(m + sd), 2):.1f}" fill="{col}" fill-opacity=".8" rx="2">'
                         f'<title>{["저품위", "목표", "고품위"][j]} · 평균 {m:.2f} ± {sd:.2f} · '
                         f'{part.min():.2f}~{part.max():.2f} · {len(part)}시간</title></rect>')
                o.append(f'<line x1="{cx - sub * .34:.1f}" y1="{sy(m):.1f}" x2="{cx + sub * .34:.1f}" y2="{sy(m):.1f}" '
                         f'stroke="var(--surface)" stroke-width="1.6"/>')
                o.append(f'<text x="{cx:.1f}" y="{pt - 6}" text-anchor="middle" style="font-size:11px;fill:{col}">'
                         f'{sd:.1f}</text>')
        lab1 = f'{r["start"]:%m/%d}~' + (f'{r["end"]:%m/%d}' if r["closed"] else "")
        o.append(f'<text x="{cx0 + cw / 2:.1f}" y="{pb + 22}" text-anchor="middle">{lab1}</text>')
        fin = f'{r["sheet_cao"]:.2f}' if r["closed"] and pd.notna(r["sheet_cao"]) else "(잠정)"
        o.append(f'<text x="{cx0 + cw / 2:.1f}" y="{pb + 40}" text-anchor="middle" class="v">{fin}</text>')
    o.append(f'<text x="{x0 - 8}" y="{pt - 6}" text-anchor="end" style="font-size:11px">σ</text>')
    o.append("</svg>")
    return "".join(o)


def composition_svg(sw: W.LineSwing) -> str:
    """파일별로 그 파일이 쌓이는 동안의 1시간 값이 저품위/목표/고품위에 있던 비율 + 확정 품위."""
    p = sw.piles[sw.piles["n_hours"] > 0].reset_index(drop=True)
    if not len(p):
        return ""
    rh, pt, x0, x1 = 30, 26, 190, 820
    H = pt + rh * len(p) + 30
    o = [f'<svg viewBox="0 0 1000 {H}" class="chart sw" role="img" aria-label="파일별 고·저품위 시간 비율">',
         f'<text x="{x0}" y="16">저품위 &lt;{LO:.1f}%</text>',
         f'<text x="{(x0 + x1) / 2:.0f}" y="16" text-anchor="middle">목표 {LO:.1f}~{HI:.1f}%</text>',
         f'<text x="{x1}" y="16" text-anchor="end">고품위 &gt;{HI:.1f}%</text>',
         '<text x="900" y="16" text-anchor="middle">확정 품위</text>']
    for i, r in p.iterrows():
        y = pt + i * rh
        lab = f'{r["start"]:%m/%d %H시} → ' + (f'{r["end"]:%m/%d %H시}' if r["closed"] else "쌓는 중")
        o.append(f'<text x="{x0 - 10}" y="{y + 15}" text-anchor="end">{lab}</text>')
        xs = x0
        for frac, col, op, name in ((r["lo"], C_LO, ".85", "저품위"), (r["inb"], "var(--well)", "1", "목표 구간"),
                                    (r["hi"], C_HI, ".85", "고품위")):
            w = (x1 - x0) * frac
            if w > 0:
                o.append(f'<rect x="{xs:.1f}" y="{y}" width="{w:.1f}" height="{rh - 8}" fill="{col}" '
                         f'fill-opacity="{op}"><title>{name} {frac * 100:.0f}% '
                         f'({r["n_hours"]}시간 중)</title></rect>')
                if w > 34:
                    fill = "var(--on-primary)" if col != "var(--well)" else "var(--muted)"
                    o.append(f'<text x="{xs + w / 2:.1f}" y="{y + 15}" text-anchor="middle" '
                             f'style="fill:{fill};font-size:12px;font-weight:700">{frac * 100:.0f}%</text>')
            xs += w
        if r["closed"] and pd.notna(r["sheet_cao"]):
            inb = LO <= r["sheet_cao"] <= HI
            o.append(f'<text x="900" y="{y + 15}" text-anchor="middle" class="v" '
                     f'style="fill:{"var(--ok-ink)" if inb else "var(--bad-ink)"}">{r["sheet_cao"]:.2f}%</text>')
        else:
            o.append(f'<text x="900" y="{y + 15}" text-anchor="middle">({r["cna_mean"]:.2f} 잠정)</text>')
    o.append("</svg>")
    return "".join(o)


def funnel_svg(rows: list[tuple[str, pd.Series, str]]) -> str:
    """같은 기간 같은 라인 — 단계별 값 분포. 점 = 개별 값, 막대 = 10~90% 범위, 세로선 = 평균."""
    lo_v, hi_v, x0, x1, rh, pt = 38, 54, 230, 960, 62, 34
    H = pt + rh * len(rows) + 26
    sx = lambda v: _sc(_cl(v, lo_v, hi_v), lo_v, hi_v, x0, x1)       # noqa: E731
    o = [f'<svg viewBox="0 0 1000 {H}" class="chart sw" role="img" aria-label="단계별 품위 분포 폭">',
         f'<rect x="{sx(LO):.1f}" y="{pt - 10}" width="{sx(HI) - sx(LO):.1f}" height="{rh * len(rows)}" '
         f'fill="var(--band)"/>']
    for v in range(40, 55, 2):
        o.append(f'<line x1="{sx(v):.1f}" y1="{pt - 10}" x2="{sx(v):.1f}" y2="{pt - 10 + rh * len(rows)}" class="gr"/>')
        o.append(f'<text x="{sx(v):.1f}" y="{pt - 16}" text-anchor="middle">{v}</text>')
    rng = np.random.default_rng(7)                       # 점 겹침 방지용 세로 흔들기(값은 그대로)
    for i, (name, s, sub) in enumerate(rows):
        s = s.dropna()
        cy = pt + i * rh + rh / 2 - 8
        o.append(f'<text x="{x0 - 14}" y="{cy - 2:.1f}" text-anchor="end" class="t">{E(name)}</text>')
        o.append(f'<text x="{x0 - 14}" y="{cy + 15:.1f}" text-anchor="end">{E(sub)}</text>')
        if not len(s):
            continue
        for v in s:
            col = C_HI if v > HI else C_LO if v < LO else "var(--muted)"
            o.append(f'<circle cx="{sx(v):.1f}" cy="{cy + rng.uniform(-9, 9):.1f}" r="2.6" fill="{col}" '
                     f'fill-opacity=".55"/>')
        a, b = s.quantile(.1), s.quantile(.9)
        o.append(f'<rect x="{sx(a):.1f}" y="{cy + 14:.1f}" width="{max(sx(b) - sx(a), 2):.1f}" height="6" rx="3" '
                 f'fill="var(--ink)" fill-opacity=".75"/>')
        m = s.mean()
        o.append(f'<line x1="{sx(m):.1f}" y1="{cy - 14:.1f}" x2="{sx(m):.1f}" y2="{cy + 22:.1f}" '
                 f'stroke="var(--ink)" stroke-width="2.5"/>')
        o.append(f'<text x="{min(sx(b) + 10, x1 - 4):.1f}" y="{cy + 22:.1f}" '
                 f'text-anchor="{"start" if sx(b) + 10 < x1 - 120 else "end"}">'
                 f'평균 {m:.2f} · 표준편차 {s.std():.2f}</text>')
    o.append("</svg>")
    return "".join(o)


def _cell(n, tot, m, sd) -> str:
    if not n:
        return '<td class="n">—</td>'
    sd_txt = f" ± {sd:.2f}" if pd.notna(sd) else ""
    return (f'<td class="n"><b>{m:.2f}</b>{sd_txt}<br>'
            f'<span style="color:var(--faint);font-size:12px">{n}시간 · {n / tot * 100:.0f}%</span></td>')


def band_table(sw: W.LineSwing, pooled: pd.Series) -> str:
    """파일별 — 저품위/목표/고품위 구간 안 1시간 값의 평균 ± 표준편차(시간 수·비율)."""
    p = sw.piles[sw.piles["n_hours"] > 0]
    if not len(p):
        return ""
    head = ('<tr><th>파일 (쌓은 기간)</th>'
            f'<th class="n" style="color:var(--s1)">저품위 &lt;{LO:.1f}</th>'
            f'<th class="n">목표 {LO:.1f}~{HI:.1f}</th>'
            f'<th class="n" style="color:var(--s2)">고품위 &gt;{HI:.1f}</th>'
            '<th class="n">CNA 전체</th><th class="n">확정 품위</th></tr>')
    body = []
    for _, r in p.iterrows():
        lab = f'{r["start"]:%m/%d %H시} → ' + (f'{r["end"]:%m/%d %H시}' if r["closed"] else "쌓는 중")
        tot = r["n_hours"]
        cells = "".join(_cell(int(r[f"{k}_n"]), tot, r[f"{k}_mean"], r[f"{k}_sd"]) for k in W.BANDS)
        fin = f'<b>{r["sheet_cao"]:.2f}</b>' if r["closed"] and pd.notna(r["sheet_cao"]) else "(잠정)"
        body.append(f'<tr><td style="white-space:nowrap">{lab}</td>{cells}'
                    f'<td class="n">{r["cna_mean"]:.2f} ± {r["cna_sd"]:.2f}</td><td class="n">{fin}</td></tr>')
    if len(pooled):
        parts = W.band_parts(pooled)
        cells = "".join(_cell(len(v), len(pooled), v.mean(), v.std() if len(v) > 1 else np.nan)
                        for v in parts.values())
        body.append(f'<tr style="background:var(--well)"><td><b>완료 파일 {len(sw.done)}개 합</b></td>{cells}'
                    f'<td class="n">{pooled.mean():.2f} ± {pooled.std():.2f}</td>'
                    f'<td class="n"><b>{sw.pile_mean:.2f}</b></td></tr>')
    return f'<div class="tbl"><table class="t">{head}{"".join(body)}</table></div>'


# ───────────────────────────────────────────────────────── 본문
def _legend(items) -> str:
    return '<div class="lg">' + "".join(
        f'<span><i class="{c}" style="background:{bg}"></i>{t}</span>' for t, bg, c in items) + "</div>"


def build(month: str) -> str:
    mine, _, _ = load_sources(validate=False, verbose=False)
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)
    cna = C.clean_yard(pd.read_excel(xls, S.YARD_PAIR[S.LINE_NEW][0]), load_col="적재물량(TPH)")
    old_an = C.clean_yard(pd.read_excel(xls, S.YARD_PAIR[S.LINE_OLD][0]))  # 해석 기준 검증에만 쓴다
    yc = load_yard_change()

    sw = W.month_swing(month, mine, yc, {S.LINE_NEW: cna, S.LINE_OLD: None})
    new, old = sw[S.LINE_NEW], sw[S.LINE_OLD]
    al_new = W.alignment_check(yc[yc["line"] == S.LINE_NEW], cna)
    al_old = W.alignment_check(yc[yc["line"] == S.LINE_OLD], old_an)

    m0 = pd.Timestamp(f"{month}-01")
    t1 = max(new.hourly.index.max() if len(new.hourly) else m0,
             new.shifts["datetime"].max() if len(new.shifts) else m0) + pd.Timedelta(hours=2)
    t0 = m0
    h = new.hourly
    h_in = float(((h >= LO) & (h <= HI)).mean() * 100) if len(h) else np.nan
    h_hi = float((h > HI).mean() * 100) if len(h) else np.nan
    h_lo = float((h < LO).mean() * 100) if len(h) else np.nan
    done = new.done
    n_ok = int(((done["sheet_cao"] >= LO) & (done["sheet_cao"] <= HI)).sum())
    sh = new.shifts
    sh_hi = int((sh["cao"] > HI).sum())
    sh_lo = int((sh["cao"] < LO).sum())
    swings = int((np.sign(h - TARGET).diff().abs() > 0).sum()) if len(h) else 0   # 목표선 교차 횟수
    days = max((h.index.max() - h.index.min()).total_seconds() / 86400, 1) if len(h) else 1
    mine_w = (float(np.average(sh["cao"], weights=sh["tonnage"]))
              if len(sh) and sh["tonnage"].sum() > 0 else np.nan)
    ym = f"{m0.year}년 {m0.month}월"
    period = f"{m0:%Y-%m-%d} ~ {t1 - pd.Timedelta(hours=2):%Y-%m-%d %H:%M}"

    kpis = f"""
<div class="k good"><div class="kv">{new.pile_mean:.2f}<span class="ku">%</span></div>
  <div class="kl">신설 야드 · {ym} 완료 파일 평균</div>
  <div class="kn">{len(done)}개 파일 물량 가중 · 목표 {TARGET}±{TOL} · {n_ok}/{len(done)}개 구간 안</div></div>
<div class="k good"><div class="kv">{new.pile_sd:.2f}<span class="ku">%p</span></div>
  <div class="kl">파일 사이 표준편차</div><div class="kn">목표 ±{TOL} 기준 안 — 파일 단위로는 고르다</div></div>
<div class="k bad"><div class="kv">{h_in:.0f}<span class="ku">%</span></div>
  <div class="kl">CNA 1시간 값이 목표 구간에 든 비율</div>
  <div class="kn">고품위 {h_hi:.0f}% · 저품위 {h_lo:.0f}% · 목표선 교차 하루 {swings / days:.1f}회</div></div>
<div class="k warn"><div class="kv" style="white-space:nowrap">{sh['cao'].min():.1f}<span class="ku">~</span>{sh['cao'].max():.1f}</div>
  <div class="kl">광산 49Q 교대별 CaO 범위 (신설)</div>
  <div class="kn">{len(sh)}교대 · 고품위 {sh_hi} · 저품위 {sh_lo} · 표준편차 {sh['cao'].std():.2f}</div></div>
<div class="k bad"><div class="kv">{old.pile_mean:.2f}<span class="ku">%</span></div>
  <div class="kl">기존 야드 · {ym} 완료 파일 평균</div>
  <div class="kn">{len(old.done)}개 파일 · 목표 상한 {HI:.1f} 위</div></div>"""

    lg_time = _legend([("고품위(목표 위)", C_HI, ""), ("저품위(목표 아래)", C_LO, ""),
                       ("목표 구간 44.1~45.1", "var(--band)", ""), ("파일 확정 품위", "var(--ink)", "ln")])
    funnel = funnel_svg([
        ("광산 49Q 암분", sh["cao"], f"교대별 {len(sh)}건"),
        ("야드 CNA", h, f"1시간 평균 {len(h)}건"),
        ("야드 파일", done["sheet_cao"], f"완료 파일 {len(done)}개"),
    ])
    old_t1 = max(old.shifts["datetime"].max() if len(old.shifts) else m0,
                 old.piles["end"].max() if len(old.piles) else m0) + pd.Timedelta(hours=6)

    gap = mine_w - new.pile_mean
    pooled = (W.hourly(cna, done["start"].min(), done["end"].max()) if len(done) else pd.Series(dtype=float))
    pp = W.band_parts(pooled)
    hi_m, lo_m = pp["hi"].mean(), pp["lo"].mean()
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{ym} 품위 번갈음</title>
<style>{DOC_STYLE}{PAGE_CSS}</style></head><body>
{nav(active="품위 번갈음")}
{hero(
  eyebrow=f"{ym} · 광산 49Q → 야드",
  title=f"평균은 <em>{new.pile_mean:.1f}%</em>,<br>그 안은 고·저품위의 번갈음",
  lead=f"신설 야드의 {ym} 파일 평균은 <b>{new.pile_mean:.2f}%</b>로 목표({TARGET}±{TOL})에 들었습니다. "
       f"그러나 같은 기간 CNA 1시간 값은 목표 구간 안에 <b>{h_in:.0f}%</b>만 머물렀고, "
       f"나머지는 고품위({h_hi:.0f}%)와 저품위({h_lo:.0f}%)를 오갔습니다. "
       f"<b>고르게 쌓아서가 아니라, 높고 낮은 것을 번갈아 쌓아 평균을 맞춘 것</b>입니다.",
  strip=f"데이터 {E(period)} · 원본 data/raw/{E(S.DATA_FILE)} · 생성 {S.now_local():%Y-%m-%d %H:%M}")}

<div class="wrap doc">

<div class="kpis">{kpis}</div>

<section>
  <h2>번갈아 쌓기</h2>
  <p class="q">평균은 어떻게 맞춰졌나?</p>
  <p class="a">광산에서는 교대마다 <strong>{sh['cao'].min():.1f}%부터 {sh['cao'].max():.1f}%까지</strong>
    오르내리는 돌이 들어왔고, 야드 CNA도 목표선을 <strong>하루 {swings / days:.1f}번</strong> 넘나들었습니다.
    그런데 파일 하나가 다 쌓이고 나면(굵은 선) 값은 {done['sheet_cao'].min():.2f}~{done['sheet_cao'].max():.2f}%로
    목표 구간 안에 모입니다.</p>
  <div class="card">{lg_time}{timeline_svg(new, t0, t1, "CNA")}</div>
  <p class="note">위 칸: 교대 하나가 막대 하나입니다. 목표선({TARGET}%) 위로 뻗으면 고품위, 아래로 뻗으면 저품위입니다.
    아래 칸: 주황 면은 CNA가 목표보다 높았던 시간, 파랑 면은 낮았던 시간입니다. 굵은 선은 야드변경 시트에 기록된
    그 파일의 확정 품위이며, 점선 세로줄이 파일이 바뀐 시각입니다. 광산 값은 <b>채굴 시각</b>에 찍혀 있습니다.
    OSP를 거쳐 야드에 닿기까지 시간차가 있으므로, 위아래 칸을 시각 단위로 맞대어 읽지 말고 <b>흔들리는 폭</b>만 비교하세요.</p>
</section>

<section>
  <h2>파일 속</h2>
  <p class="q">파일 하나 안에서는 고르게 쌓였나?</p>
  <p class="a">아닙니다. 완료된 {len(done)}개 파일 모두 확정 품위는 목표 안이지만, 쌓는 동안 CNA 값이 목표 구간에 머문
    시간은 파일마다 <strong>{done['inb'].min() * 100:.0f}~{done['inb'].max() * 100:.0f}%</strong>뿐입니다.
    나머지 시간은 <b>고품위와 저품위가 서로를 상쇄</b>했습니다.</p>
  <div class="card">{composition_svg(new)}</div>
  <p class="note">막대 하나가 파일 하나입니다. 그 파일을 쌓는 동안의 CNA 1시간 평균값을 저품위(파랑)·목표(회색)·고품위(주황)로
    나눠 시간 비율로 보였습니다. CNA의 적재물량 단위가 확인되지 않아 톤이 아니라 <b>시간</b> 기준입니다.
    오른쪽 값은 야드변경 시트의 확정 품위입니다.</p>
  <p class="q">고품위·저품위는 각각 얼마나 높고 낮았나?</p>
  <p class="a">완료 파일 {len(done)}개를 합쳐 보면 고품위 시간의 평균은 <strong>{hi_m:.2f}%</strong>
    (목표보다 +{hi_m - TARGET:.2f}%p), 저품위 시간의 평균은 <strong>{lo_m:.2f}%</strong>({lo_m - TARGET:+.2f}%p)입니다.
    목표 구간 안 시간의 평균은 {pp['in'].mean():.2f}%입니다. <b>위아래로 비슷한 거리만큼 벗어난 값들이 서로를 지워</b>
    파일 평균이 목표에 닿았습니다.</p>
  <p class="q">파일 하나를 쌓는 동안 각 구간은 얼마나 흔들렸나?</p>
  <p class="a">목표 구간 안의 값은 파일마다 표준편차 <strong>{done['in_sd'].min():.2f}~{done['in_sd'].max():.2f}</strong>로
    좁게 머물지만, 저품위는 <strong>{done['lo_sd'].min():.2f}~{done['lo_sd'].max():.2f}</strong>,
    고품위는 <strong>{done['hi_sd'].min():.2f}~{done['hi_sd'].max():.2f}</strong>로 파일에 따라 크게 달랐습니다.
    가장 크게 흔들린 파일은 {done.loc[done['cna_sd'].idxmax(), 'start']:%m/%d}~{done.loc[done['cna_sd'].idxmax(), 'end']:%m/%d}
    (전체 표준편차 {done['cna_sd'].max():.2f})입니다.</p>
  <div class="card">{_legend([("저품위", C_LO, ""), ("목표 구간 안", "var(--muted)", ""), ("고품위", C_HI, "")])}
    {pile_swing_svg(new, cna)}</div>
  <p class="note">파일 하나에 칸 세 개(저품위·목표·고품위)가 있습니다. 점 하나가 CNA 1시간 값입니다. 진한 상자는 평균 ± 표준편차,
    가는 세로선은 최솟값~최댓값, 상자 속 흰 선은 평균입니다. 맨 위 작은 숫자가 그 칸의 표준편차(σ)이고, 맨 아래 굵은 숫자가 파일의 확정 품위입니다.</p>
  <div class="card">{band_table(new, pooled)}</div>
  <p class="note">칸마다 <b>평균 ± 표준편차</b>(CaO %)이고, 아랫줄은 그 구간에 든 시간 수와 파일 안에서의 비율입니다.
    값은 CNA 2분 측정을 1시간 평균한 것입니다. 경계값(44.1·45.1)은 목표 구간에 넣었습니다.
    'CNA 전체'는 그 파일을 쌓는 동안의 1시간 값 전체의 평균 ± 표준편차이고, '확정 품위'는 야드변경 시트 값입니다.</p>
</section>

<section>
  <h2>폭 좁히기</h2>
  <p class="q">단계를 거치며 무엇이 달라졌나?</p>
  <p class="a">평균은 단계마다 크게 움직이지 않지만, <strong>폭</strong>은 광산 교대 표준편차
    {sh['cao'].std():.2f} → 야드 1시간 {h.std():.2f} → 파일 {new.pile_sd:.2f}로 줄어듭니다.
    섞이고 쌓이면서 평균이 되는 것이지, <b>들어오는 돌이 고른 것은 아닙니다</b>.</p>
  <div class="card">{funnel}</div>
  <p class="note">점 하나가 값 하나, 검은 막대가 10~90% 범위, 세로선이 평균입니다. 광산 49Q 평균
    ({sh['cao'].mean():.2f}%, 물량 가중 {mine_w:.2f}%)이 야드 파일 평균보다 <b>{gap:.1f}%p 높은</b> 점은 이 그래프로는
    설명할 수 없습니다. 이 차이는 이미 알려진 광산–야드 품위 격차(OSP 기존 재고 혼입, 47Q 감마레이 원료,
    XRF·CNA 계측 차이 후보)와 같은 문제로, 여기서는 <b>흔들림의 폭</b>만 비교합니다.</p>
</section>

<section>
  <h2>기존 라인</h2>
  <p class="q">기존 라인도 같은가?</p>
  <p class="a">기존 야드는 {ym} 완료 파일 {len(old.done)}개의 평균이 <strong>{old.pile_mean:.2f}%</strong>로
    <b>목표 상한({HI:.1f}%)보다 높습니다</b>. 평균도 맞추지 못했습니다. 광산 49Q 기존 교대는
    {len(old.shifts)}건으로 {old.shifts['cao'].min():.1f}~{old.shifts['cao'].max():.1f}% 범위였습니다.</p>
  <div class="card">{_legend([("고품위", C_HI, ""), ("저품위", C_LO, ""), ("파일 확정 품위", "var(--ink)", "ln")])}
    {timeline_svg(old, m0, old_t1, None)}</div>
  <p class="note">기존 야드 분석기(45Q 감마레이)는 이번 요청 범위에 없어 그리지 않았습니다. 파일 확정 품위는
    기존라인 야드변경 시트 값입니다.</p>
</section>

<section>
  <h2>읽는 기준</h2>
  <p class="q">야드변경 시트의 CaO는 어느 파일의 값인가?</p>
  <p class="a">데이터로 보면 <strong>그 행의 시각에 다 쌓인(직전) 파일의 품위</strong>입니다. 이 페이지는 그렇게 읽었습니다.</p>
  <ul class="facts">
    <li>신설 {al_new['n']}행 대조: '그 시각부터 쌓은 파일'로 읽으면 CNA 평균과 상관 <b>r={al_new['forward']['r']:.2f}</b>
      · 평균 차이 {al_new['forward']['mae']:.2f}%p, '그 시각까지 쌓은 파일'로 읽으면 <b>r={al_new['previous']['r']:.2f}</b>
      · 평균 차이 <b>{al_new['previous']['mae']:.2f}%p</b>.</li>
    <li>기존 {al_old['n']}행(45Q 감마레이 대조): 앞 파일 r={al_old['forward']['r']:.2f} · 직전 파일
      r={al_old['previous']['r']:.2f}. 신설만큼 뚜렷하지는 않지만 같은 방향입니다.</li>
    <li>종전 문서(data_schema §0)는 '그 시점부터 적재한 물량·품위'로 적혀 있었습니다. 현장 확인을 요청했습니다
      (field_questions 6차). 행의 Y1/Y2 표기가 어느 파일을 가리키는지도 함께 확인이 필요해, 그래프에는 Y1/Y2를 쓰지 않고 시각으로만 표시했습니다.</li>
    <li>계산 코드: <span class="mono">src/visualization/swing_data.py</span> ·
      생성: <span class="mono">scripts/make_grade_swing.py --month {month}</span></li>
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
    dst = P.OUTPUTS_DIR / f"grade_swing_{month}.html"
    dst.write_text(doc, encoding="utf-8")
    # 메뉴·통합본은 고정 이름을 가리킨다 — 기본(최신 월) 실행일 때만 덮어쓴다
    if a.month is None:
        (P.OUTPUTS_DIR / "grade_swing.html").write_text(doc, encoding="utf-8")
    print(f"[OK] 품위 번갈음 비교: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")
    return dst


if __name__ == "__main__":
    main(sys.argv[1:])
