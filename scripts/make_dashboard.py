"""품질·재고 운영 현황판 [Synthesis-Agent].

사용자 요청: "품질관리 및 재고 파악에 쉽게 쓸 수 있는 **반응형 대시보드**".
2026-11-09 추가 요청: **시멘트 품질관리 시스템(Blue365 QMS) 디자인 스타일로 다시 정리.**

`plan`(계획)·`prescription`(처방)·`brief`(현황)이 **읽는 문서**라면, 이것은 **매일 여는 화면**이다.

  · 문서는 결론을 먼저 말하지만, 현황판은 **지금 상태**를 먼저 보여준다.
  · 문서는 고정이지만, 현황판은 **기간·라인을 바꿔 가며** 본다.
  · 그래서 집계값을 JSON 으로 싣고 **브라우저에서 다시 그린다.**

⭐️ 구조도 QMS 를 따른다 — 한 장을 끝없이 스크롤하지 않고, **왼쪽 세로 메뉴로 화면을
   갈아 끼운다**(종합 현황 / 품위 추이 / 재고 / 교차인출 / 최근 기록).
   휴대폰에서는 같은 메뉴가 하단 탭바가 된다.

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths as P                                   # noqa: E402
from config import schema as S                                  # noqa: E402
from src.matching import pipeline as MP                         # noqa: E402
from src.matching.chain import build_chain                      # noqa: E402
from src.matching.inventory import zone_inventory               # noqa: E402
from src.models.dataset import (load_osp_stock, load_sources,    # noqa: E402
                                load_yard_change)
from src.visualization import dashboard_data as D               # noqa: E402
from src.visualization.qmsstyle import LOGO, STYLE, icon, views_js  # noqa: E402

E = html.escape
TARGET, TOL = S.TARGET.cao_mean, S.TARGET.tol


def _payload() -> dict:
    mine, osp, yards = load_sources(verbose=False)
    stock = load_osp_stock()
    invs = {ln: zone_inventory(mine, osp, stock, ln) for ln in S.YARD_PAIR}

    # ⭐️ 추적 연결 점수판 — 이 프로젝트의 성공 기준이다(§6-0-28). 첫 화면 맨 위에 둔다.
    chain = build_chain(mine, osp, stock, load_yard_change())

    # ⭐️ 경로별 이송 시간 — 하드코딩하지 않고 매 실행마다 데이터에서 추정한다(§2-4)
    route_lags = {}
    for ln in S.YARD_PAIR:
        rl = MP.estimate_route_lags(osp, yards[ln], ln)
        for src, lag in rl.lags.items():
            route_lags[f"{src}→{ln}"] = int(lag)
    route_txt = " · ".join(f"{k} 약 {v}시간" for k, v in
                           sorted(route_lags.items(), key=lambda kv: -kv[1]))

    return dict(
        target=TARGET, tol=TOL, capacity=S.OSP_CAPACITY_TON,
        lines=list(S.YARD_PAIR), alias={k: v[1] for k, v in S.YARD_PAIR.items()},
        built=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ref=datetime.now().strftime("%Y-%m-%d"),
        route_txt=route_txt,
        chain=dict(
            linked_pct=(None if chain.linked_pct != chain.linked_pct else round(chain.linked_pct, 1)),
            linked_ton=chain.linked_ton, total_ton=chain.total_ton,
            sentence=chain.sentence(),
            weakest=(chain.weakest.key if chain.weakest else None),
            joints=[dict(key=j.key, name=j.name, label=j.label, why=j.why,
                         gap=j.gap, tone=j.tone,
                         score=(None if j.score != j.score else round(j.score, 1)))
                    for j in chain.joints]),
        head=D.headline(yards, stock),
        yard=D.yard_daily(yards),
        hist=D.yard_hist(yards),
        stock=D.stock_daily(stock),
        flow=D.flow_daily(mine, osp),
        zones=D.zone_stock(invs),
        cross=D.cross_flow(osp),
        recent=D.recent_records(osp, mine),
    )


def _sidebar() -> str:
    """왼쪽 세로 메뉴 — 레퍼런스(QMS)의 틀 그대로. 항목 자체는 JS 가 채운다."""
    return f"""<aside class="side" aria-label="메뉴">
  <div class="brand"><span class="logo">{LOGO}</span><span class="txt">Blue365 <small>석회석</small></span>
    <button class="collapse" id="collapse" aria-label="메뉴 접기" title="메뉴 접기"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></svg></button></div>
  <div class="ws" title="품위·재고 현황판 · 조회 전용"><span class="av">품</span><div><b>품위 현황판</b><small>보는용 · 조회 전용</small></div></div>
  <nav id="tabs" aria-label="화면"></nav>
  <div class="spacer"></div>
  <div class="upd"><b><i></i>파이프라인 실행 때 갱신</b><span id="genAt"></span><br>
    재현 <code>python scripts/run_all.py</code></div>
</aside>"""


def build() -> str:
    payload = _payload()
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    return f"""<!doctype html>
<html lang="ko" translate="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="google" content="notranslate">
<title>석회석 품위·재고 현황판</title>
<style>{STYLE}</style>
</head>
<body>
<div class="shell" id="shell">
{_sidebar()}
<div class="mainc">
<header class="top" id="top">
  <div class="wrap">
    <div class="bar">
      <div class="mbrand"><span class="logo">{LOGO}</span>Blue365</div>
      <div class="where" id="where"></div>
      <span class="tag">보는용</span>
      <span class="grow"></span>
      <span class="refchip" id="refchip"></span>
      <button class="iconbtn" id="share" aria-label="공유"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg><span>공유</span></button>
    </div>
  </div>
</header>
<div class="wrap" id="banners"></div>
<main class="wrap" id="view"></main>
<div class="wrap"><footer>
  <div>재고는 OSP 실사 기록, 품위는 실시간 분석기 실측, 물량은 광산 이송량과 OSP 인출량입니다.
    구역별 재고는 <b>측정값이 아니라 적재−인출 흐름에서 복원한 추정치</b>입니다.</div>
  <div>목표 CaO {TARGET}±{TOL}% · 이 화면은 <code>python scripts/make_dashboard.py</code> 로 다시 만듭니다.</div>
</footer></div>
</div>
</div>
<nav class="tabbar" id="tabbar" aria-label="화면"></nav>
<button class="fab" id="fab" aria-label="맨 위로"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 15 6-6 6 6"/></svg></button>
<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script id="payload" type="application/json">{js}</script>
<script id="menu" type="application/json">{views_js()}</script>
<script>
{_SCRIPT}
</script>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════════
# 화면 쪽 코드 — 파이썬 f-string 이 아니라 **보통 문자열**이다. 중괄호를 그대로 쓴다.
# (종전에는 f-string 안에 JS 를 넣어 `{{ }}` 로 일일이 이스케이프했는데, 한 글자만
#  틀려도 조용히 깨졌다. 값은 전부 위 payload 로 내려보내므로 섞을 이유가 없다.)
# ══════════════════════════════════════════════════════════════════════════
_SCRIPT = r"""
(() => {
"use strict";
const DATA = JSON.parse(document.getElementById('payload').textContent);
const MENU = JSON.parse(document.getElementById('menu').textContent);
const $ = (id) => document.getElementById(id);
const SVGNS = 'http://www.w3.org/2000/svg';
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const fmt = (v, d = 0) => v == null || !isFinite(v) ? '—'
  : Number(v).toLocaleString('ko-KR', {minimumFractionDigits: d, maximumFractionDigits: d});
const two = (i) => String(i + 1).padStart(2, '0');
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 저장 불가 환경 */ } },
};

/* ── 상태 ─────────────────────────────────────────────────────────────
   LINE = 보고 있는 라인, FROM~TO = 보고 있는 기간(년-월-일 두 날짜).
   ⚠️ 기간은 '마지막 날 기준 N일' 같은 상대 창이 아니다. 칩은 두 날짜를 채워 넣는
      지름길일 뿐이고, 지금 보는 구간은 항상 화면에 글자로 적힌다. */
let LINE = 'all', METRIC = 'cao', FROM = '', TO = '', WIN = 30, Q = '';

/* ⚠️ **분석 구간과 보관 구간이 다르다.** OSP 실사 재고 시트는 2024-04 부터 있지만 품위·물량
      기록은 2026-06 부터다. '전체' 를 재고 기준으로 잡으면 품위 그래프가 오른쪽 끝에 몰려
      읽을 수 없게 된다. → 기본 구간은 **야드 측정이 있는 기간**으로, 날짜 입력의 하한만
      재고까지 열어 둔다(과거 재고를 보고 싶으면 직접 입력하면 된다). */
function spanOf(grps) {
  const ds = [];
  grps.forEach(grp => Object.values(grp || {}).forEach(rows =>
    (Array.isArray(rows) ? rows : (rows.daily || [])).forEach(r => r && r.d && ds.push(r.d))));
  ds.sort();
  return ds.length ? [ds[0], ds[ds.length - 1]] : ['', ''];
}
const [DMIN, DMAX] = spanOf([DATA.yard]);                            // 품위·물량이 있는 구간 = 기본
const [SMIN, SMAX] = spanOf([DATA.yard, DATA.flow, DATA.cross, DATA.stock]);  // 보관 구간 전체

function presetFrom(days) {
  if (!days || !DMAX) return DMIN;
  const d = new Date(DMAX); d.setDate(d.getDate() - days);
  const iso = d.toISOString().slice(0, 10);
  return iso < DMIN ? DMIN : iso;
}
FROM = presetFrom(30); TO = DMAX;

function cut(rows) {   // 기간 거르기 — ISO 문자열이라 문자열 비교로 충분하다
  if (!rows || !rows.length) return rows;
  return rows.filter(r => (!FROM || r.d >= FROM) && (!TO || r.d <= TO));
}
const lines = () => LINE === 'all' ? DATA.lines : [LINE];
// 계열색 — 막대 채움색(--bar)은 선으로 쓰면 바탕에 묻힌다. 전용 계열색을 쓴다.
const COL = {}; DATA.lines.forEach((l, i) => COL[l] = i ? 'var(--series-1)' : 'var(--series-2)');

/* ── 레퍼런스(QMS)의 조각들 ────────────────────────────────────────── */
const pill = (cls, t) => `<span class="pill ${cls}">${esc(t)}</span>`;
const head = (tag, h, lead) =>
  `<div><span class="tag">${esc(tag)}</span><h1 class="hl">${h}</h1>` +
  (lead ? `<p class="lead">${lead}</p>` : '') + '</div>';
const card = ({no, title, en, well, i = 0, cls = ''}) =>
  `<div class="card ${cls}" style="--i:${i}"><div class="well">${well}</div>` +
  `<div class="cap"><div class="t">${no ? `<span class="no">${no}</span>` : ''}${title}</div>` +
  (en ? `<small>${en}</small>` : '') + '</div></div>';
const box = (inner, i = 0) => `<div class="card pad" style="--i:${i}">${inner}</div>`;
const seg = (id, opts, cur) => `<div class="seg" id="${id}" role="group">` +
  opts.map(([v, t]) => `<button aria-pressed="${String(v) === String(cur)}" data-v="${esc(v)}">${esc(t)}</button>`).join('') + '</div>';
const empty = (t) => `<div class="empty">${esc(t)}</div>`;
const onPick = (id, fn) => { const el = $(id); if (el) el.addEventListener('click', (e) => {
  const b = e.target.closest('button[data-v]'); if (b) fn(b.dataset.v); }); };
function statusIcon(tone) {
  const c = {good: '--ok', warn: '--warn', bad: '--bad'}[tone] || '--faint';
  const p = tone === 'good' ? '<path d="m7 12.5 3.2 3.2L17 9"/>'
          : tone === 'bad' ? '<path d="m8 8 8 8M16 8l-8 8"/>'
          : '<path d="M12 7v6"/><path d="M12 17h.01"/>';
  return `<svg viewBox="0 0 24 24" width="38" height="38" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="var(${c})"/>` +
    `<g fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${p}</g></svg>`;
}

/* ── 토스트 ───────────────────────────────────────────────────────── */
let toastT;
function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 2000);
}

/* ── 기간·라인 고르는 줄 ──────────────────────────────────────────── */
function ctrl({dates = true} = {}) {
  const winOpts = [[7, '7일'], [30, '30일'], [90, '90일'], [0, '전체']];
  const linOpts = [['all', '전체']].concat(DATA.lines.map(l => [l, l]));
  return box(
    '<div class="ctrl">' +
    (dates ? '<div><span class="lab">기간 (년-월-일)</span><span class="dates">' +
      `<input type="date" id="dFrom" aria-label="시작 날짜" value="${FROM}" min="${SMIN}" max="${SMAX}">` +
      '<span class="tilde">~</span>' +
      `<input type="date" id="dTo" aria-label="종료 날짜" value="${TO}" min="${SMIN}" max="${SMAX}"></span></div>` +
      `<div><span class="lab">빠른 선택</span>${seg('win', winOpts, WIN)}</div>` : '') +
    `<div><span class="lab">라인</span>${seg('lin', linOpts, LINE)}</div>` +
    '</div>' + (dates ? '<p class="hint" id="span-note"></p>' : ''));
}
function wireCtrl() {
  onPick('lin', (v) => { LINE = v; render(CUR); });
  const fIn = $('dFrom'), tIn = $('dTo');
  if (!fIn) return;
  onPick('win', (v) => { WIN = +v; FROM = presetFrom(WIN); TO = DMAX; render(CUR); });
  // 날짜를 직접 고치면 어떤 칩도 눌린 상태가 아니게 둔다 — 지금 보는 구간은 입력칸이 말해 준다
  [fIn, tIn].forEach(i => i.onchange = () => {
    let a = fIn.value || DMIN, z = tIn.value || DMAX;
    if (a > z) { const s = a; a = z; z = s; }      // 거꾸로 넣으면 바로잡는다
    FROM = a; TO = z; WIN = -1; render(CUR);
  });
  // ⚠️ 날짜 입력칸의 표기 형식은 **브라우저 언어**를 따라가 바꿀 수 없다(한국어가 아니면
  //    MM/DD/YYYY 로 보인다). 그래서 지금 보는 구간을 년-월-일로 따로 적어 준다.
  const n = $('span-note');
  if (n) {
    const days = Math.round((new Date(TO) - new Date(FROM)) / 86400000) + 1;
    n.innerHTML = `보는 구간 <b>${esc(FROM)} ~ ${esc(TO)}</b> (${days}일)` +
      (SMIN < DMIN ? ` · 기본 구간은 <b>야드 측정 기간</b> 기준입니다. 재고·인출 기록은 ` +
        `${esc(SMIN)}부터 있어, 직접 입력하면 그 구간도 볼 수 있습니다.` : '');
  }
}

/* ── 직접 그린 SVG 차트 ───────────────────────────────────────────── */
const el = (t, a = {}, kids = []) => {
  const n = document.createElementNS(SVGNS, t);
  for (const k in a) n.setAttribute(k, a[k]);
  kids.forEach(c => n.appendChild(c));
  return n;
};
const txt = (s, a) => { const n = el('text', a); n.textContent = s; return n; };
function svg(host, w, h) {
  host.innerHTML = '';
  const s = el('svg', {viewBox: `0 0 ${w} ${h}`, class: 'chart', preserveAspectRatio: 'xMidYMid meet'});
  host.appendChild(s); return s;
}
function xmap(rows, pl, pr) {
  if (!rows.length) return () => pl;
  const t0 = new Date(rows[0].d).getTime(), t1 = new Date(rows[rows.length - 1].d).getTime();
  const sp = Math.max(t1 - t0, 1);
  return d => pl + (new Date(d).getTime() - t0) / sp * (pr - pl);
}
const ymap = (lo, hi, pb, pt) => v => pb - (v - lo) / Math.max(hi - lo, 1e-9) * (pb - pt);
function dateTicks(s, rows, X, pb) {
  let last = '';
  rows.forEach(r => {
    const m = r.d.slice(0, 7);
    if (m !== last) {
      last = m;
      s.appendChild(txt(r.d.slice(5, 7) + '월', {x: X(r.d), y: pb + 15, 'text-anchor': 'middle', class: 'ax'}));
    }
  });
}

// 추이 패널에서 볼 지표 — 세그먼트로 바꾼다. 규격 음영은 CaO 에만 의미가 있다.
const METRICS = {
  cao: {v: 'cao', lo: 'lo', hi: 'hi', spec: true, step: 2, name: '야드 CaO',
        tag: '일별 평균 · 음영 = 규격',
        hint: '굵은 선이 하루 평균, 옅은 띠가 그날의 최저~최고입니다. 띠가 음영을 크게 ' +
              '벗어난 날은 하루 안에서도 품위가 많이 흔들린 날입니다.'},
  mgo: {v: 'mgo', lo: 'mlo', hi: 'mhi', spec: false, step: 1, name: 'MgO',
        tag: '일별 평균',
        hint: 'MgO 는 CaO 와 같은 광산 기록에서 나오므로, 두 성분이 함께 움직이는지 보면 ' +
              '매칭이 제대로 되었는지 교차 확인할 수 있습니다(품위 수지).'},
  load: {v: 'load', lo: 'llo', hi: 'lhi', spec: false, step: 10, name: '적재량',
        tag: '벨트 적재량 · 일별 평균',
        hint: '분석기 헛값은 적재량이 적을 때 몰립니다(헛값 구간 중앙값 15 vs 정상 35). ' +
              '품위가 튀는 날은 이 그래프를 함께 보십시오.'},
};

function drawTrend() {
  const host = $('c-trend'); if (!host) return;
  const M = METRICS[METRIC];
  const tag = $('trend-tag'), hint = $('trend-hint');
  if (tag) tag.textContent = M.tag;
  if (hint) hint.textContent = M.hint;
  const series = lines().map(l => [l, cut(DATA.yard[l] || [])])
    .map(([l, r]) => [l, r.filter(x => x[M.v] != null)]).filter(([, r]) => r.length);
  if (!series.length) { host.innerHTML = empty('이 기간에 값이 없어요.'); return; }
  const W = 1200, H = 300, pl = 44, pr = W - 14, pt = 14, pb = H - 26;
  const s = svg(host, W, H);
  const all = series.flatMap(([, r]) => r);
  let lo = Math.min(...all.map(r => r[M.lo] != null ? r[M.lo] : r[M.v]));
  let hi = Math.max(...all.map(r => r[M.hi] != null ? r[M.hi] : r[M.v]));
  if (M.spec) { lo = Math.min(lo, DATA.target - DATA.tol - 1); hi = Math.max(hi, DATA.target + DATA.tol + 1); }
  const pad = Math.max((hi - lo) * .05, .3);
  lo -= pad; hi += pad;
  const Y = ymap(lo, hi, pb, pt), X = xmap(all.slice().sort((a, b) => a.d < b.d ? -1 : 1), pl, pr);
  if (M.spec) {
    s.appendChild(el('rect', {x: pl, y: Y(DATA.target + DATA.tol), width: pr - pl,
      height: Math.abs(Y(DATA.target - DATA.tol) - Y(DATA.target + DATA.tol)),
      rx: 6, fill: 'var(--band)'}));
  }
  for (let v = Math.ceil(lo / M.step) * M.step; v <= hi; v += M.step) {
    s.appendChild(el('line', {x1: pl, y1: Y(v), x2: pr, y2: Y(v), stroke: 'var(--grid)'}));
    s.appendChild(txt(v, {x: pl - 7, y: Y(v) + 4, 'text-anchor': 'end', class: 'ax'}));
  }
  series.forEach(([l, rows]) => {
    const band = rows.filter(r => r[M.lo] != null && r[M.hi] != null);
    if (band.length > 1) {
      const up = band.map(r => `${X(r.d).toFixed(1)},${Y(r[M.hi]).toFixed(1)}`);
      const dn = band.slice().reverse().map(r => `${X(r.d).toFixed(1)},${Y(r[M.lo]).toFixed(1)}`);
      s.appendChild(el('polygon', {points: up.concat(dn).join(' '), fill: COL[l], opacity: .16}));
    }
    const pts = rows.map(r => `${X(r.d).toFixed(1)},${Y(r[M.v]).toFixed(1)}`).join(' ');
    s.appendChild(el('polyline', {points: pts, fill: 'none', stroke: COL[l],
      'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}));
  });
  dateTicks(s, series[0][1], X, pb);
  let lx = pl + 4;
  series.forEach(([l]) => {
    s.appendChild(el('rect', {x: lx, y: pt - 4, width: 16, height: 3, rx: 1.5, fill: COL[l]}));
    s.appendChild(txt(l, {x: lx + 21, y: pt + 1, class: 'cs'}));
    lx += 82;
  });
  if (M.spec) {
    s.appendChild(txt(`음영 = 목표 ${DATA.target}±${DATA.tol}`,
      {x: pr, y: pt + 1, 'text-anchor': 'end', class: 'cs'}));
  }
}

function drawStock() {
  const host = $('c-stock'); if (!host) return;
  const series = lines().map(l => [l, cut(DATA.stock[l] || [])]).filter(([, r]) => r.length);
  if (!series.length) { host.innerHTML = empty('이 기간에 값이 없어요.'); return; }
  const W = 620, H = 210, pl = 50, pr = W - 12, pt = 12, pb = H - 24;
  const s = svg(host, W, H);
  const Y = ymap(0, DATA.capacity * 1.06, pb, pt);
  const all = series.flatMap(([, r]) => r).sort((a, b) => a.d < b.d ? -1 : 1);
  const X = xmap(all, pl, pr);
  s.appendChild(el('line', {x1: pl, y1: Y(DATA.capacity), x2: pr, y2: Y(DATA.capacity),
    stroke: 'var(--bad)', 'stroke-dasharray': '5 4', 'stroke-width': 1.2}));
  s.appendChild(txt('만실 ' + fmt(DATA.capacity), {x: pr, y: Y(DATA.capacity) - 5, 'text-anchor': 'end', class: 'cs'}));
  [0, 20000, 40000].forEach(v => {
    s.appendChild(el('line', {x1: pl, y1: Y(v), x2: pr, y2: Y(v), stroke: 'var(--grid)'}));
    s.appendChild(txt(v ? (v / 1000) + 'k' : '0', {x: pl - 7, y: Y(v) + 4, 'text-anchor': 'end', class: 'ax'}));
  });
  series.forEach(([l, rows]) => {
    const pts = rows.filter(r => r.t != null).map(r => `${X(r.d).toFixed(1)},${Y(r.t).toFixed(1)}`).join(' ');
    s.appendChild(el('polyline', {points: pts, fill: 'none', stroke: COL[l], 'stroke-width': 2}));
  });
  dateTicks(s, series[0][1], X, pb);
}

function drawFlow() {
  const host = $('c-flow'); if (!host) return;
  const rowsByLine = lines().map(l => [l, cut(DATA.flow[l] || [])]).filter(([, r]) => r.length);
  if (!rowsByLine.length) { host.innerHTML = empty('이 기간에 값이 없어요.'); return; }
  const days = [...new Set(rowsByLine.flatMap(([, r]) => r.map(x => x.d)))].sort();
  const agg = days.map(d => {
    let i = 0, o = 0;
    rowsByLine.forEach(([, r]) => { const h = r.find(x => x.d === d); if (h) { i += h.i || 0; o += h.o || 0; } });
    return {d, i, o};
  });
  const W = 620, H = 210, pl = 50, pr = W - 12, mid = H / 2 - 2, pt = 12, pb = H - 24;
  const s = svg(host, W, H);
  const mx = Math.max(1, ...agg.map(r => Math.max(r.i, r.o)));
  const bw = Math.max(1.5, (pr - pl) / Math.max(agg.length, 1) * .66);
  const X = xmap(agg, pl + bw, pr - bw);
  agg.forEach(r => {
    const x = X(r.d) - bw / 2;
    const hi = (r.i / mx) * (mid - pt), ho = (r.o / mx) * (pb - mid);
    if (r.i) s.appendChild(el('rect', {x: x.toFixed(1), y: (mid - hi).toFixed(1),
      width: bw.toFixed(1), height: hi.toFixed(1), fill: 'var(--accent)'}));
    if (r.o) s.appendChild(el('rect', {x: x.toFixed(1), y: mid.toFixed(1),
      width: bw.toFixed(1), height: ho.toFixed(1), fill: 'var(--bar)'}));
  });
  s.appendChild(el('line', {x1: pl, y1: mid, x2: pr, y2: mid, stroke: 'var(--ink-3)'}));
  s.appendChild(txt('적재', {x: pl - 7, y: pt + 10, 'text-anchor': 'end', class: 'ax'}));
  s.appendChild(txt('인출', {x: pl - 7, y: pb - 2, 'text-anchor': 'end', class: 'ax'}));
  dateTicks(s, agg, X, pb);
}

function drawHist() {
  const host = $('c-hist'); if (!host) return;
  const ed = DATA.hist.edges;
  const ls = lines().filter(l => DATA.hist.lines[l]);
  if (!ls.length) { host.innerHTML = empty('표시할 자료가 없어요.'); return; }
  const W = 1200, H = 280, pl = 44, pr = W - 14, pt = 16, pb = H - 26;
  const s = svg(host, W, H);
  const mx = Math.max(...ls.flatMap(l => DATA.hist.lines[l])) * 1.12;
  const xs = v => pl + (v - ed[0]) / (ed[ed.length - 1] - ed[0]) * (pr - pl);
  const Y = ymap(0, mx, pb, pt);
  s.appendChild(el('rect', {x: xs(DATA.target - DATA.tol), y: pt,
    width: xs(DATA.target + DATA.tol) - xs(DATA.target - DATA.tol), height: pb - pt,
    rx: 6, fill: 'var(--band)'}));
  ls.forEach(l => {
    const v = DATA.hist.lines[l];
    const pts = v.map((p, i) => `${xs((ed[i] + ed[i + 1]) / 2).toFixed(1)},${Y(p).toFixed(1)}`);
    s.appendChild(el('polyline', {points: pts.join(' '), fill: 'none', stroke: COL[l],
      'stroke-width': 2, 'stroke-linejoin': 'round'}));
  });
  [40, 42, 44, 46, 48, 50].forEach(v => s.appendChild(
    txt(v, {x: xs(v), y: pb + 15, 'text-anchor': 'middle', class: 'ax'})));
  s.appendChild(el('line', {x1: pl, y1: pb, x2: pr, y2: pb, stroke: 'var(--line)'}));
  s.appendChild(txt('가로축 CaO(%) · 세로축 비율', {x: pr, y: pt + 2, 'text-anchor': 'end', class: 'cs'}));
}

function drawZones() {
  const host = $('c-zone'); if (!host) return;
  const ls = lines().filter(l => DATA.zones[l]);
  if (!ls.length) { host.innerHTML = empty('표시할 자료가 없어요.'); return; }
  let h = '';
  ls.forEach(l => {
    const z = DATA.zones[l];
    const mx = Math.max(1, ...z.zones.map(x => x.t || 0));
    h += `<div class="zhd">${esc(l)} · 합계 ${fmt(z.total)}톤 <span style="font-weight:400">(${esc(z.at)} 기준)</span></div>`;
    if (!z.zones.length) h += empty('재고 추정이 없어요.');
    z.zones.forEach(x => {
      const inSpec = x.cao != null && Math.abs(x.cao - DATA.target) <= DATA.tol;
      const c = x.cao == null ? 'var(--faint)' : (inSpec ? 'var(--ok)' : 'var(--primary)');
      h += `<div class="zbar"><span class="zn">${esc(x.z)}</span>` +
        `<span class="zt"><i style="width:${(x.t / mx * 100).toFixed(1)}%;background:${c}"></i></span>` +
        `<span class="zv">${fmt(x.t)}t · ${x.cao == null ? '—' : x.cao.toFixed(1) + '%'}</span></div>`;
    });
  });
  host.innerHTML = h;
}

function drawCross() {
  const host = $('c-cross'); if (!host) return;
  const note = $('cross-note');
  const ks = Object.keys(DATA.cross).filter(l => (DATA.cross[l].cross || 0) > 0);
  if (!ks.length) { host.innerHTML = empty('교차인출 기록이 없어요.'); if (note) note.textContent = ''; return; }
  const l = ks[0], c = DATA.cross[l], rows = cut(c.daily);
  if (!rows.length) { host.innerHTML = empty('이 기간에 값이 없어요.'); if (note) note.textContent = ''; return; }
  const W = 1200, H = 190, pl = 50, pr = W - 14, pt = 14, pb = H - 26;
  const s = svg(host, W, H);
  const mx = Math.max(1, ...rows.map(r => r.t || 0));
  const Y = ymap(0, mx * 1.1, pb, pt);
  const bw = Math.max(1.5, (pr - pl) / Math.max(rows.length, 1) * .66);
  const X = xmap(rows, pl + bw, pr - bw);
  rows.forEach(r => {
    const x = X(r.d) - bw / 2;
    if (r.t) s.appendChild(el('rect', {x: x.toFixed(1), y: Y(r.t).toFixed(1),
      width: bw.toFixed(1), height: (pb - Y(r.t)).toFixed(1), fill: 'var(--bar)'}));
    if (r.c) s.appendChild(el('rect', {x: x.toFixed(1), y: Y(r.c).toFixed(1),
      width: bw.toFixed(1), height: (pb - Y(r.c)).toFixed(1), fill: 'var(--warn)'}));
  });
  [0, mx / 2, mx].forEach(v => {
    s.appendChild(el('line', {x1: pl, y1: Y(v), x2: pr, y2: Y(v), stroke: 'var(--grid)'}));
    s.appendChild(txt(fmt(v), {x: pl - 7, y: Y(v) + 4, 'text-anchor': 'end', class: 'ax'}));
  });
  dateTicks(s, rows, X, pb);
  s.appendChild(txt('회색 = 그날 전체 인출 · 주황 = 교차인출분', {x: pr, y: pt + 2, 'text-anchor': 'end', class: 'cs'}));
  if (note) note.innerHTML =
    `<b>${esc(l)} OSP 인출 ${fmt(c.total)}톤 중 ${fmt(c.cross)}톤(${c.pct.toFixed(0)}%, ${fmt(c.n_rows)}건)</b>이 ` +
    `원본 기록의 공정구분에 <b>${esc(c.dest)}</b>으로 적혀 있습니다. 재고는 <b>${esc(l)} OSP</b>에서 빠지지만 ` +
    `물량은 <b>${esc(c.dest)} 라인</b>으로 갑니다. 데이터로 추정한 경로별 이송 시간: <b>${esc(DATA.route_txt)}</b>.`;
}

function drawRecent() {
  const body = $('rec'); if (!body) return;
  const q = Q.trim().toLowerCase();
  const rows = DATA.recent.filter(r => {
    if (LINE !== 'all' && r.line !== LINE) return false;
    if (!q) return true;
    return [r.t, r.kind, r.line, r.zone, r.note].join(' ').toLowerCase().includes(q);
  });
  const n = $('rec-n'); if (n) n.textContent = fmt(rows.length) + '건';
  body.innerHTML = rows.slice(0, 200).map(r => '<tr>' +
    `<td>${esc(r.t)}</td><td>${esc(r.kind)}</td><td>${esc(r.line)}</td>` +
    `<td class="n">${r.zone == null ? '—' : esc(r.zone)}</td><td class="n">${fmt(r.ton)}</td>` +
    `<td class="n">${r.cao == null ? '—' : r.cao.toFixed(2)}</td>` +
    `<td style="color:var(--faint)">${esc(r.note || '')}</td></tr>`).join('') ||
    '<tr><td colspan="7"><div class="empty">해당 기록이 없어요.</div></td></tr>';
}

/* ══ 화면 ═══════════════════════════════════════════════════════════ */
const view = $('view');

function overview() {
  const C = DATA.chain;
  const pctTxt = C.linked_pct == null ? '—' : C.linked_pct.toFixed(1) + '%';
  const tone = C.linked_pct == null ? 'mute' : C.linked_pct >= 95 ? 'good' : C.linked_pct >= 85 ? 'warn' : 'bad';
  const h = C.linked_pct == null ? '추적 상태를<br><em>계산할 수 없어요</em>'
    : C.linked_pct >= 95 ? `광산부터 야드까지<br><em>끝까지</em> 이어졌어요`
    : `데이터가 <em>${esc(pctTxt)}</em><br>이어져 있어요`;
  view.innerHTML = `<div class="page">
    ${head(`종합 현황 · ${esc(DATA.ref)} 기준`, h,
      '<b>이 화면은 품질담당이 "지금 품위와 재고가 정상인지" 를 판단하기 위한 것입니다.</b> ' +
      '맨 위는 광산에서 야드까지 데이터가 얼마나 이어졌는지, 그 아래는 라인별 현재 상태입니다.')}
    <h2 class="sec">추적 연결 <small>이 과제의 성공 기준 · 광산 → OSP → 야드, 네 이음매</small></h2>
    <div class="grid g-kpi">${C.joints.map((j, i) => card({i, no: two(i),
      title: esc(j.name),
      en: esc(j.why),
      well: `<div style="display:flex;gap:12px;align-items:center"><span style="flex:none;display:flex">${statusIcon(j.tone)}</span>` +
        `<div><div class="big" style="font-size:24px">${esc(j.label)}</div>` +
        (j.gap ? `<div class="note" style="color:var(--${j.tone === 'good' ? 'ok' : j.tone === 'warn' ? 'warn' : 'bad'})">↳ ${esc(j.gap)}</div>` : '') +
        '</div></div>'})).join('') || empty('점수판을 만들 수 없어요.')}</div>
    ${box(`<div class="score"><span class="pct is-${tone}">${esc(pctTxt)}</span>` +
      `<span style="color:var(--muted)">이어짐 · ${fmt(C.linked_ton)} / ${fmt(C.total_ton)}톤</span>` +
      `${pill(tone === 'mute' ? 'mute' : tone, tone === 'good' ? '양호' : tone === 'warn' ? '확인 필요' : '기준 이탈')}</div>` +
      `<p class="hint">${C.sentence}</p>` +
      '<p class="hint">구역(칸) 단위가 아니라 <b>라인 단위</b>로 잇습니다 — 현장이 구역별 재고를 ' +
      '측정하지 않아 그 해상도는 가질 수 없고, 가진 척하면 숫자만 그럴듯해집니다. ' +
      '네 칸이 모두 녹색이면 "어느 더미에서 언제 쌓인 돌인지" 를 끝까지 말할 수 있습니다.</p>', 4)}
    <h2 class="sec">라인별 상태 <small>최근 7일</small></h2>
    ${ctrl({dates: false})}
    <div class="grid g2">${lines().map((l, i) => {
      const hd = DATA.head[l] || {};
      const dev = hd.w_mean == null ? null : hd.w_mean - DATA.target;
      const okTone = hd.w_ok == null ? 'mute' : (hd.w_ok >= 60 ? 'ok' : hd.w_ok >= 30 ? 'warn' : 'bad');
      const stale = hd.age_h != null && hd.age_h > 48;
      return box(
        `<h3>${esc(l)} 라인 <span style="font-weight:500;color:var(--faint)">${esc(DATA.alias[l] || '')}</span>` +
        pill(okTone, `최근 7일 규격내 ${hd.w_ok == null ? '—' : hd.w_ok.toFixed(0) + '%'}`) +
        (stale ? pill('mute', '자료 지연') : '') + '</h3>' +
        '<div class="statrow">' +
        `<div class="stat"><div class="v ${dev == null ? '' : (Math.abs(dev) <= DATA.tol ? 'is-good' : 'is-bad')}">` +
        `${hd.last_cao == null ? '—' : hd.last_cao.toFixed(2)}<small>%</small></div><div class="l">최신 CaO</div></div>` +
        `<div class="stat"><div class="v">${hd.w_mean == null ? '—' : hd.w_mean.toFixed(2)}<small>%</small></div><div class="l">7일 평균</div></div>` +
        `<div class="stat"><div class="v ${hd.w_std == null ? '' : (hd.w_std <= DATA.tol ? 'is-good' : 'is-bad')}">` +
        `${hd.w_std == null ? '—' : hd.w_std.toFixed(2)}<small>%p</small></div><div class="l">7일 편차</div></div>` +
        `<div class="stat"><div class="v">${fmt(hd.stock)}<small>t</small></div><div class="l">OSP 재고</div></div>` +
        '</div>' +
        `<div class="gauge"><i style="width:${Math.min(hd.stock_pct || 0, 100).toFixed(1)}%"></i></div>` +
        `<p class="hint">재고 ${hd.stock_pct == null ? '—' : hd.stock_pct.toFixed(0) + '%'} ` +
        `(만실 ${fmt(DATA.capacity)}톤 대비) · 7일 변화 ` +
        `${hd.stock_chg == null ? '—' : (hd.stock_chg > 0 ? '+' : '') + fmt(hd.stock_chg) + '톤'} · ` +
        `최신 측정 ${esc(hd.last_at || '—')}</p>`, 6 + i);
    }).join('')}</div>
  </div>`;
  wireCtrl();
}

function trend() {
  view.innerHTML = `<div class="page">
    ${head('품위 추이', '야드 품위가<br><em>규격 안</em>인가',
      '기간과 라인을 바꾸면 아래 두 그래프가 함께 움직입니다.')}
    ${ctrl()}
    ${box('<h3>야드 품위 <span class="pill mute" id="trend-tag"></span></h3>' +
      `<div style="margin-bottom:12px">${seg('metric', Object.keys(METRICS).map(k => [k, METRICS[k].name]), METRIC)}</div>` +
      '<div class="chart" id="c-trend"></div><p class="hint" id="trend-hint"></p>', 1)}
    ${box('<h3>품위 분포 <span class="pill mute">전체 기간</span></h3><div id="c-hist"></div>' +
      '<p class="hint">규격 폭 안에 얼마나 모여 있는지 봅니다. 봉우리가 좁고 음영 안에 있을수록 좋습니다.</p>', 2)}
  </div>`;
  wireCtrl();
  onPick('metric', (v) => { METRIC = v; render(CUR); });
  drawTrend(); drawHist();
}

function stock() {
  view.innerHTML = `<div class="page">
    ${head('재고', 'OSP 에<br><em>무엇이</em> 얼마나 있나',
      '재고가 낮아지면 배합 선택지가 줄어듭니다. 구역별 재고는 <b>추정치</b>입니다.')}
    ${ctrl()}
    <div class="grid g2">
      ${box('<h3>OSP 재고 추이 <span class="pill mute">실사 기준</span></h3><div id="c-stock"></div>' +
        '<p class="hint">점선은 만실 용량입니다.</p>', 1)}
      ${box('<h3>적재 · 인출 <span class="pill mute">일별 톤</span></h3><div id="c-flow"></div>' +
        '<p class="hint">위쪽이 광산에서 들어온 양, 아래쪽이 야드로 나간 양입니다.</p>', 2)}
    </div>
    ${box('<h3>구역별 재고 <span class="pill warn">추정</span></h3><div id="c-zone"></div>' +
      '<p class="hint">막대 길이는 추정 재고량, 색은 품위입니다 — ' +
      '<b style="color:var(--ok)">초록</b>이 규격 안, 파랑이 규격 밖입니다. ' +
      '구역별 재고는 측정값이 아니라 흐름에서 복원한 추정치입니다.</p>', 3)}
  </div>`;
  wireCtrl();
  drawStock(); drawFlow(); drawZones();
}

function cross() {
  view.innerHTML = `<div class="page">
    ${head('교차인출', '기존 OSP 에서 뽑아<br><em>신설</em>로 보낸 물량',
      '재고는 <b>기존</b> 적치장에서 빠지고, 품위는 <b>신설</b> 야드로 갑니다 — 두 가지를 따로 귀속시켜 계산합니다.')}
    ${ctrl()}
    ${box('<h3>일별 인출 중 교차분 <span class="pill ok">반영됨</span></h3>' +
      '<div class="chart" id="c-cross"></div><p class="hint" id="cross-note"></p>', 1)}
  </div>`;
  wireCtrl();
  drawCross();
}

function recent() {
  view.innerHTML = `<div class="page">
    ${head('최근 기록', '원본 기록을<br><em>그대로</em> 봅니다',
      '숫자가 이상해 보이면 여기서 원본 행을 찾아 확인합니다(§2-3 검증 가능성).')}
    ${ctrl({dates: false})}
    ${box('<h3>최근 기록 <span class="pill mute" id="rec-n"></span></h3>' +
      `<input id="q" class="search" placeholder="검색 — 구역 번호·라인·비고" aria-label="기록 검색" value="${esc(Q)}">` +
      '<div class="scroll tall" style="margin-top:12px"><table><thead><tr>' +
      '<th>시각</th><th>구분</th><th>라인</th><th class="n">구역</th>' +
      '<th class="n">톤</th><th class="n">CaO</th><th>비고</th>' +
      '</tr></thead><tbody id="rec"></tbody></table></div>', 1)}
  </div>`;
  wireCtrl();
  const q = $('q');
  q.oninput = () => { Q = q.value; drawRecent(); };
  drawRecent();
}

const PAGES = {overview, trend, stock, cross, recent};

/* ── 메뉴·라우팅 ──────────────────────────────────────────────────── */
const NAMES = Object.fromEntries(MENU.views.map(([k, n]) => [k, n]));
const svgI = (k) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  `stroke-linecap="round" stroke-linejoin="round">${MENU.icons[k] || ''}</svg>`;
$('tabs').innerHTML = MENU.groups.map(([g, ids]) =>
  (g ? `<div class="grp">${esc(g)}</div>` : '') +
  ids.map(id => `<button class="navi" data-id="${id}" title="${esc(NAMES[id])}">${svgI(id)}<span class="lbl">${esc(NAMES[id])}</span></button>`).join('')
).join('');
$('tabbar').innerHTML = MENU.views.map(([id, , short]) =>
  `<button role="tab" data-id="${id}">${svgI(id)}<span>${esc(short)}</span></button>`).join('');
$('genAt').textContent = `생성 ${DATA.built}`;
$('refchip').innerHTML = `<i></i>기준일 ${esc(DATA.ref)}`;

let CUR = 'overview';
function render(id) {
  if (!PAGES[id]) id = 'overview';
  CUR = id;
  $('tabs').querySelectorAll('button').forEach(b =>
    b.dataset.id === id ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
  $('tabbar').querySelectorAll('button').forEach(b =>
    b.setAttribute('aria-selected', b.dataset.id === id ? 'true' : 'false'));
  const grp = (MENU.groups.find(([, ids]) => ids.includes(id)) || [])[0];
  $('where').innerHTML = `현황판 › ${grp ? esc(grp) + ' › ' : ''}<b>${esc(NAMES[id])}</b>`;
  PAGES[id]();
}
const go = (id) => {
  if (location.hash !== '#' + id) location.hash = id; else render(id);
  scrollTo({top: 0});
};
for (const nav of [$('tabs'), $('tabbar')]) nav.addEventListener('click', (e) => {
  const b = e.target.closest('button[data-id]'); if (b) go(b.dataset.id);
});
addEventListener('hashchange', () => render(location.hash.slice(1)));

// 화면 폭이 크게 바뀌면 SVG 를 다시 그린다(그래프 폭이 고정 viewBox 라 글자 크기가 달라진다)
let lastW = innerWidth, rz;
addEventListener('resize', () => {
  clearTimeout(rz);
  rz = setTimeout(() => { if (Math.abs(innerWidth - lastW) > 40) { lastW = innerWidth; render(CUR); } }, 250);
});
addEventListener('scroll', () => {
  $('top').classList.toggle('scrolled', scrollY > 4);
  $('fab').classList.toggle('on', scrollY > 600);
}, {passive: true});
$('fab').addEventListener('click', () => scrollTo({
  top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}));

const setMini = (on) => {
  $('shell').classList.toggle('mini', on);
  const t = on ? '메뉴 펼치기' : '메뉴 접기';
  $('collapse').setAttribute('aria-label', t); $('collapse').title = t;
  store.set('b365_side_mini', on ? '1' : '');
};
$('collapse').addEventListener('click', () => setMini(!$('shell').classList.contains('mini')));
if (store.get('b365_side_mini')) setMini(true);

$('share').addEventListener('click', async () => {
  const url = location.href.split('#')[0] + location.hash, isFile = location.protocol === 'file:';
  if (!isFile && navigator.share) {
    try { await navigator.share({title: document.title, url}); return; }
    catch (e) { if (e && e.name === 'AbortError') return; }
  }
  const text = isFile ? decodeURI(location.pathname.replace(/^\/([A-Za-z]:)/, '$1')).replace(/\//g, '\\') : url;
  try { await navigator.clipboard.writeText(text); toast(isFile ? '파일 위치를 복사했어요' : '링크를 복사했어요'); }
  catch (e) { toast('복사가 막혀 있어요 — 주소창의 주소를 복사해 주세요'); }
});

render(location.hash.slice(1) || 'overview');
})();
"""


def main():
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = P.OUTPUTS_DIR / "dashboard.html"
    doc = build()
    dst.write_text(doc, encoding="utf-8")
    print(f"[OK] 품위·재고 현황판: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
