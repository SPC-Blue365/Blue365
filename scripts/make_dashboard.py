"""품질·재고 운영 대시보드 [Synthesis-Agent].

사용자 요청: "품질관리 및 재고 파악에 쉽게 쓸 수 있는 **반응형 대시보드**".

`plan`(계획)·`prescription`(처방)·`brief`(현황)이 **읽는 문서**라면, 이것은 **매일 여는 화면**이다.
그래서 설계가 다르다.

  · 문서는 결론을 먼저 말하지만, 대시보드는 **지금 상태**를 먼저 보여준다.
  · 문서는 고정이지만, 대시보드는 **기간·라인을 바꿔 가며** 본다.
  · 그래서 집계값을 JSON 으로 싣고 **브라우저에서 다시 그린다.**

⭐️ 무겁게 만들지 않는다 — 지난 통합 리포트는 Plotly 번들 때문에 5MB 가 되어 탭이 먹통이었다.
   여기서는 외부 차트 라이브러리를 쓰지 않고 **집계값 + 직접 그린 SVG** 로 끝낸다(수백 KB).

실행: python scripts/make_dashboard.py  →  outputs/dashboard.html
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths as P                                   # noqa: E402
from config import schema as S                                  # noqa: E402
from src.matching import pipeline as MP                         # noqa: E402
from src.matching.inventory import zone_inventory               # noqa: E402
from src.models.dataset import RAW_DIR, load_osp_stock, load_sources  # noqa: E402
from src.visualization import dashboard_data as D               # noqa: E402
from src.visualization.webstyle import STYLE                    # noqa: E402

E = html.escape
TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol


def build() -> str:
    mine, osp, yards = load_sources(verbose=False)
    stock = load_osp_stock()
    invs = {ln: zone_inventory(mine, osp, stock, ln) for ln in S.YARD_PAIR}

    # ⭐️ 경로별 이송 시간 — 하드코딩하지 않고 매 실행마다 데이터에서 추정한다(§2-4)
    route_lags = {}
    for ln in S.YARD_PAIR:
        rl = MP.estimate_route_lags(osp, yards[ln], ln)
        for src, lag in rl.lags.items():
            route_lags[f"{src}→{ln}"] = int(lag)
    route_txt = " · ".join(f"{k} 약 {v}시간" for k, v in
                           sorted(route_lags.items(), key=lambda kv: -kv[1]))

    # 교차인출은 원본 시트의 `공정구분` 을 봐야 하므로 원본을 다시 읽는다
    xls = pd.ExcelFile(RAW_DIR / S.DATA_FILE)
    raw = {S.LINE_OLD: pd.read_excel(xls, S.SHEET_OSP_OLD),
           S.LINE_NEW: pd.read_excel(xls, S.SHEET_OSP_NEW)}

    payload = dict(
        target=TARGET, tol=TOL, capacity=S.OSP_CAPACITY_TON,
        lines=list(S.YARD_PAIR), alias={k: v[1] for k, v in S.YARD_PAIR.items()},
        built=datetime.now().strftime("%Y-%m-%d %H:%M"),
        head=D.headline(yards, stock),
        yard=D.yard_daily(yards),
        hist=D.yard_hist(yards),
        stock=D.stock_daily(stock),
        flow=D.flow_daily(mine, osp),
        zones=D.zone_stock(invs),
        cross=D.cross_flow(raw),
        recent=D.recent_records(osp, mine),
    )
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    return f"""<title>석회석 품질·재고 대시보드</title>
<style>{STYLE}
.wrap {{ max-width:1320px; padding:20px 18px 56px; gap:20px; }}
.bar {{ position:sticky; top:0; z-index:20; background:var(--surface);
        border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow);
        padding:11px 14px; display:flex; flex-wrap:wrap; align-items:center; gap:8px; }}
.bar .grp {{ display:inline-flex; gap:4px; }}
.chip {{ appearance:none; border:1px solid var(--line-2); background:var(--surface);
         border-radius:999px; padding:5px 13px; font-size:12.5px; cursor:pointer;
         color:var(--ink-2); font-family:inherit; }}
.chip[aria-pressed="true"] {{ background:var(--accent-soft); border-color:var(--accent-2);
                              color:var(--accent-ink); font-weight:600; }}
.bar .sp {{ margin-left:auto; font-size:11.5px; color:var(--ink-3); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:16px; }}
.grid.wide {{ grid-template-columns:1fr; }}
.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
          box-shadow:var(--shadow); padding:15px 17px 17px; min-width:0;
          display:flex; flex-direction:column; gap:9px; }}
.panel > h3 {{ margin:0; font-size:13px; font-weight:600; letter-spacing:-.01em;
               display:flex; align-items:center; gap:9px; flex-wrap:wrap; }}
.panel .hint {{ font-size:11.5px; color:var(--ink-3); margin:0; line-height:1.55; }}
.tag {{ font-size:10.5px; font-weight:600; padding:2px 9px; border-radius:999px;
        border:1px solid currentColor; white-space:nowrap; }}
.tag.good {{ color:var(--good); }} .tag.warn {{ color:var(--warn); }}
.tag.bad {{ color:var(--bad); }} .tag.mute {{ color:var(--ink-3); }}
.statrow {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr)); gap:10px; }}
.stat .v {{ font-family:'IBM Plex Mono',monospace; font-variant-numeric:tabular-nums;
            font-size:19px; font-weight:600; letter-spacing:-.02em; }}
.stat .v small {{ font-size:11.5px; font-weight:400; color:var(--ink-2);
                  font-family:'IBM Plex Sans KR',sans-serif; margin-left:1px; }}
.stat .l {{ font-size:10px; letter-spacing:.07em; text-transform:uppercase;
            color:var(--ink-3); font-weight:600; margin-top:2px; }}
.v.good {{ color:var(--good); }} .v.bad {{ color:var(--bad); }} .v.warn {{ color:var(--warn); }}
.gauge {{ height:9px; border-radius:99px; background:var(--surface-3); overflow:hidden; }}
.gauge i {{ display:block; height:100%; background:var(--accent); }}
.tbl {{ overflow:auto; max-height:380px; border:1px solid var(--line); border-radius:8px; }}
.tbl table {{ margin:0; border:0; border-radius:0; }}
.tbl th {{ position:sticky; top:0; z-index:1; }}
.zbar {{ display:flex; align-items:center; gap:8px; font-size:12px; }}
.zbar .zn {{ font-family:'IBM Plex Mono',monospace; width:34px; text-align:right;
             color:var(--ink-2); font-weight:600; }}
.zbar .zt {{ flex:1; height:16px; background:var(--surface-3); border-radius:4px; overflow:hidden; }}
.zbar .zt i {{ display:block; height:100%; }}
.zbar .zv {{ font-family:'IBM Plex Mono',monospace; font-variant-numeric:tabular-nums;
             width:96px; text-align:right; color:var(--ink-2); font-size:11.5px; }}
.empty {{ color:var(--ink-3); font-size:12.5px; padding:14px 0; text-align:center; }}
@media (max-width:640px) {{
  .wrap {{ padding:14px 12px 40px; gap:14px; }}
  .bar {{ padding:9px 10px; }} .chip {{ padding:5px 10px; font-size:12px; }}
  .grid {{ grid-template-columns:1fr; gap:12px; }}
}}
</style>

<div class="wrap">

<div class="top" style="border:0;padding-bottom:0">
  <div class="eyebrow">석회석 광산 → OSP → 야드 · 운영 대시보드</div>
  <h1>품질 · 재고 현황</h1>
</div>

<div class="bar" role="toolbar" aria-label="기간과 라인 선택">
  <span style="font-size:11.5px;color:var(--ink-3);font-weight:600">기간</span>
  <span class="grp" id="win">
    <button class="chip" data-w="7">7일</button>
    <button class="chip" data-w="30" aria-pressed="true">30일</button>
    <button class="chip" data-w="90">90일</button>
    <button class="chip" data-w="0">전체</button>
  </span>
  <span style="font-size:11.5px;color:var(--ink-3);font-weight:600;margin-left:8px">라인</span>
  <span class="grp" id="lin"></span>
  <span class="sp" id="built"></span>
</div>

<div id="cards" class="grid"></div>

<div class="grid wide">
  <div class="panel">
    <h3>야드 품위 추이 <span class="tag mute">일별 평균 · 음영 = 규격</span></h3>
    <div id="c-trend"></div>
    <p class="hint">굵은 선이 하루 평균, 옅은 띠가 그날의 최저~최고입니다.
      띠가 음영을 크게 벗어난 날은 하루 안에서도 품위가 많이 흔들린 날입니다.</p>
  </div>
</div>

<div class="grid">
  <div class="panel">
    <h3>OSP 재고 추이 <span class="tag mute">실사 기준</span></h3>
    <div id="c-stock"></div>
    <p class="hint">점선은 만실 용량입니다. 재고가 낮아지면 배합 선택지가 줄어듭니다.</p>
  </div>
  <div class="panel">
    <h3>적재 · 인출 <span class="tag mute">일별 톤</span></h3>
    <div id="c-flow"></div>
    <p class="hint">위쪽이 광산에서 들어온 양, 아래쪽이 야드로 나간 양입니다.</p>
  </div>
</div>

<div class="grid">
  <div class="panel">
    <h3>품위 분포 <span class="tag mute">전체 기간</span></h3>
    <div id="c-hist"></div>
    <p class="hint">규격 폭 안에 얼마나 모여 있는지 봅니다. 봉우리가 좁고 음영 안에 있을수록 좋습니다.</p>
  </div>
  <div class="panel">
    <h3>구역별 재고 <span class="tag mute">추정</span></h3>
    <div id="c-zone"></div>
    <p class="hint" id="zone-note"></p>
  </div>
</div>

<div class="grid wide">
  <div class="panel">
    <h3>교차인출 — 기존 OSP 에서 뽑아 신설로 보낸 물량 <span class="tag">반영됨</span></h3>
    <p class="hint">재고는 <b>기존</b> 적치장에서 빠지고, 품위는 <b>신설</b> 야드로 갑니다 —
      두 가지를 따로 귀속시켜 계산합니다. 데이터로 추정한 경로별 이송 시간:
      <b>{E(route_txt)}</b>.</p>
    <div id="c-cross"></div>
    <p class="hint" id="cross-note"></p>
  </div>
</div>

<div class="grid wide">
  <div class="panel">
    <h3>최근 기록 <span class="tag mute" id="rec-n"></span></h3>
    <input id="q" class="chip" style="border-radius:8px;width:100%;max-width:280px;padding:7px 12px"
           placeholder="검색 — 구역 번호·라인·비고" aria-label="기록 검색">
    <div class="tbl"><table class="t"><thead><tr>
      <th>시각</th><th>구분</th><th>라인</th><th class="n">구역</th>
      <th class="n">톤</th><th class="n">CaO</th><th>비고</th>
    </tr></thead><tbody id="rec"></tbody></table></div>
  </div>
</div>

<footer>
  재고는 OSP 실사 기록, 품위는 실시간 분석기 실측, 물량은 광산 이송량과 OSP 인출량입니다.
  구역별 재고는 <b>측정값이 아니라 적재−인출 흐름에서 복원한 추정치</b>입니다.
  재현 <code>python scripts/make_dashboard.py</code>.
</footer>
</div>

<script id="payload" type="application/json">{js}</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
const SVGNS = 'http://www.w3.org/2000/svg';
let WIN = 30, LINE = 'all';

const fmt = (v, d = 0) => v == null ? '—'
  : v.toLocaleString('ko-KR', {{minimumFractionDigits: d, maximumFractionDigits: d}});
const el = (t, a = {{}}, kids = []) => {{
  const n = document.createElementNS(SVGNS, t);
  for (const k in a) n.setAttribute(k, a[k]);
  kids.forEach(c => n.appendChild(c));
  return n;
}};
const txt = (s, a) => {{ const n = el('text', a); n.textContent = s; return n; }};

function cut(rows) {{                       // 기간 필터 — 마지막 날짜 기준 상대 창
  if (!WIN || !rows.length) return rows;
  const last = new Date(rows[rows.length - 1].d);
  const from = new Date(last); from.setDate(from.getDate() - WIN);
  return rows.filter(r => new Date(r.d) >= from);
}}
const lines = () => LINE === 'all' ? DATA.lines : [LINE];
const COL = {{}}; DATA.lines.forEach((l, i) => COL[l] = i ? 'var(--accent)' : 'var(--bar)');

function svg(host, w, h) {{
  host.innerHTML = '';
  const s = el('svg', {{viewBox: `0 0 ${{w}} ${{h}}`, class: 'chart',
                        preserveAspectRatio: 'xMidYMid meet'}});
  host.appendChild(s); return s;
}}
function xmap(rows, pl, pr) {{
  if (!rows.length) return () => pl;
  const t0 = new Date(rows[0].d).getTime(), t1 = new Date(rows[rows.length - 1].d).getTime();
  const sp = Math.max(t1 - t0, 1);
  return d => pl + (new Date(d).getTime() - t0) / sp * (pr - pl);
}}
function ymap(lo, hi, pb, pt) {{ return v => pb - (v - lo) / Math.max(hi - lo, 1e-9) * (pb - pt); }}

function dateTicks(s, rows, X, pb) {{
  let last = '';
  rows.forEach(r => {{
    const m = r.d.slice(0, 7);
    if (m !== last) {{
      last = m;
      s.appendChild(txt(r.d.slice(5, 7) + '월',
        {{x: X(r.d), y: pb + 15, 'text-anchor': 'middle', class: 'ax'}}));
    }}
  }});
}}

/* ── 야드 품위 추이 ───────────────────────────────── */
function drawTrend() {{
  const host = document.getElementById('c-trend');
  const series = lines().map(l => [l, cut(DATA.yard[l] || [])]).filter(([, r]) => r.length);
  if (!series.length) {{ host.innerHTML = '<p class="empty">표시할 자료가 없습니다.</p>'; return; }}
  const W = 1200, H = 300, pl = 44, pr = W - 14, pt = 14, pb = H - 26;
  const s = svg(host, W, H);
  const all = series.flatMap(([, r]) => r);
  const lo = Math.min(DATA.target - DATA.tol - 1, ...all.map(r => r.lo ?? r.cao)) - .3;
  const hi = Math.max(DATA.target + DATA.tol + 1, ...all.map(r => r.hi ?? r.cao)) + .3;
  const Y = ymap(lo, hi, pb, pt), X = xmap(all.slice().sort((a, b) => a.d < b.d ? -1 : 1), pl, pr);
  s.appendChild(el('rect', {{x: pl, y: Y(DATA.target + DATA.tol), width: pr - pl,
    height: Math.abs(Y(DATA.target - DATA.tol) - Y(DATA.target + DATA.tol)),
    fill: 'var(--band)'}}));
  for (let v = Math.ceil(lo); v <= hi; v += 2) {{
    s.appendChild(el('line', {{x1: pl, y1: Y(v), x2: pr, y2: Y(v), stroke: 'var(--grid)'}}));
    s.appendChild(txt(v, {{x: pl - 7, y: Y(v) + 4, 'text-anchor': 'end', class: 'ax'}}));
  }}
  series.forEach(([l, rows]) => {{
    const band = rows.filter(r => r.lo != null && r.hi != null);
    if (band.length > 1) {{
      const up = band.map(r => `${{X(r.d).toFixed(1)}},${{Y(r.hi).toFixed(1)}}`);
      const dn = band.slice().reverse().map(r => `${{X(r.d).toFixed(1)}},${{Y(r.lo).toFixed(1)}}`);
      s.appendChild(el('polygon', {{points: up.concat(dn).join(' '), fill: COL[l], opacity: .16}}));
    }}
    const pts = rows.filter(r => r.cao != null)
      .map(r => `${{X(r.d).toFixed(1)}},${{Y(r.cao).toFixed(1)}}`).join(' ');
    s.appendChild(el('polyline', {{points: pts, fill: 'none', stroke: COL[l],
      'stroke-width': 1.8, 'stroke-linejoin': 'round'}}));
  }});
  dateTicks(s, series[0][1], X, pb);
  let lx = pl + 4;
  series.forEach(([l]) => {{
    s.appendChild(el('rect', {{x: lx, y: pt - 4, width: 16, height: 3, fill: COL[l]}}));
    s.appendChild(txt(l, {{x: lx + 21, y: pt + 1, class: 'cs'}}));
    lx += 82;
  }});
  s.appendChild(txt(`음영 = 목표 ${{DATA.target}}±${{DATA.tol}}`,
    {{x: pr, y: pt + 1, 'text-anchor': 'end', class: 'cs'}}));
}}

/* ── 재고 추이 ────────────────────────────────────── */
function drawStock() {{
  const host = document.getElementById('c-stock');
  const series = lines().map(l => [l, cut(DATA.stock[l] || [])]).filter(([, r]) => r.length);
  if (!series.length) {{ host.innerHTML = '<p class="empty">표시할 자료가 없습니다.</p>'; return; }}
  const W = 620, H = 210, pl = 50, pr = W - 12, pt = 12, pb = H - 24;
  const s = svg(host, W, H);
  const hi = DATA.capacity * 1.06;
  const Y = ymap(0, hi, pb, pt);
  const all = series.flatMap(([, r]) => r).sort((a, b) => a.d < b.d ? -1 : 1);
  const X = xmap(all, pl, pr);
  s.appendChild(el('line', {{x1: pl, y1: Y(DATA.capacity), x2: pr, y2: Y(DATA.capacity),
    stroke: 'var(--bad)', 'stroke-dasharray': '5 4', 'stroke-width': 1.2}}));
  s.appendChild(txt('만실 ' + fmt(DATA.capacity), {{x: pr, y: Y(DATA.capacity) - 5,
    'text-anchor': 'end', class: 'cs'}}));
  [0, 20000, 40000].forEach(v => {{
    s.appendChild(el('line', {{x1: pl, y1: Y(v), x2: pr, y2: Y(v), stroke: 'var(--grid)'}}));
    s.appendChild(txt(v ? (v / 1000) + 'k' : '0',
      {{x: pl - 7, y: Y(v) + 4, 'text-anchor': 'end', class: 'ax'}}));
  }});
  series.forEach(([l, rows]) => {{
    const pts = rows.filter(r => r.t != null)
      .map(r => `${{X(r.d).toFixed(1)}},${{Y(r.t).toFixed(1)}}`).join(' ');
    s.appendChild(el('polyline', {{points: pts, fill: 'none', stroke: COL[l], 'stroke-width': 1.8}}));
  }});
  dateTicks(s, series[0][1], X, pb);
}}

/* ── 적재·인출 ────────────────────────────────────── */
function drawFlow() {{
  const host = document.getElementById('c-flow');
  const rowsByLine = lines().map(l => [l, cut(DATA.flow[l] || [])]).filter(([, r]) => r.length);
  if (!rowsByLine.length) {{ host.innerHTML = '<p class="empty">표시할 자료가 없습니다.</p>'; return; }}
  const days = [...new Set(rowsByLine.flatMap(([, r]) => r.map(x => x.d)))].sort();
  const agg = days.map(d => {{
    let i = 0, o = 0;
    rowsByLine.forEach(([, r]) => {{ const h = r.find(x => x.d === d); if (h) {{ i += h.i || 0; o += h.o || 0; }} }});
    return {{d, i, o}};
  }});
  const W = 620, H = 210, pl = 50, pr = W - 12, mid = H / 2 - 2, pt = 12, pb = H - 24;
  const s = svg(host, W, H);
  const mx = Math.max(1, ...agg.map(r => Math.max(r.i, r.o)));
  const bw = Math.max(1.5, (pr - pl) / Math.max(agg.length, 1) * .66);
  const X = xmap(agg, pl + bw, pr - bw);
  agg.forEach(r => {{
    const x = X(r.d) - bw / 2;
    const hi = (r.i / mx) * (mid - pt), ho = (r.o / mx) * (pb - mid);
    if (r.i) s.appendChild(el('rect', {{x: x.toFixed(1), y: (mid - hi).toFixed(1),
      width: bw.toFixed(1), height: hi.toFixed(1), fill: 'var(--accent)'}}));
    if (r.o) s.appendChild(el('rect', {{x: x.toFixed(1), y: mid.toFixed(1),
      width: bw.toFixed(1), height: ho.toFixed(1), fill: 'var(--bar)'}}));
  }});
  s.appendChild(el('line', {{x1: pl, y1: mid, x2: pr, y2: mid, stroke: 'var(--ink-3)'}}));
  s.appendChild(txt('적재', {{x: pl - 7, y: pt + 10, 'text-anchor': 'end', class: 'ax'}}));
  s.appendChild(txt('인출', {{x: pl - 7, y: pb - 2, 'text-anchor': 'end', class: 'ax'}}));
  dateTicks(s, agg, X, pb);
}}

/* ── 분포 ─────────────────────────────────────────── */
function drawHist() {{
  const host = document.getElementById('c-hist');
  const ed = DATA.hist.edges;
  const ls = lines().filter(l => DATA.hist.lines[l]);
  if (!ls.length) {{ host.innerHTML = '<p class="empty">표시할 자료가 없습니다.</p>'; return; }}
  const W = 620, H = 210, pl = 36, pr = W - 12, pt = 14, pb = H - 24;
  const s = svg(host, W, H);
  const mx = Math.max(...ls.flatMap(l => DATA.hist.lines[l])) * 1.12;
  const xs = v => pl + (v - ed[0]) / (ed[ed.length - 1] - ed[0]) * (pr - pl);
  const Y = ymap(0, mx, pb, pt);
  s.appendChild(el('rect', {{x: xs(DATA.target - DATA.tol), y: pt,
    width: xs(DATA.target + DATA.tol) - xs(DATA.target - DATA.tol), height: pb - pt,
    fill: 'var(--band)'}}));
  ls.forEach(l => {{
    const v = DATA.hist.lines[l];
    const pts = v.map((p, i) => `${{xs((ed[i] + ed[i + 1]) / 2).toFixed(1)}},${{Y(p).toFixed(1)}}`);
    s.appendChild(el('polyline', {{points: pts.join(' '), fill: 'none', stroke: COL[l],
      'stroke-width': 1.7, 'stroke-linejoin': 'round'}}));
  }});
  [40, 43, 46, 49].forEach(v => s.appendChild(
    txt(v, {{x: xs(v), y: pb + 15, 'text-anchor': 'middle', class: 'ax'}})));
  s.appendChild(el('line', {{x1: pl, y1: pb, x2: pr, y2: pb, stroke: 'var(--line)'}}));
  s.appendChild(txt('가로축 CaO(%) · 세로축 비율', {{x: pr, y: pt + 2,
    'text-anchor': 'end', class: 'cs'}}));
}}

/* ── 구역별 재고 ──────────────────────────────────── */
function drawZones() {{
  const host = document.getElementById('c-zone');
  const note = document.getElementById('zone-note');
  const ls = lines().filter(l => DATA.zones[l]);
  if (!ls.length) {{ host.innerHTML = '<p class="empty">표시할 자료가 없습니다.</p>'; note.textContent = ''; return; }}
  let h = '';
  ls.forEach(l => {{
    const z = DATA.zones[l];
    const mx = Math.max(1, ...z.zones.map(x => x.t || 0));
    h += `<div style="font-size:11.5px;color:var(--ink-3);font-weight:600;margin:6px 0 4px">
            ${{l}} · 합계 ${{fmt(z.total)}}톤 <span style="font-weight:400">(${{z.at}} 기준)</span></div>`;
    if (!z.zones.length) h += '<p class="empty">재고 추정이 없습니다.</p>';
    z.zones.forEach(x => {{
      const inSpec = x.cao != null && Math.abs(x.cao - DATA.target) <= DATA.tol;
      const c = x.cao == null ? 'var(--ink-3)' : (inSpec ? 'var(--good)' : 'var(--accent)');
      h += `<div class="zbar"><span class="zn">${{x.z}}</span>
        <span class="zt"><i style="width:${{(x.t / mx * 100).toFixed(1)}}%;background:${{c}}"></i></span>
        <span class="zv">${{fmt(x.t)}}t · ${{x.cao == null ? '—' : x.cao.toFixed(1) + '%'}}</span></div>`;
    }});
  }});
  host.innerHTML = h;
  note.innerHTML = '막대 길이는 추정 재고량, 색은 품위입니다 — '
    + '<b style="color:var(--good)">초록</b>이 규격 안, 파랑이 규격 밖입니다. '
    + '구역별 재고는 측정값이 아니라 흐름에서 복원한 추정치입니다.';
}}

/* ── 교차인출 ─────────────────────────────────────── */
function drawCross() {{
  const host = document.getElementById('c-cross');
  const note = document.getElementById('cross-note');
  const ks = Object.keys(DATA.cross).filter(l => (DATA.cross[l].cross || 0) > 0);
  if (!ks.length) {{ host.innerHTML = '<p class="empty">교차인출 기록이 없습니다.</p>'; note.textContent = ''; return; }}
  const l = ks[0], c = DATA.cross[l], rows = cut(c.daily);
  const W = 1200, H = 190, pl = 50, pr = W - 14, pt = 14, pb = H - 26;
  const s = svg(host, W, H);
  const mx = Math.max(1, ...rows.map(r => r.t || 0));
  const Y = ymap(0, mx * 1.1, pb, pt);
  const bw = Math.max(1.5, (pr - pl) / Math.max(rows.length, 1) * .66);
  const X = xmap(rows, pl + bw, pr - bw);
  rows.forEach(r => {{
    const x = X(r.d) - bw / 2;
    if (r.t) s.appendChild(el('rect', {{x: x.toFixed(1), y: Y(r.t).toFixed(1),
      width: bw.toFixed(1), height: (pb - Y(r.t)).toFixed(1), fill: 'var(--bar)'}}));
    if (r.c) s.appendChild(el('rect', {{x: x.toFixed(1), y: Y(r.c).toFixed(1),
      width: bw.toFixed(1), height: (pb - Y(r.c)).toFixed(1), fill: 'var(--warn)'}}));
  }});
  [0, mx / 2, mx].forEach(v => {{
    s.appendChild(el('line', {{x1: pl, y1: Y(v), x2: pr, y2: Y(v), stroke: 'var(--grid)'}}));
    s.appendChild(txt(fmt(v), {{x: pl - 7, y: Y(v) + 4, 'text-anchor': 'end', class: 'ax'}}));
  }});
  dateTicks(s, rows, X, pb);
  s.appendChild(txt('회색 = 그날 전체 인출 · 주황 = 교차인출분',
    {{x: pr, y: pt + 2, 'text-anchor': 'end', class: 'cs'}}));
  note.innerHTML = `<b>${{l}} OSP 인출 ${{fmt(c.total)}}톤 중 ${{fmt(c.cross)}}톤`
    + `(${{c.pct.toFixed(0)}}%, ${{c.n_rows}}건)</b>이 원본 기록의 공정구분에 `
    + `<b>${{c.dest}}</b>으로 적혀 있습니다. 재고는 <b>${{l}} OSP</b>에서 빠지지만 `
    + `물량은 <b>${{c.dest}} 라인</b>으로 갑니다. `
    + `<b style="color:var(--warn)">품위를 어느 야드에 붙일지 확인이 필요합니다.</b>`;
}}

/* ── 상단 카드 ────────────────────────────────────── */
function drawCards() {{
  const host = document.getElementById('cards');
  host.innerHTML = lines().map(l => {{
    const h = DATA.head[l] || {{}};
    const dev = h.w_mean == null ? null : h.w_mean - DATA.target;
    const okTone = h.w_ok == null ? 'mute' : (h.w_ok >= 60 ? 'good' : h.w_ok >= 30 ? 'warn' : 'bad');
    const stale = h.age_h != null && h.age_h > 48;
    return `<div class="panel">
      <h3>${{l}} 라인 <span style="font-weight:400;color:var(--ink-3)">${{DATA.alias[l] || ''}}</span>
        <span class="tag ${{okTone}}">최근 7일 규격내 ${{h.w_ok == null ? '—' : h.w_ok.toFixed(0) + '%'}}</span>
        ${{stale ? '<span class="tag mute">자료 지연</span>' : ''}}</h3>
      <div class="statrow">
        <div class="stat"><div class="v ${{dev == null ? '' : (Math.abs(dev) <= DATA.tol ? 'good' : 'bad')}}">
          ${{h.last_cao == null ? '—' : h.last_cao.toFixed(2)}}<small>%</small></div>
          <div class="l">최신 CaO</div></div>
        <div class="stat"><div class="v">${{h.w_mean == null ? '—' : h.w_mean.toFixed(2)}}<small>%</small></div>
          <div class="l">7일 평균</div></div>
        <div class="stat"><div class="v ${{h.w_std == null ? '' : (h.w_std <= DATA.tol ? 'good' : 'bad')}}">
          ${{h.w_std == null ? '—' : h.w_std.toFixed(2)}}<small>%p</small></div>
          <div class="l">7일 편차</div></div>
        <div class="stat"><div class="v">${{fmt(h.stock)}}<small>t</small></div>
          <div class="l">OSP 재고</div></div>
      </div>
      <div class="gauge"><i style="width:${{Math.min(h.stock_pct || 0, 100).toFixed(1)}}%"></i></div>
      <p class="hint">재고 ${{h.stock_pct == null ? '—' : h.stock_pct.toFixed(0) + '%'}}
        (만실 ${{fmt(DATA.capacity)}}톤 대비) ·
        7일 변화 ${{h.stock_chg == null ? '—' : (h.stock_chg > 0 ? '+' : '') + fmt(h.stock_chg) + '톤'}} ·
        최신 측정 ${{h.last_at || '—'}}</p>
    </div>`;
  }}).join('');
}}

/* ── 최근 기록 ────────────────────────────────────── */
function drawRecent() {{
  const q = (document.getElementById('q').value || '').trim().toLowerCase();
  const rows = DATA.recent.filter(r => {{
    if (LINE !== 'all' && r.line !== LINE) return false;
    if (!q) return true;
    return [r.t, r.kind, r.line, r.zone, r.note].join(' ').toLowerCase().includes(q);
  }});
  document.getElementById('rec-n').textContent = rows.length + '건';
  document.getElementById('rec').innerHTML = rows.slice(0, 200).map(r => `<tr>
    <td>${{r.t}}</td><td>${{r.kind}}</td><td>${{r.line}}</td>
    <td class="n">${{r.zone ?? '—'}}</td><td class="n">${{fmt(r.ton)}}</td>
    <td class="n">${{r.cao == null ? '—' : r.cao.toFixed(2)}}</td>
    <td style="color:var(--ink-3)">${{r.note || ''}}</td></tr>`).join('')
    || '<tr><td colspan="7" class="empty">해당 기록이 없습니다.</td></tr>';
}}

function render() {{
  drawCards(); drawTrend(); drawStock(); drawFlow();
  drawHist(); drawZones(); drawCross(); drawRecent();
}}

/* ── 조작 ─────────────────────────────────────────── */
document.getElementById('built').textContent = '기준 ' + DATA.built;
document.getElementById('lin').innerHTML =
  `<button class="chip" data-l="all" aria-pressed="true">전체</button>`
  + DATA.lines.map(l => `<button class="chip" data-l="${{l}}">${{l}}</button>`).join('');
document.querySelectorAll('#win .chip').forEach(b => b.onclick = () => {{
  WIN = +b.dataset.w;
  document.querySelectorAll('#win .chip').forEach(x =>
    x.setAttribute('aria-pressed', x === b));
  render();
}});
document.querySelectorAll('#lin .chip').forEach(b => b.onclick = () => {{
  LINE = b.dataset.l;
  document.querySelectorAll('#lin .chip').forEach(x =>
    x.setAttribute('aria-pressed', x === b));
  render();
}});
document.getElementById('q').oninput = drawRecent;
render();
</script>
"""


def main():
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = P.OUTPUTS_DIR / "dashboard.html"
    doc = build()
    dst.write_text(doc, encoding="utf-8")
    print(f"[OK] 품질·재고 대시보드: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
