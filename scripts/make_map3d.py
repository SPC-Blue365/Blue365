"""3D 공정 지도 [Synthesis-Agent] — 광산 → 크러셔·수항 → OSP → 야드를 3D 로 운영한다.

사용자 요청(2026-11-24): "3D 운영으로 생성해줘. 시멘트 생산공정 프로젝트처럼"
레퍼런스: 같은 계정의 **Blue365 공정 지도**(claude.ai/artifact/AfsA3zhW7CAkuGKjK7Bihf) — 전체 화면
3D 공장 지도 위에 흰 카드(지표·공정 탭·지도 조작·상세 패널·추적 단계·목록)를 얹은 화면.
같은 공장의 상류(광산·크러셔·OSP·P/W·프리블렌딩)를 그 지도와 **같은 문법**으로 그린다:
  · 팔레트·조명·안개·카메라(궤도: 끌기=이동 · 오른쪽 끌기=회전 · 휠=확대)·떠 있는 이름표
  · 원뿔 더미 · 층진 광산 · 패들휠(P/W) · 벨트 위 물량 입자 · 상태 점(정상/주의/이탈)

⭐️ 레퍼런스와 **다른 점 — 가상 데이터를 쓰지 않는다(§2-1).** 레퍼런스는 시연용 '가상 데이터' 로 값이
   움직이지만, 이 지도의 숫자·색·벨트 입자 수는 전부 `map3d_data.build_payload()` 가 원본에서 계산한 값이다.
   측정하지 않는 것(수항 재고·구역 재고·크러셔별 물량)은 측정한 척하지 않고 화면에 그렇게 적는다.

⭐️ 인터넷 없이 열린다 — Three.js r149(레퍼런스와 같은 판)를 파일 안에 싣는다
   (`src/visualization/vendor/three-0.149.0.min.js`, MIT).

실행: python scripts/make_map3d.py  →  outputs/map3d.html
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from config import paths as P                                           # noqa: E402
from src.visualization.map3d_data import build_payload                  # noqa: E402
from src.visualization.qmsstyle import DOC_STYLE, foot, nav             # noqa: E402

VENDOR = Path(__file__).resolve().parents[1] / "src" / "visualization" / "vendor"
THREE_JS = VENDOR / "three-0.149.0.min.js"


# ══════════════════════════════════════════════════════════════════════════
# 화면 CSS — 레퍼런스(공정 지도)의 오버레이 카드를 QMS 토큰으로. 클래스는 m3- 로 시작한다
# (문서 층의 .tag·.panel·.kpis 와 이름이 겹치지 않게).
# ══════════════════════════════════════════════════════════════════════════
PAGE_CSS = r"""
body.m3page { overflow: hidden }
body.m3page .wrap.ft { display: none }
.m3 { position: relative; height: calc(100vh - 61px); height: calc(100dvh - 61px); overflow: hidden; background: var(--bg) }
html.embedded .m3 { height: 100vh; height: 100dvh }
#m3stage { position: absolute; inset: 0; outline: none; touch-action: none; cursor: grab }
#m3stage.drag { cursor: grabbing } #m3stage.hover { cursor: pointer }
#m3stage canvas { display: block }
.m3-nogl { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; color: var(--muted); padding: 24px }

/* 떠 있는 이름표 */
#m3tags { position: absolute; inset: 0; pointer-events: none; overflow: hidden }
.m3-tag { position: absolute; left: 0; top: 0; pointer-events: auto; display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px 5px 8px; border-radius: 999px;
  background: var(--surface); color: var(--ink); font-size: 12px; font-weight: 700; box-shadow: var(--shadow); white-space: nowrap; will-change: transform; border: 0; cursor: pointer }
.m3-tag i { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); flex: none }
.m3-tag.s-warn i { background: var(--warn) } .m3-tag.s-bad i { background: var(--bad) } .m3-tag.s-none i { background: var(--faint) }
.m3-tag small { font-weight: 600; color: var(--faint) }
.m3-tag.mini { padding: 4px 8px; font-size: 11px; font-weight: 600 }
.m3-tag.route { background: var(--primary-soft); color: var(--primary-ink) } .m3-tag.route small { color: var(--primary-ink); opacity: .8 }
.m3-tag.ghost { background: var(--well); color: var(--muted); box-shadow: none }
.m3-tag.sel { background: var(--primary); color: #fff; z-index: 2 } .m3-tag.sel small { color: #fff; opacity: .85 } .m3-tag.sel i { background: #fff }

/* 오버레이 공통 — 흰 카드(둥근 20px) */
.m3-card { position: absolute; background: var(--surface); border-radius: var(--r-card); box-shadow: var(--shadow); z-index: 5 }
.m3-top { position: absolute; left: 16px; right: 16px; top: 16px; z-index: 6; display: flex; gap: 12px; align-items: flex-start; pointer-events: none; flex-wrap: wrap }
.m3-top > * { pointer-events: auto }
.m3-tabs { display: flex; gap: 2px; background: var(--surface); border-radius: 16px; box-shadow: var(--shadow); padding: 0 8px; overflow-x: auto; scrollbar-width: none; max-width: 100% }
.m3-tabs button { position: relative; height: 46px; padding: 0 12px; border: 0; background: none; font: inherit; font-weight: 700; font-size: 14px; color: var(--faint); white-space: nowrap; cursor: pointer }
.m3-tabs button::after { content: ""; position: absolute; left: 10px; right: 10px; bottom: 0; height: 3px; border-radius: 3px 3px 0 0; background: var(--primary); transform: scaleX(0); transition: transform .28s var(--ease-out) }
.m3-tabs button[aria-selected="true"] { color: var(--ink) } .m3-tabs button[aria-selected="true"]::after { transform: scaleX(1) }
.m3-asof { display: inline-flex; align-items: center; gap: 7px; height: 46px; padding: 0 14px; border-radius: 16px; background: var(--surface); box-shadow: var(--shadow); font-size: 13px; color: var(--muted); white-space: nowrap }
.m3-asof i { width: 8px; height: 8px; border-radius: 50%; background: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft) }
.m3-asof b { color: var(--ink) }

.m3-kpis { position: absolute; left: 16px; top: 74px; z-index: 5; display: flex; gap: 12px; flex-wrap: wrap; width: calc(100% - 420px); pointer-events: none }
.m3-kpi { pointer-events: auto; background: var(--surface); border-radius: var(--r-card); box-shadow: var(--shadow); padding: 13px 15px; min-width: 176px; flex: 0 1 220px; cursor: pointer; border: 2px solid transparent; text-align: left; font: inherit; color: inherit }
.m3-kpi:hover { border-color: var(--primary-soft) }
.m3-kpi .kl { font-size: 12px; color: var(--muted); font-weight: 700; display: flex; align-items: center; gap: 6px }
.m3-kpi .kl i { width: 7px; height: 7px; border-radius: 50%; background: var(--ok) } .m3-kpi.s-warn .kl i { background: var(--warn) } .m3-kpi.s-bad .kl i { background: var(--bad) } .m3-kpi.s-none .kl i { background: var(--faint) }
.m3-kpi .kv { font-size: 24px; font-weight: 800; letter-spacing: -.02em; line-height: 1.25; margin-top: 2px }
.m3-kpi .kv small { font-size: 13px; font-weight: 700; color: var(--muted); margin-left: 2px }
.m3-kpi .ks { font-size: 12px; color: var(--faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis }

.m3-ctrls { position: absolute; right: 388px; top: 74px; display: flex; flex-direction: column; background: var(--surface); border-radius: 16px; box-shadow: var(--shadow); padding: 4px; z-index: 5 }
.m3-ctrls button { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; color: var(--ink2); border: 0; background: none; cursor: pointer }
.m3-ctrls button:hover { background: var(--hover); color: var(--primary) }
.m3-ctrls button[aria-pressed="true"] { color: var(--primary) }
.m3-ctrls hr { border: 0; height: 1px; background: var(--line); margin: 3px 6px }
.m3-ctrls svg { width: 20px; height: 20px }

/* 상세 패널 */
.m3-detail { top: 74px; right: 16px; width: 356px; max-height: calc(100% - 380px); overflow: auto; padding: 18px; display: flex; flex-direction: column; gap: 14px }
.m3-dh { display: flex; gap: 12px; align-items: flex-start }
.m3-dic { width: 44px; height: 44px; border-radius: 14px; background: var(--primary-soft); color: var(--primary); display: grid; place-items: center; flex: none }
.m3-dic svg { width: 22px; height: 22px }
.m3-eb { font-size: 11.5px; font-weight: 800; color: var(--primary) }
.m3-dn { font-size: 18px; font-weight: 800; letter-spacing: -.02em; margin-top: 1px }
.m3-ds { font-size: 12.5px; color: var(--faint); margin-top: 2px; line-height: 1.5 }
.m3-x { margin-left: auto; width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; color: var(--faint); border: 1px solid var(--line); background: none; cursor: pointer; flex: none }
.m3-x:hover { color: var(--primary); border-color: var(--primary) }
.m3-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; border-radius: 8px; padding: 4px 9px; white-space: nowrap }
.m3-badge::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor }
.m3-badge.s-ok { color: var(--ok-ink); background: var(--ok-bg) } .m3-badge.s-warn { color: var(--warn-ink); background: var(--warn-bg) }
.m3-badge.s-bad { color: var(--bad-ink); background: var(--bad-bg) } .m3-badge.s-none { color: var(--muted); background: var(--well) }
.m3-badge.s-info { color: var(--primary-ink); background: var(--primary-soft) }
.m3-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center }
.m3-kv { margin: 0; display: flex; flex-direction: column }
.m3-kv div { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--line); font-size: 13.5px }
.m3-kv div:last-child { border-bottom: 0 }
.m3-kv dt { color: var(--muted) } .m3-kv dd { margin: 0; font-weight: 800; text-align: right; font-variant-numeric: tabular-nums }
.m3-kv dd small { font-weight: 600; color: var(--faint); margin-left: 3px }
.m3-sec { font-size: 12.5px; font-weight: 800; color: var(--ink2); display: flex; justify-content: space-between; align-items: baseline; gap: 8px }
.m3-sec small { font-weight: 600; color: var(--faint) }
.m3-spark { background: var(--well); border-radius: 14px; padding: 10px 12px 6px }
.m3-spark svg { width: 100%; height: 70px; display: block }
.m3-note { font-size: 12.5px; color: var(--muted); line-height: 1.65; margin: 0 }
.m3-note b { color: var(--ink2) }
.m3-zones { display: grid; grid-template-columns: repeat(auto-fill, minmax(70px, 1fr)); gap: 6px }
.m3-zone { background: var(--well); border-radius: 10px; padding: 7px 8px; font-size: 12px; text-align: left; border: 0; font: inherit; cursor: default }
.m3-zone b { display: block; font-size: 13px } .m3-zone small { color: var(--faint) }
.m3-zone.s-ok b { color: var(--ok-ink) } .m3-zone.s-warn b { color: var(--warn-ink) } .m3-zone.s-bad b { color: var(--bad-ink) }

/* 추적 단계(왼쪽 아래) · 최근 기록(오른쪽 아래) */
.m3-chain { left: 16px; bottom: 16px; right: 388px; max-width: 760px; padding: 14px 18px 16px; display: flex; flex-direction: column; gap: 12px }
.m3-chh { display: flex; align-items: baseline; gap: 10px; font-weight: 800 }
.m3-chh b { font-size: 22px; letter-spacing: -.02em } .m3-chh small { margin-left: auto; color: var(--faint); font-weight: 600; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.m3-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)) }
.m3-step { display: flex; flex-direction: column; align-items: center; gap: 5px; position: relative; text-align: center; min-width: 0 }
.m3-step::before { content: ""; position: absolute; top: 15px; left: calc(-50% + 18px); right: calc(50% + 18px); height: 2px; background: var(--primary-soft) }
.m3-step:first-child::before { display: none }
.m3-step .sb { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; background: var(--ok); color: #fff; font-weight: 800; font-size: 13px; position: relative; z-index: 1 }
.m3-step.s-warn .sb { background: var(--warn); color: #1d1d1d } .m3-step.s-bad .sb { background: var(--bad) } .m3-step.s-none .sb { background: var(--faint) }
.m3-step b { font-size: 12.5px; white-space: nowrap } .m3-step small { font-size: 12px; color: var(--muted); white-space: nowrap }
.m3-list { right: 16px; bottom: 16px; width: 356px; padding: 14px 14px 8px; display: flex; flex-direction: column; gap: 8px }
.m3-lh { display: flex; align-items: center; gap: 10px }
.m3-lh b { font-size: 14px } .m3-lh small { margin-left: auto; color: var(--faint); font-size: 12px }
.m3-seg { display: inline-flex; background: var(--line); border-radius: 12px; padding: 3px; gap: 2px }
.m3-seg button { padding: 5px 10px; border-radius: 9px; font: inherit; font-size: 12.5px; font-weight: 700; color: var(--muted); border: 0; background: none; cursor: pointer }
.m3-seg button[aria-pressed="true"] { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.1) }
.m3-rows { max-height: 196px; overflow: auto; margin: 0 -6px }
.m3-rw { display: grid; grid-template-columns: 78px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 8px 6px; border-radius: 12px; width: 100%; text-align: left; border: 0; background: none; font: inherit; color: inherit; cursor: pointer }
.m3-rw:hover { background: var(--well) }
.m3-rw .t { font-size: 12px; color: var(--faint); font-variant-numeric: tabular-nums }
.m3-rw .m { font-size: 13px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis } .m3-rw .m small { font-weight: 500; color: var(--faint); margin-left: 4px }
.m3-rw .v { font-size: 12.5px; color: var(--ink2); text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums }
.m3.nopanels .m3-chain, .m3.nopanels .m3-list { display: none }
/* 오른쪽 아래 '최근 기록' 카드와 겹치지 않게 — 카드가 없으면(숨김·좁은 화면) 끝까지 늘린다 */
.m3.nopanels .m3-detail { max-height: calc(100% - 90px) }
@media (max-width: 900px) { .m3-detail { max-height: calc(100% - 90px) } }
.m3.nodetail .m3-detail { display: none }
.m3.nodetail .m3-ctrls { right: 16px }
.m3.nodetail .m3-chain { right: 388px }
.m3.nodetail .m3-kpis { width: calc(100% - 80px) }
.m3-hint { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); background: var(--toast); color: var(--toast-ink); padding: 9px 14px; border-radius: 999px; font-size: 13px; font-weight: 600; z-index: 7; pointer-events: none; transition: opacity .4s }
.m3-hint.off { opacity: 0 }

@media (max-width: 1180px) { .m3-chain { display: none } .m3-kpis { width: calc(100% - 420px) } }
@media (max-width: 900px) { .m3-list { display: none } }
@media (max-width: 720px) {
  .m3 { height: calc(100dvh - 60px - 68px - env(safe-area-inset-bottom, 0px)) }
  html.embedded .m3 { height: 100dvh }
  .m3-top { left: 8px; right: 8px; top: 8px; gap: 8px }
  .m3-asof { display: none }
  .m3-tabs button { height: 40px; font-size: 13px; padding: 0 10px }
  .m3-kpis { left: 0; right: 0; top: 56px; width: auto; flex-wrap: nowrap; overflow-x: auto; padding: 0 8px 8px; scrollbar-width: none }
  .m3-kpi { flex: 0 0 158px; min-width: 0; padding: 10px 12px } .m3-kpi .kv { font-size: 19px }
  .m3-kpi .kl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block } .m3-kpi .kl i { display: inline-block; margin-right: 5px; vertical-align: 1px }
  .m3-ctrls, .m3.nodetail .m3-ctrls { right: 8px; top: 156px } .m3-ctrls button { width: 36px; height: 36px }
  .m3-detail { left: 0; right: 0; bottom: 0; top: auto; width: auto; max-height: 58%; border-radius: 20px 20px 0 0 }
  .m3.nodetail .m3-detail { display: none }
}
@media (prefers-reduced-motion: reduce) { .m3-tabs button::after { transition: none } }
"""

PAGE_HTML = r"""
<div class="m3" id="m3">
  <div id="m3stage" tabindex="0" aria-label="석회석 공정 3D 지도. 끌어서 이동, 휠로 확대, 오른쪽 버튼으로 끌면 회전"></div>
  <div id="m3tags"></div>
  <div class="m3-top">
    <div class="m3-tabs" id="m3tabs" role="tablist" aria-label="구역"></div>
    <span class="m3-asof" id="m3asof"></span>
  </div>
  <div class="m3-kpis" id="m3kpis"></div>
  <div class="m3-ctrls" role="toolbar" aria-label="지도 조작">
    <button type="button" data-cam="in" aria-label="확대" title="확대"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg></button>
    <button type="button" data-cam="out" aria-label="축소" title="축소"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14"/></svg></button>
    <hr>
    <button type="button" data-cam="rl" aria-label="왼쪽으로 회전" title="왼쪽으로 회전"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg></button>
    <button type="button" data-cam="rr" aria-label="오른쪽으로 회전" title="오른쪽으로 회전"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg></button>
    <hr>
    <button type="button" data-cam="home" aria-label="전체 보기" title="전체 보기"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/></svg></button>
    <hr>
    <button type="button" id="m3panels" aria-pressed="false" aria-label="아래 카드 숨기기" title="추적 단계·최근 기록 숨기기"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 14h18"/></svg></button>
  </div>
  <aside class="m3-card m3-detail" id="m3detail" aria-live="polite"></aside>
  <section class="m3-card m3-chain" id="m3chain" aria-label="추적 연결"></section>
  <section class="m3-card m3-list" id="m3list" aria-label="최근 기록"></section>
  <div class="m3-hint" id="m3hint">끌어서 이동 · 휠로 확대 · 오른쪽 버튼으로 회전 · 설비를 누르면 상세</div>
</div>
"""

# ══════════════════════════════════════════════════════════════════════════
# 화면 코드 — 보통 문자열(f-string 아님). 값은 전부 payload 에서 온다.
# ══════════════════════════════════════════════════════════════════════════
PAGE_JS = r"""
(() => {
"use strict";
const P = JSON.parse(document.getElementById('m3payload').textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const nf = (v, d = 0) => v == null || !isFinite(v) ? '—' : Number(v).toLocaleString('ko-KR', {minimumFractionDigits: d, maximumFractionDigits: d});
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const isMobile = () => matchMedia('(max-width: 720px)').matches;
const OLD = P.lines[0], NEW = P.lines[1];
const ST_TXT = {ok: '정상', warn: '주의', bad: '이탈', none: '자료 없음', info: '참고'};

/* ── 상태 판정(문구는 화면에 그대로 보인다) ───────────────────────── */
const ospSt = (o) => o.pct == null ? 'none' : (o.pct >= 90 || o.pct <= 15) ? 'warn' : 'ok';
const surgeSt = () => P.surge.open_fill > P.surge.cap ? 'warn' : 'ok';
const chainSt = (t) => ({good: 'ok', warn: 'warn', bad: 'bad'}[t] || 'none');

/* ── 레퍼런스(시멘트 공정 지도) 팔레트 그대로 ──────────────────────── */
const PAL = {
 light: {bg:'#F2F4F6',ground:'#E6EBF2',pad:'#EEF2F7',grass:'#D9EBDF',road:'#D1D9E3',mark:'#FFFFFF',wall:'#F9FBFD',wall2:'#E6EBF2',accent:'#3182F6',steel:'#C6CFDB',steelDark:'#8995A5',concrete:'#D7DCE3',limestone:'#C8B79A',rock:'#B9AA92',rock2:'#A39379',slag:'#8E8A84',tree:'#5DBA88',trunk:'#9C8468',truckY:'#F2B53A',dirt:'#CDBFA6',glass:'#A9CAF5',ghost:'#DDE3EA',ok:'#0E9F6E',warn:'#D98200',bad:'#E5484D',none:'#98A2AE'},
 dark: {bg:'#0F1115',ground:'#161A21',pad:'#1B2028',grass:'#1A2A23',road:'#252B35',mark:'#3D4553',wall:'#454D59',wall2:'#353C47',accent:'#3D86F5',steel:'#5D6776',steelDark:'#3F4754',concrete:'#3B414B',limestone:'#6F6757',rock:'#5E5749',rock2:'#514A3E',slag:'#4A4744',tree:'#2F7A55',trunk:'#5C4D3E',truckY:'#C9952E',dirt:'#4A4337',glass:'#2F5A93',ghost:'#2A3039',ok:'#2FBF85',warn:'#F5A623',bad:'#F2646A',none:'#7E8794'},
};
const isDark = () => { const t = document.documentElement.getAttribute('data-theme');
  return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; };

/* ── 배치(월드 좌표) — 흐름은 서→동(화면 왼쪽→오른쪽), 기존 라인이 뒤·신설 라인이 앞 ── */
const Z = {}; Z[OLD] = -22; Z[NEW] = 16;
const X = {qry: -122, cr: -96, surge: -84, tower: -74, osp0: -60, osp1: -24, pw: -19, an: 0, yard: 24, kiln: 62};
const QZ = {'47Q': -32, '49Q': 10, '45Q': -10};
const ZONE_DX = 1.65;                       // 구역 0~100(5 간격) → 21칸
const zoneX = (z) => X.osp0 + 1.5 + (z / 5) * ZONE_DX;

/* ── 장치 목록(이름표·상세 패널·선택의 단위) ─────────────────────── */
const EQ = [];
const addEq = (o) => { EQ.push(o); return o; };
Object.values(P.quarries).forEach((q) => addEq({id: 'Q' + q.id, kind: 'qry', name: q.id + ' 광산', icon: 'mountain', tab: 'mine',
  x: X.qry, z: QZ[q.id] ?? 0, y: 9, st: 'ok', sub: `7일 ${nf(q.ton7)}t`, q}));
addEq({id: 'GC', kind: 'cr', name: 'G/C 크러셔', icon: 'factory', tab: 'mine', x: X.cr, z: 2, y: 10, st: 'ok', sub: `단독 ${P.crushers.gc_only}교대`});
addEq({id: 'HC', kind: 'cr', name: 'H/C 크러셔', icon: 'factory', tab: 'mine', x: X.cr, z: -12, y: 10, st: 'ok', sub: `단독 ${P.crushers.hc_only}교대`});
addEq({id: 'SURGE', kind: 'surge', name: '수항(사일로)', icon: 'silo', tab: 'mine', x: X.surge, z: -5, y: 15, st: surgeSt(), sub: surgeSt() === 'warn' ? '고갈 기록 빠짐' : ''});
[OLD, NEW].forEach((ln) => {
  const o = P.osp[ln];
  addEq({id: 'OSP' + ln, kind: 'osp', ln, name: `OSP ${ln}`, icon: 'layers', tab: 'osp', major: true, x: (X.osp0 + X.osp1) / 2, z: Z[ln], y: 9,
         st: ospSt(o), sub: o.pct == null ? '' : `재고 ${nf(o.stock)}t · ${nf(o.pct)}%`, o});
  addEq({id: 'PW' + ln, kind: 'pw', ln, name: `P/W ${ln}`, icon: 'wheel', tab: 'osp', mini: true, x: X.pw, z: Z[ln], y: 5,
         st: o.pw_active ? 'ok' : 'none', sub: o.pw_active ? '24시간 안 인출' : `마지막 ${o.last_out || '—'}`, o});
  const y = P.yards[ln];
  addEq({id: 'YD' + ln, kind: 'yard', ln, name: `${y.analyzer} 야드`, icon: 'gauge', tab: 'yard', major: true, x: X.yard, z: Z[ln], y: 9,
         st: y.st, sub: y.last_cao == null ? '' : `최신 ${nf(y.last_cao, 2)}%`, y});
  addEq({id: 'KL' + ln, kind: 'kiln', ln, name: ln === OLD ? '4·5K 킬른' : '6·7K 킬른', icon: 'flame', tab: 'yard', mini: true, ghost: true,
         x: X.kiln, z: Z[ln], y: 7, st: 'none', sub: '범위 밖'});
});
addEq({id: 'LSLAG', kind: 'lslag', name: P.lslag.name, icon: 'layers', tab: 'osp', x: -40, z: -48, y: 7, st: 'info', sub: `누적 ${nf(P.lslag.ton)}t`});
P.routes.forEach((r) => {
  const cross = r.src !== r.dest;
  addEq({id: `R${r.src}${r.dest}`, kind: 'route', r, name: cross ? `교차인출 ${r.src}→${r.dest}` : `${r.src} → ${P.yards[r.dest].analyzer}`,
         icon: 'belt', tab: 'yard', route: true, x: cross ? -10 : -9, z: cross ? (Z[OLD] + Z[NEW]) / 2 + 2 : Z[r.dest], y: cross ? 9 : 7,
         st: 'info', sub: `${r.lag}시간${r.field ? ' · 현장 확정' : ''}`});
});
const E = Object.fromEntries(EQ.map((e) => [e.id, e]));

/* ── 아이콘(상세 패널 머리) ────────────────────────────────────── */
const IC = {
  mountain: '<path d="m3 20 6-11 4 6 3-4 5 9z"/>', factory: '<path d="M3 21V9l6 4V9l6 4V5h6v16z"/>', silo: '<path d="M7 21V8a5 5 0 0 1 10 0v13"/><path d="M5 21h14"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>', wheel: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16M4 12h16"/>',
  gauge: '<path d="M4 18a8 8 0 1 1 16 0"/><path d="m12 18 4-6"/>', flame: '<path d="M12 3c3 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 0 2 1 3 2 3 0-3 0-5 1-7z"/>',
  belt: '<circle cx="6" cy="14" r="3"/><circle cx="18" cy="14" r="3"/><path d="M6 11h12M6 17h12"/>',
};
const svgI = (k) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${IC[k] || ''}</svg>`;

/* ══ 3D 장면 ════════════════════════════════════════════════════ */
let THREEOK = typeof THREE !== 'undefined';
let renderer, scene, camera, hemi, sun, raycaster, pointer;
const M = {}, OBJ = {}, ANCHOR = {}, FLOWS = [], WHEELS = [], RINGS = [];
const cam = {tx: -30, tz: -4, dist: 260, theta: .62, phi: .96}, goal = {...cam};
let selRing = null;

function makeMats() {
  const mk = (n, key, o = {}) => { M[n] = new THREE.MeshStandardMaterial(Object.assign({color: PAL.light[key], roughness: .85, metalness: .02}, o)); M[n].userData.key = key; };
  mk('ground', 'ground'); mk('pad', 'pad'); mk('road', 'road'); mk('mark', 'mark'); mk('grass', 'grass'); mk('dirt', 'dirt');
  mk('wall', 'wall'); mk('wall2', 'wall2'); mk('accent', 'accent', {roughness: .6}); mk('steel', 'steel', {metalness: .25, roughness: .55});
  mk('steelD', 'steelDark', {metalness: .25, roughness: .6}); mk('conc', 'concrete'); mk('lime', 'limestone'); mk('rock', 'rock', {flatShading: true});
  mk('rock2', 'rock2', {flatShading: true}); mk('slag', 'slag', {flatShading: true}); mk('tree', 'tree', {flatShading: true}); mk('trunk', 'trunk');
  mk('ylw', 'truckY', {roughness: .6}); mk('glass', 'glass', {roughness: .3, metalness: .1});
  mk('ghost', 'ghost', {transparent: true, opacity: .55});
  ['ok', 'warn', 'bad', 'none'].forEach((k) => { M['st_' + k] = new THREE.MeshBasicMaterial({color: PAL.light[k]}); M['st_' + k].userData.key = k; });
  M.sel = new THREE.MeshBasicMaterial({color: PAL.light.accent, transparent: true, opacity: .9, depthWrite: false}); M.sel.userData.key = 'accent';
}
function applyPalette() {
  if (!THREEOK || !scene) return;
  const dk = isDark(), pal = dk ? PAL.dark : PAL.light;
  Object.values(M).forEach((m) => { if (m.userData.key) m.color.set(pal[m.userData.key]); });
  renderer.setClearColor(pal.bg, 1); scene.fog.color.set(pal.bg);
  hemi.intensity = dk ? .55 : .66; sun.intensity = dk ? .55 : .62;
  hemi.color.set(dk ? '#B9C6DA' : '#FFFFFF'); hemi.groundColor.set(dk ? '#1A1F27' : '#C9D3E0');
}
const add = (m, p = scene, sh = true) => { m.castShadow = sh; m.receiveShadow = true; p.add(m); return m; };
function box(p, w, h, d, mat, x, y, z) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.position.set(x, y + h / 2, z); return add(m, p); }
function cyl(p, r, h, mat, x, y, z, seg = 28, r2) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r2 ?? r, h, seg), mat); m.position.set(x, y + h / 2, z); return add(m, p); }
function flat(w, d, mat, x, z, y = .03, rot = 0) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, .06, d), mat); m.position.set(x, y, z); m.rotation.y = rot; m.receiveShadow = true; scene.add(m); return m; }
function seg(x1, z1, x2, z2, w, mat, y = .05) { const dx = x2 - x1, dz = z2 - z1; return flat(Math.hypot(dx, dz) + w, w, mat, (x1 + x2) / 2, (z1 + z2) / 2, y, Math.atan2(-dz, dx)); }
function grp(id) { const g = new THREE.Group(); g.userData.eq = id; scene.add(g); OBJ[id] = g; return g; }
function bld(p, w, h, d, x, z) {   // 레퍼런스의 건물 — 흰 벽 + 파란 지붕 띠 + 창
  box(p, w, h, d, M.wall, x, 0, z); box(p, w + .5, .5, d + .5, M.accent, x, h, z);
  for (let i = 0; i < Math.max(1, Math.floor(h / 3.4)); i++) { const y = 1.4 + i * 3.2; if (y + 1 > h) break;
    box(p, w * .78, .9, .08, M.glass, x, y, z + d / 2 + .05); box(p, .08, .9, d * .7, M.glass, x + w / 2 + .05, y, z); }
}
function tree(x, z, s = 1) { const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(s); cyl(g, .25, 1.6, M.trunk, 0, 0, 0, 6);
  const t = new THREE.Mesh(new THREE.IcosahedronGeometry(1.7, 0), M.tree); t.position.y = 2.9; t.scale.y = 1.15; add(t, g); scene.add(g); }
function ring(p, r, mat, x, z, y = .09, w = .55) { const m = new THREE.Mesh(new THREE.RingGeometry(r, r + w, 48).rotateX(-Math.PI / 2), mat); m.position.set(x, y, z); m.raycast = () => {}; p.add(m); return m; }

/* 벨트 — 레퍼런스와 같은 강판 상자 + 기둥. 입자 수는 **최근 7일 물량 비율**(장식 아님) */
function conveyor(pts, n, matKey = 'lime', parent = scene, eq = null) {
  const V = pts.map((p) => new THREE.Vector3(p[0], p[1], p[2])), XA = new THREE.Vector3(1, 0, 0);
  const segs = []; let tot = 0;
  for (let i = 0; i < V.length - 1; i++) {
    const a = V[i], b = V[i + 1], dir = b.clone().sub(a), L = dir.length(); dir.normalize();
    const m = new THREE.Mesh(new THREE.BoxGeometry(L, .6, 1.4), M.steel);
    m.position.copy(a).add(b).multiplyScalar(.5); m.quaternion.setFromUnitVectors(XA, dir); add(m, parent);
    if (eq) m.userData.eq = eq;
    const k = Math.floor(L / 7);
    for (let s = 1; s <= k; s++) { const q = a.clone().lerp(b, s / (k + 1)); if (q.y > 1.2) box(parent, .35, q.y - .3, .35, M.steelD, q.x, 0, q.z); }
    segs.push(L); tot += L;
  }
  const parts = [];
  for (let i = 0; i < n; i++) { const m = new THREE.Mesh(new THREE.BoxGeometry(.8, .45, .9), M[matKey]); add(m, parent, false); m.raycast = () => {}; parts.push({m, t: i / n}); }
  FLOWS.push({V, segs, tot, parts});
}
function along(f, d) { let i = 0; while (i < f.segs.length - 1 && d > f.segs[i]) { d -= f.segs[i]; i++; } return f.V[i].clone().lerp(f.V[i + 1], clamp(d / f.segs[i], 0, 1)); }
// 입자 수: 가장 큰 흐름 = 14개. 물량이 있으면 최소 2개, 없으면 0 (멈춘 벨트로 보인다)
const MAXT = Math.max(1, ...P.routes.map((r) => r.ton7 || 0), ...P.lines.map((l) => P.osp[l].in7 || 0), P.lslag.ton7 || 0);
const nParts = (t) => !t ? 0 : clamp(Math.round(14 * t / MAXT), 2, 14);

function buildScene() {
  // 바닥 · 부지 · 길
  const g0 = new THREE.Mesh(new THREE.PlaneGeometry(700, 700), M.ground); g0.rotation.x = -Math.PI / 2; g0.receiveShadow = true; scene.add(g0);
  flat(210, 96, M.pad, -26, -12, .01);
  seg(-108, -42, -108, 22, 5, M.dirt, .045);                          // 광산 운반로
  Object.keys(P.quarries).forEach((q) => seg(-116, QZ[q] ?? 0, -108, QZ[q] ?? 0, 4, M.dirt, .046));
  seg(-108, 2, -101, 2, 4, M.dirt, .046); seg(-108, -12, -101, -12, 4, M.dirt, .046);
  seg(-128, 34, 78, 34, 7, M.road, .04); for (let x = -124; x < 78; x += 8) flat(3.4, .25, M.mark, x, 34, .08);
  seg(-40, -30, -40, -44, 4, M.dirt, .045);                           // OSP 기존 → L-Slag 적치장
  [[-76, 24, 22, 12], [-6, -40, 24, 10], [40, -38, 20, 10], [-110, -50, 18, 10]].forEach((a) => flat(a[2], a[3], M.grass, a[0], a[1], .035));
  [[-130, -44], [-126, 28], [-100, 28], [-64, 28], [-30, 28], [6, 28], [44, 28], [70, -36], [-4, -46], [30, -46], [-118, -52], [-80, -48]].forEach(([x, z], i) => tree(x, z, .8 + (i % 3) * .18));

  // 01 광산 — 층진 채굴장 + 적재기
  Object.values(P.quarries).forEach((q) => {
    const id = 'Q' + q.id, g = grp(id), z = QZ[q.id] ?? 0, cx = X.qry;
    [[16, 13], [12, 10], [8, 7], [4.5, 4]].forEach(([w, d], i) => box(g, w, 2.4, d, i % 2 ? M.rock2 : M.rock, cx - i * 1.2, i * 2.4, z - i * .5));
    box(g, 2.4, 1.3, 3, M.ylw, cx + 9.5, 0, z); box(g, 2, 1.5, 1.9, M.ylw, cx + 9.5, 1.3, z - .4);
    const arm = box(g, .45, .45, 3.8, M.ylw, cx + 9.5, 2.4, z + 1.9); arm.rotation.x = .35;
    ANCHOR[id] = new THREE.Vector3(cx - 2, 11, z);
  });
  // 02 크러셔 G/C · H/C
  [['GC', 2], ['HC', -12]].forEach(([id, z]) => { const g = grp(id); bld(g, 8, 7, 8, X.cr, z);
    const h = new THREE.Mesh(new THREE.CylinderGeometry(2.6, 1, 2.6, 4, 1), M.steel); h.rotation.y = Math.PI / 4; h.position.set(X.cr - 5.4, 5, z); add(h, g);
    box(g, 1.6, 3.6, 1.6, M.steelD, X.cr - 5.4, 0, z); ANCHOR[id] = new THREE.Vector3(X.cr, 9, z); });
  // 03 수항(사일로) — 재고를 측정하지 않으므로 채움 높이를 그리지 않는다
  { const g = grp('SURGE'); cyl(g, 4, 12, M.wall, X.surge, 0, -5); cyl(g, 4.06, .45, M.accent, X.surge, 5.5, -5); cyl(g, .9, 1.6, M.accent, X.surge, 12, -5, 24, 4);
    ANCHOR.SURGE = new THREE.Vector3(X.surge, 15, -5); }
  // 분배 탑
  box(scene, 3, 9, 3, M.steel, X.tower, 0, -5); box(scene, 3.4, .5, 3.4, M.accent, X.tower, 9, -5);

  // 04 OSP 기존·신설 — 구역(5 간격) 더미. 높이 = **흐름에서 복원한 추정 재고**, 바닥 띠 = 구역 품위 상태
  [OLD, NEW].forEach((ln) => {
    const o = P.osp[ln], g = grp('OSP' + ln), z = Z[ln], len = X.osp1 - X.osp0;
    box(g, len + 2, .5, 11, M.conc, (X.osp0 + X.osp1) / 2, 0, z);
    const tmax = Math.max(1, ...P.lines.flatMap((l) => P.osp[l].zones.map((q) => q.t || 0)));
    o.zones.forEach((q) => {
      if (!q.t || q.t <= 0) return;
      const k = Math.sqrt(q.t / tmax), r = 1.1 + 2.3 * k, h = 1.4 + 6.2 * k, x = zoneX(q.z);
      const c = new THREE.Mesh(new THREE.ConeGeometry(r, h, 24), M.lime); c.position.set(x, .5 + h / 2, z); add(c, g);
      ring(g, r + .15, M['st_' + q.st] || M.st_none, x, z, .56, .45);
    });
    ANCHOR['OSP' + ln] = new THREE.Vector3((X.osp0 + X.osp1) / 2, 10, z);
    // P/W(패들휠) — 최근 24시간 안에 인출이 있었을 때만 돈다
    const gp = grp('PW' + ln); box(gp, 3.4, 1.1, 2.4, M.steelD, X.pw, 0, z); box(gp, 3.5, .25, 2.5, M.accent, X.pw, 1.1, z);
    const wh = new THREE.Group(); wh.position.set(X.pw - 1.6, 1.55, z); gp.add(wh);
    add(new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.25, .22, 24), M.steel), wh); add(new THREE.Mesh(new THREE.CylinderGeometry(.35, .35, .7, 12), M.steelD), wh);
    for (let k = 0; k < 8; k++) { const a = k * Math.PI / 4, pd = new THREE.Mesh(new THREE.BoxGeometry(.95, .55, .16), M.accent); pd.position.set(Math.cos(a) * 1.25, 0, Math.sin(a) * 1.25); pd.rotation.y = -a; add(pd, wh); }
    WHEELS.push({wh, on: o.pw_active}); ANCHOR['PW' + ln] = new THREE.Vector3(X.pw, 5, z);
  });
  // L-Slag 적치장 — 별도 용도(사용자 확정 2026-11-23): 야드로 가지 않는다
  { const g = grp('LSLAG'); box(g, 16, .4, 9, M.conc, -40, 0, -48);
    const p = new THREE.Mesh(new THREE.ConeGeometry(3.2, 4.4, 20), M.slag); p.scale.set(1.9, 1, 1); p.position.set(-40, 2.6, -48); add(p, g);
    ANCHOR.LSLAG = new THREE.Vector3(-40, 7, -48); }

  // 05 분석기 + 프리블렌딩 야드(기존 45Q · 신설 CNA) — 바닥 띠 = 최신 CaO 상태
  [OLD, NEW].forEach((ln) => {
    const y = P.yards[ln], g = grp('YD' + ln), z = Z[ln];
    bld(g, 5, 4, 5, X.an, z + 3.6);                                    // 분석기실
    box(g, 2.4, 1.4, 2.4, M.accent, X.an, 4.2, z);                     // 벨트 위 분석기
    flat(32, 9.4, M.conc, X.yard, z, .06);
    const pile = new THREE.Mesh(new THREE.ConeGeometry(3.8, 5.2, 24), M.lime); pile.scale.set(3.6, 1, 1); pile.position.set(X.yard, 2.6, z); add(pile, g);
    // 상태 띠 — 받침(32×9.4) 둘레의 얇은 테두리. 큰 원은 지도를 덮어 버린다
    const sm = M['st_' + y.st] || M.st_none;
    [[32.6, .5, 0, 4.95], [32.6, .5, 0, -4.95], [.5, 10.4, 16.05, 0], [.5, 10.4, -16.05, 0]].forEach(([w, d, dx, dz]) => {
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, .14, d), sm); b.position.set(X.yard + dx, .12, z + dz); b.raycast = () => {}; g.add(b); });
    const st = new THREE.Group(); g.add(st); box(st, .8, 6.6, .8, M.steelD, X.yard - 10, 0, z - 5); const bm = box(st, .7, .7, 6, M.accent, X.yard - 10, 6.2, z - 2.4); bm.rotation.x = .18;
    ANCHOR['YD' + ln] = new THREE.Vector3(X.yard, 9, z);
    // 킬른 — 이 시스템 범위 밖(흐릿하게, 자료 없음)
    const gk = grp('KL' + ln), kz = z;
    const k = new THREE.Mesh(new THREE.CylinderGeometry(1.8, 1.8, 18, 28).rotateZ(Math.PI / 2), M.ghost); k.position.set(X.kiln, 2.8, kz); k.rotation.y = .05; add(k, gk, false);
    cyl(gk, 2.4, .6, M.ghost, X.kiln - 7, 0, kz, 20); cyl(gk, 2.4, .6, M.ghost, X.kiln + 7, 0, kz, 20); ANCHOR['KL' + ln] = new THREE.Vector3(X.kiln, 6.5, kz);
  });

  // 벨트 — 입자 수 = 최근 7일 물량
  const route = (s, d) => P.routes.find((r) => r.src === s && r.dest === d) || {ton7: 0};
  conveyor([[X.cr + 4, 1.2, 2], [X.surge - 4, 9, -3]], nParts(P.osp[OLD].in7 + P.osp[NEW].in7), 'lime');
  conveyor([[X.cr + 4, 1.2, -12], [X.surge - 4, 9, -7]], nParts(P.osp[OLD].in7 + P.osp[NEW].in7) >> 1, 'lime');
  conveyor([[X.surge + 4, 1.4, -5], [X.tower - 1.5, 8.6, -5]], nParts(P.osp[OLD].in7 + P.osp[NEW].in7), 'lime');
  [OLD, NEW].forEach((ln) => conveyor([[X.tower + 1.5, 8.6, -5], [X.osp0 + 3, 10.2, Z[ln] + Math.sign(-5 - Z[ln]) * 3]], nParts(P.osp[ln].in7), 'lime', scene, 'OSP' + ln));
  conveyor([[X.pw + 1.5, 1.2, Z[OLD]], [X.pw + 5, 5.4, Z[OLD]], [X.yard - 12, 5.4, Z[OLD]]], nParts(route(OLD, OLD).ton7), 'lime', scene, `R${OLD}${OLD}`);
  conveyor([[X.pw + 1.5, 1.2, Z[NEW]], [X.pw + 5, 5.4, Z[NEW]], [X.yard - 12, 5.4, Z[NEW]]], nParts(route(NEW, NEW).ton7), 'lime', scene, `R${NEW}${NEW}`);
  // 교차인출: 기존 OSP → 신설 야드 (높게 건너간다)
  conveyor([[X.pw + 1, 1.2, Z[OLD] + 2.6], [X.pw + 8, 9, Z[OLD] + 6], [-12, 9, Z[NEW] - 7], [-6, 5.6, Z[NEW] - .6]], nParts(route(OLD, NEW).ton7), 'lime', scene, `R${OLD}${NEW}`);
  // L-Slag 적치장으로 (야드가 아님)
  conveyor([[-40, 1.2, Z[OLD] - 6.4], [-40, 4.2, -40]], nParts(P.lslag.ton7), 'slag', scene, 'LSLAG');

  selRing = new THREE.Mesh(new THREE.RingGeometry(1, 1.25, 64).rotateX(-Math.PI / 2), M.sel); selRing.visible = false; selRing.raycast = () => {}; scene.add(selRing);
}

/* ── 카메라(레퍼런스와 같은 궤도식) ───────────────────────────── */
const TABS = [
  {id: 'all', name: '전체 공정', b: [-132, 72, -54, 30]},
  {id: 'mine', name: '광산·크러셔', b: [-132, -70, -40, 18]},
  {id: 'osp', name: 'OSP·L-Slag', b: [-66, -14, -54, 22]},
  {id: 'yard', name: '야드·분석기', b: [-14, 72, -30, 24]},
];
let curTab = 'all';
function homeView(tab = curTab) {
  // 레퍼런스(공정 지도)와 같은 맞춤: 경계 상자를 화면 축에 투영해, 위 카드·아래 카드·오른쪽 패널을 뺀
  // **빈자리**에 들어가는 거리를 구하고, 그 빈자리 한가운데로 장면을 옮긴다.
  const t = TABS.find((x) => x.id === tab) || TABS[0], st = $('m3stage');
  // 휴대폰(세로 화면)은 흐름이 위→아래로 흐르게 돌려 본다(광산이 위, 야드가 아래)
  const asp = st.clientWidth / Math.max(1, st.clientHeight), m = isMobile(), th = m ? 1.32 : .62, ph = .94, tn = Math.tan(16 * Math.PI / 180);
  const r = [Math.cos(th), -Math.sin(th)], f = [-Math.sin(th), -Math.cos(th)];
  let r0 = 1e9, r1 = -1e9, f0 = 1e9, f1 = -1e9;
  for (const x of [t.b[0], t.b[1]]) for (const z of [t.b[2], t.b[3]]) { const pr = x * r[0] + z * r[1], pf = x * f[0] + z * f[1];
    r0 = Math.min(r0, pr); r1 = Math.max(r1, pr); f0 = Math.min(f0, pf); f1 = Math.max(f1, pf); }
  const m3 = $('m3'), panels = !m && !m3.classList.contains('nopanels'), detail = !m && !m3.classList.contains('nodetail');
  // 휴대폰: 위 탭+지표 줄이 화면의 약 1/3 을 차지한다
  const top = m ? .31 : .27, bot = m ? .02 : panels && innerWidth > 1180 ? .21 : .03, side = detail ? .27 : (m ? 0 : .02);
  const W = (r1 - r0) / 2, H = (f1 - f0) / 2 * Math.cos(ph) + 15 * Math.sin(ph) * .5;
  const d = clamp(Math.max(H / (tn * (1 - top - bot)), W / (tn * asp * (1 - side))) * (m ? 1.0 : .9), 50, 460);
  const up = d * tn * (top - bot) / Math.cos(ph) * .9, rt = d * tn * asp * side;
  const cr = (r0 + r1) / 2 + rt, cf = (f0 + f1) / 2 + up;
  return {tx: cr * r[0] + cf * f[0], tz: cr * r[1] + cf * f[1], theta: th, phi: ph, dist: d};
}
function applyCam() { const sp = Math.sin(cam.phi); camera.position.set(cam.tx + cam.dist * sp * Math.sin(cam.theta), cam.dist * Math.cos(cam.phi), cam.tz + cam.dist * sp * Math.cos(cam.theta)); camera.lookAt(cam.tx, 0, cam.tz); }
function panBy(dx, dy) { const st = $('m3stage'); const sc = cam.dist * 2 * Math.tan(camera.fov * Math.PI / 360) / st.clientHeight;
  const rx = Math.cos(cam.theta), rz = -Math.sin(cam.theta), fx = -Math.sin(cam.theta), fz = -Math.cos(cam.theta), k = sc / Math.cos(cam.phi);
  goal.tx = clamp(goal.tx - rx * dx * sc + fx * dy * k, -180, 120); goal.tz = clamp(goal.tz - rz * dx * sc + fz * dy * k, -110, 80); cam.tx = goal.tx; cam.tz = goal.tz; }
const zoomBy = (f) => { goal.dist = clamp(goal.dist * f, 30, 480); };
const flyTo = (x, z, d) => { goal.tx = x; goal.tz = z; if (d) goal.dist = d; if (REDUCED) Object.assign(cam, goal); };

function setupControls() {
  const st = $('m3stage'); const pts = new Map(); let mode = null, moved = 0, last = null, pinch = null;
  st.addEventListener('contextmenu', (e) => e.preventDefault());
  st.addEventListener('pointerdown', (e) => { st.setPointerCapture(e.pointerId); pts.set(e.pointerId, {x: e.clientX, y: e.clientY}); moved = 0; last = {x: e.clientX, y: e.clientY};
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), ang: Math.atan2(b.y - a.y, b.x - a.x), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2}; mode = 'pinch'; }
    else mode = (e.button === 2 || e.shiftKey || e.ctrlKey) ? 'rot' : 'pan';
    st.classList.add('drag'); hideHint(); });
  st.addEventListener('pointermove', (e) => {
    if (!pts.has(e.pointerId)) { hover(e); return; }
    pts.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (mode === 'pinch' && pts.size === 2) { const [a, b] = [...pts.values()]; const d = Math.hypot(a.x - b.x, a.y - b.y), ang = Math.atan2(b.y - a.y, b.x - a.x), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      goal.dist = clamp(goal.dist * pinch.d / d, 30, 480); cam.dist = goal.dist; goal.theta -= (ang - pinch.ang); cam.theta = goal.theta; panBy(mx - pinch.mx, my - pinch.my); pinch = {d, ang, mx, my}; moved += 10; return; }
    const dx = e.clientX - last.x, dy = e.clientY - last.y; last = {x: e.clientX, y: e.clientY}; moved += Math.abs(dx) + Math.abs(dy);
    if (mode === 'pan') panBy(dx, dy);
    else if (mode === 'rot') { goal.theta -= dx * .006; goal.phi = clamp(goal.phi - dy * .004, .45, 1.25); cam.theta = goal.theta; cam.phi = goal.phi; }
  });
  const up = (e) => { if (!pts.has(e.pointerId)) return; pts.delete(e.pointerId);
    if (pts.size === 0) { st.classList.remove('drag'); if (moved < 6 && mode !== 'pinch') pick(e); mode = null; }
    else if (pts.size === 1) { mode = 'pan'; last = [...pts.values()][0]; } };
  st.addEventListener('pointerup', up); st.addEventListener('pointercancel', up);
  st.addEventListener('wheel', (e) => { e.preventDefault(); zoomBy(Math.exp(e.deltaY * .0012)); hideHint(); }, {passive: false});
  st.addEventListener('keydown', (e) => { const k = e.key;
    if (k === 'ArrowLeft') panBy(40, 0); else if (k === 'ArrowRight') panBy(-40, 0); else if (k === 'ArrowUp') panBy(0, 40); else if (k === 'ArrowDown') panBy(0, -40);
    else if (k === '+' || k === '=') zoomBy(.8); else if (k === '-') zoomBy(1.25); else if (k === 'Escape') select(null); });
  document.querySelectorAll('[data-cam]').forEach((b) => b.addEventListener('click', () => { const c = b.dataset.cam;
    if (c === 'in') zoomBy(.75); else if (c === 'out') zoomBy(1.33); else if (c === 'rl') goal.theta += .35; else if (c === 'rr') goal.theta -= .35;
    else if (c === 'home') Object.assign(goal, homeView()); if (REDUCED) Object.assign(cam, goal); }));
}
function eqAt(e) {
  const r = $('m3stage').getBoundingClientRect();
  pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(Object.values(OBJ).concat(scene.children.filter((c) => c.userData.eq)), true);
  for (const h of hits) { let o = h.object; while (o) { if (o.userData && o.userData.eq) return o.userData.eq; o = o.parent; } }
  return null;
}
let hovered = null;
function hover(e) { if (!THREEOK) return; const id = eqAt(e); if (id !== hovered) { hovered = id; $('m3stage').classList.toggle('hover', !!id); } }
function pick(e) { if (!THREEOK) return; const id = eqAt(e); select(id ? E[id] : null, {fly: false}); }

/* ── 이름표 ─────────────────────────────────────────────────── */
const TAG = {};
function buildTags() {
  const wrap = $('m3tags');
  EQ.forEach((e) => { const b = document.createElement('button'); b.type = 'button';
    b.innerHTML = `${e.route || e.ghost ? '' : '<i></i>'}<span>${esc(e.name)}</span><small></small>`;
    b.addEventListener('click', () => select(e, {fly: true})); wrap.appendChild(b); TAG[e.id] = b;
    if (!ANCHOR[e.id]) ANCHOR[e.id] = new THREE.Vector3(e.x, e.y, e.z); });
  updateTags();
}
function updateTags() {
  const m = isMobile();
  EQ.forEach((e) => { const b = TAG[e.id]; if (!b) return; const on = sel && sel.id === e.id;
    b.className = 'm3-tag s-' + e.st + (e.route ? ' route' : '') + (e.ghost ? ' ghost' : '') + (e.mini || e.route || e.ghost ? ' mini' : '') + (on ? ' sel' : '');
    b.querySelector('small').textContent = e.sub || '';
    // 전체 보기에서는 큰 설비 이름표만 — 작은 이름표(P/W·벨트·킬른)는 그 탭이나 가까이 볼 때만(레퍼런스와 같은 규칙)
    const small = e.mini || e.route || e.ghost, near = cam.dist < NEAR;
    const show = on || (m ? (e.major || e.st === 'bad' || e.st === 'warn') : (!small || curTab !== 'all' || near));
    b.dataset.hide = show ? '' : '1'; });
}
const _v = THREEOK ? new THREE.Vector3() : null;
function placeTags() {
  const st = $('m3stage'), w = st.clientWidth, h = st.clientHeight, rects = [];
  EQ.forEach((e) => { const el = TAG[e.id]; if (!el) return;
    if (el.dataset.hide === '1') { el.style.display = 'none'; return; }
    _v.copy(ANCHOR[e.id]).project(camera);
    if (_v.z > 1 || _v.x < -1.1 || _v.x > 1.1 || _v.y < -1.1 || _v.y > 1.1) { el.style.display = 'none'; return; }
    let px = (_v.x + 1) / 2 * w, py = (1 - _v.y) / 2 * h; el.style.display = '';
    if (!el._w) { el._w = el.offsetWidth; el._h = el.offsetHeight; }
    // 겹치면 위·아래로 비켜 앉힌다(레퍼런스와 같은 방식)
    const r0 = {l: px - el._w / 2, r: px + el._w / 2, t: py - el._h, b: py}, hh = el._h + 4;
    const ov = (r, c) => Math.max(0, Math.min(r.r, c.r + 4) - Math.max(r.l, c.l - 4)) * Math.max(0, Math.min(r.b, c.b + 3) - Math.max(r.t, c.t - 3));
    let best = 0, bestA = 1e9;
    for (const dy of [0, -hh, hh, -2 * hh, 2 * hh]) { const r = {l: r0.l, r: r0.r, t: r0.t + dy, b: r0.b + dy}, A = rects.reduce((a, c) => a + ov(r, c), 0); if (A < bestA) { bestA = A; best = dy; } if (!A) break; }
    rects.push({l: r0.l, r: r0.r, t: r0.t + best, b: r0.b + best});
    el.style.transform = `translate(${px.toFixed(1)}px,${(py + best).toFixed(1)}px) translate(-50%,-100%)`; });
}

/* ══ 오버레이 ═════════════════════════════════════════════════ */
function spark(pts, opt = {}) {
  const v = pts.filter((p) => p.v != null); if (v.length < 2) return '<p class="m3-note">표시할 기간 자료가 없습니다.</p>';
  const W = 320, H = 70, pl = 4, pr = W - 4, pt = 6, pb = H - 6;
  let lo = Math.min(...v.map((p) => p.v)), hi = Math.max(...v.map((p) => p.v));
  if (opt.band) { lo = Math.min(lo, opt.band[0]); hi = Math.max(hi, opt.band[1]); }
  const pad = (hi - lo) * .08 || 1; lo -= pad; hi += pad;
  const X = (i) => pl + (pr - pl) * i / (v.length - 1), Y = (y) => pb - (y - lo) / (hi - lo) * (pb - pt);
  let s = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(opt.label || '추이')}">`;
  if (opt.band) s += `<rect x="${pl}" width="${pr - pl}" y="${Y(opt.band[1]).toFixed(1)}" height="${(Y(opt.band[0]) - Y(opt.band[1])).toFixed(1)}" rx="4" fill="var(--band)"/>`;
  const line = v.map((p, i) => `${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(' ');
  s += `<polygon points="${pl},${pb} ${line} ${pr},${pb}" fill="var(--primary)" opacity=".08"/>`;
  s += `<polyline points="${line}" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;
  const e = v[v.length - 1]; s += `<circle cx="${X(v.length - 1).toFixed(1)}" cy="${Y(e.v).toFixed(1)}" r="3.5" fill="var(--primary)" stroke="var(--surface)" stroke-width="1.5"/>`;
  return s + '</svg>';
}
const kvs = (rows) => '<dl class="m3-kv">' + rows.filter(Boolean).map(([k, v, u]) => `<div><dt>${esc(k)}</dt><dd>${v}${u ? `<small>${esc(u)}</small>` : ''}</dd></div>`).join('') + '</dl>';
const badge = (st, txt) => `<span class="m3-badge s-${st}">${esc(txt || ST_TXT[st] || '')}</span>`;
const head = (e, eb, sub) => `<div class="m3-dh"><span class="m3-dic">${svgI(e.icon)}</span><div style="min-width:0"><div class="m3-eb">${esc(eb)}</div>` +
  `<div class="m3-dn">${esc(e.name)}</div>${sub ? `<div class="m3-ds">${sub}</div>` : ''}</div>` +
  `<button class="m3-x" type="button" id="m3close" aria-label="닫기"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div>`;

function detailHTML(e) {
  const W7 = `${P.win_from} ~ ${P.data_end.slice(5)}`;
  if (!e) {
    return `<div class="m3-dh"><span class="m3-dic">${svgI('layers')}</span><div><div class="m3-eb">석회석 광산 → OSP → 야드</div><div class="m3-dn">설비를 눌러 보세요</div>` +
      `<div class="m3-ds">지도 위 설비나 이름표를 누르면 그 설비의 실측 값이 여기에 나옵니다.</div></div></div>` +
      `<p class="m3-note">벨트 위 덩어리 수는 <b>최근 7일 물량</b>에 비례합니다(${esc(W7)}). 물량이 없던 벨트는 비어 있습니다. ` +
      `OSP 더미 높이는 <b>흐름에서 복원한 구역 추정 재고</b>, 바닥 띠 색은 품위 상태(목표 ${P.target}±${P.tol}%)입니다.</p>` +
      `<p class="m3-note">수항 재고·구역 재고·크러셔별 물량은 <b>측정하지 않는 값</b>이라 지도에 지어 그리지 않았습니다.</p>`;
  }
  if (e.kind === 'qry') { const q = e.q;
    return head(e, '01 광산', `마지막 기록 ${esc(q.last || '—')}`) + `<div class="m3-row">${badge('info', `최근 7일 ${q.n7}교대`)}</div>` +
      kvs([['적재(이송) 물량', nf(q.ton7), 't'], [`→ ${OLD} 라인`, nf(q.lines[OLD]), 't'], [`→ ${NEW} 라인`, nf(q.lines[NEW]), 't'],
           ['CaO (물량 가중)', nf(q.cao7, 2), '%'], ['MgO (물량 가중)', nf(q.mgo7, 2), '%']]) +
      `<div class="m3-sec">일별 CaO <small>최근 45일 · 물량 가중</small></div><div class="m3-spark">${spark(q.daily, {label: 'CaO'})}</div>` +
      `<p class="m3-note">기간 ${esc(W7)}. 원본 시트 <b>광산(${esc(q.id)})</b>의 이송물량·품위입니다.</p>`; }
  if (e.kind === 'cr') { const c = P.crushers;
    return head(e, '02 크러셔', '') + kvs([['G/C 단독', c.gc_only, '교대'], ['H/C 단독', c.hc_only, '교대'], ['G/C·H/C 병행', c.both, '교대']]) +
      `<p class="m3-note">광산 기록은 <b>교대 단위</b>이고 병행 교대의 물량을 크러셔별로 나눈 기록이 없어, 물량을 나누지 않고 <b>교대 수</b>만 셉니다(${esc(W7)}).</p>`; }
  if (e.kind === 'surge') { const s = P.surge, c = s.last_cycle;
    return head(e, '03 수항(사일로)', `용량 ${nf(s.cap)}t`) + `<div class="m3-row">${badge(e.st, e.st === 'warn' ? '고갈 기록 빠진 것으로 보임' : '정상')}</div>` +
      kvs([['마지막 \'고갈\' 기록', esc(s.last_empty || '—')], ['그 뒤 채움', `${nf(s.open_fill)}`, `t · ${s.open_n}회`],
           c && ['최근 닫힌 사이클', `${esc(c.start)} → ${esc(c.end)}`], c && ['그 사이클 채움 · 순간 최대', `${nf(c.fill)} · ${nf(c.peak)}`, 't']]) +
      `<p class="m3-note">수항 재고는 <b>측정하지 않습니다.</b> '고갈' 기록(재고≈0) 사이의 채움 합만 알 수 있어, 채움 높이를 그리지 않았습니다.` +
      (e.st === 'warn' ? ` 마지막 고갈 뒤 채움이 <b>용량의 ${nf(s.open_fill / s.cap, 1)}배</b>라, 그 사이 <b>기록되지 않은 고갈</b>이 있었던 것으로 보입니다(현장 문의 대상).` : '') + '</p>'; }
  if (e.kind === 'osp') { const o = e.o;
    const zs = o.zones.filter((z) => z.t > 0).map((z) => `<div class="m3-zone s-${z.st}"><small>${z.z}번</small><b>${nf(z.cao, 1)}%</b><small>${nf(z.t)}t</small></div>`).join('');
    return head(e, '04 OSP 적치장', `실사 ${esc(o.stock_at || '—')} · 용량 ${nf(o.cap)}t`) + `<div class="m3-row">${badge(e.st, e.st === 'warn' ? (o.pct >= 90 ? '만실 가까움' : '재고 적음') : '정상')}</div>` +
      kvs([['재고(실사)', nf(o.stock), `t · ${nf(o.pct)}%`], ['7일 변화', o.chg7 == null ? '—' : (o.chg7 > 0 ? '+' : '') + nf(o.chg7), 't'],
           ['7일 적재(광산→)', nf(o.in7), 't'], ['7일 인출(→)', nf(o.out7), 't'], ['마지막 인출', esc(o.last_out || '—')]]) +
      `<div class="m3-sec">실사 재고 <small>최근 60회</small></div><div class="m3-spark">${spark(o.stock_daily, {label: '재고'})}</div>` +
      `<div class="m3-sec">구역 추정 재고 · 품위 <small>${esc(o.zone_at || '')} 기준 · 추정</small></div><div class="m3-zones">${zs || '<p class="m3-note">추정 구역이 없습니다.</p>'}</div>` +
      `<p class="m3-note">구역 재고는 <b>측정값이 아니라</b> 적재−인출 흐름에서 복원한 추정입니다(현장은 구역별 재고를 측정하지 않음). 7일 인출에는 L-Slag 적치장으로 간 물량도 들어 있습니다.</p>`; }
  if (e.kind === 'pw') { const o = e.o;
    return head(e, '04 인출 P/W', '') + `<div class="m3-row">${badge(o.pw_active ? 'ok' : 'none', o.pw_active ? '최근 24시간 안 인출' : '최근 24시간 인출 기록 없음')}</div>` +
      kvs([['마지막 인출', esc(o.last_out || '—')], ['7일 인출', nf(o.out7), 't']]) +
      `<p class="m3-note">패들휠은 자료 마지막 시각(${esc(P.data_end)}) 기준 24시간 안에 인출 기록이 있을 때만 돕니다.</p>`; }
  if (e.kind === 'lslag') { const l = P.lslag;
    return head(e, '별도 용도', `${esc(l.first || '—')} 부터`) + `<div class="m3-row">${badge('info', '야드로 가지 않음')}</div>` +
      kvs([['누적', nf(l.ton), `t · ${l.n}건`], ['최근 7일', nf(l.ton7), 't'], ['마지막', esc(l.last || '—')]]) +
      `<p class="m3-note">기존 OSP 에서 인출해 <b>별도의 L-Slag 적치장</b>으로 이송합니다(현장 확정 2026-11-23). OSP 재고에서는 빠지지만 <b>야드 품위 매칭에서는 제외</b>합니다.</p>`; }
  if (e.kind === 'route') { const r = e.r;
    return head(e, '벨트 · 운반 경로', '') + `<div class="m3-row">${badge('info', r.field ? '운반 시간 현장 확정' : '운반 시간 데이터 추정')}</div>` +
      kvs([['운반 시간', `${r.lag}`, '시간'], ['상류↔야드 일치도', r.corr == null ? '—' : (r.corr > 0 ? '+' : '') + nf(r.corr, 2)],
           ['최근 7일 물량', nf(r.ton7), 't'], ['전 기간 물량', nf(r.ton), 't']]) +
      `<p class="m3-note">${r.src !== r.dest ? '기존 OSP 에서 뽑아 <b>신설 야드</b>로 보내는 교차인출입니다. 재고는 기존에서, 품위는 신설 야드로 귀속합니다. ' : ''}` +
      (r.field ? '운반 시간은 현장이 알려 준 값이며, 일치도는 그 시간에서 계산했습니다.' : '운반 시간은 상관이 가장 높은 지연으로 데이터에서 추정했습니다.') + '</p>'; }
  if (e.kind === 'yard') { const y = e.y;
    return head(e, '05 프리블렌딩 야드', `${esc(y.alias)} · 마지막 측정 ${esc(y.last_at || '—')}`) +
      `<div class="m3-row">${badge(y.st, y.st === 'ok' ? '규격 안' : y.st === 'warn' ? '규격 가까이' : y.st === 'bad' ? '규격 밖' : '자료 없음')}${y.age_h != null && y.age_h > 24 ? badge('none', `${nf(y.age_h, 0)}시간째 새 자료 없음`) : ''}</div>` +
      kvs([['최신 CaO', nf(y.last_cao, 2), '%'], ['7일 평균', nf(y.w_mean, 2), '%'], ['7일 편차', nf(y.w_std, 2), '%p'], ['7일 규격 안', nf(y.w_ok), '%']]) +
      `<div class="m3-sec">일별 CaO <small>최근 45일 · 띠 = 목표 ${P.target}±${P.tol}</small></div><div class="m3-spark">${spark(y.daily, {band: [P.target - P.tol, P.target + P.tol], label: 'CaO'})}</div>` +
      `<p class="m3-note">${esc(y.analyzer)} 분석기 실측입니다. 품위 예측·처방은 운영 현황판·배합 처방에서 봅니다.</p>`; }
  if (e.kind === 'kiln') return head(e, '이 시스템 범위 밖', '') + '<p class="m3-note">킬른은 이 추적 시스템의 범위 밖이라 자료를 싣지 않았습니다. 야드까지가 이 지도의 끝입니다.</p>';
  return '';
}

let sel = null;
function select(e, o = {}) {
  sel = e || null; $('m3').classList.toggle('nodetail', !sel && isMobile());
  $('m3detail').innerHTML = detailHTML(sel);
  const c = $('m3close'); if (c) c.onclick = () => select(null);
  if (THREEOK && selRing) {
    if (sel) { const a = ANCHOR[sel.id]; selRing.position.set(a.x, .14, a.z); const s = sel.kind === 'osp' ? 15 : sel.kind === 'yard' ? 14 : sel.kind === 'qry' ? 9 : sel.kind === 'route' ? 3 : 5; selRing.scale.setScalar(s); selRing.visible = true;
      if (o.fly) flyTo(a.x + (isMobile() ? 0 : 14), a.z, Math.min(goal.dist, 150)); }
    else selRing.visible = false;
  }
  updateTags();
}

function kpis() {
  const c = P.chain, yo = P.yards[OLD], yn = P.yards[NEW], so = P.osp[OLD], sn = P.osp[NEW];
  const tot = (so.stock || 0) + (sn.stock || 0), cap = (so.cap || 0) + (sn.cap || 0);
  const card = (id, st, kl, kv, u, ks) => `<button type="button" class="m3-kpi s-${st}" data-go="${id}"><div class="kl"><i></i>${esc(kl)}</div>` +
    `<div class="kv">${kv}<small>${esc(u)}</small></div><div class="ks">${ks}</div></button>`;
  $('m3kpis').innerHTML =
    card('', c.pct >= 95 ? 'ok' : c.pct >= 85 ? 'warn' : 'bad', '추적 연결', nf(c.pct, 1), '%', `야드로 간 물량 중 · ${nf(c.ton)}t`) +
    card('YD' + OLD, yo.st, `${yo.analyzer} 야드 최신`, nf(yo.last_cao, 2), '%', `${esc(yo.last_at || '—')} · 7일 규격 안 ${nf(yo.w_ok)}%`) +
    card('YD' + NEW, yn.st, `${yn.analyzer} 야드 최신`, nf(yn.last_cao, 2), '%', `${esc(yn.last_at || '—')} · 7일 규격 안 ${nf(yn.w_ok)}%`) +
    card('OSP' + OLD, ospSt(so) === 'ok' && ospSt(sn) === 'ok' ? 'ok' : 'warn', 'OSP 재고(실사)', nf(tot), 't', `${OLD} ${nf(so.pct)}% · ${NEW} ${nf(sn.pct)}% (용량 대비)`);
  $('m3kpis').querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => { const id = b.dataset.go; select(id ? E[id] : null, {fly: !!id}); }));
}
function chainCard() {
  const c = P.chain;
  $('m3chain').innerHTML = `<div class="m3-chh">추적 연결 <b>${nf(c.pct, 1)}%</b><small>광산 → OSP → 야드 · 네 이음매 · 가장 약한 곳 ${esc((c.joints.find((j) => j.key === c.weakest) || {}).name || '—')}</small></div>` +
    '<div class="m3-steps">' + c.joints.map((j, i) => `<div class="m3-step s-${chainSt(j.tone)}" title="${esc(j.why)}"><span class="sb">${i + 1}</span><b>${esc(j.name)}</b><small>${esc(j.label)}</small></div>`).join('') + '</div>';
}
let LF = 'all';
function listCard() {
  const rows = P.recent.filter((r) => LF === 'all' || (LF === 'in' ? r.kind === '적재' : r.kind.startsWith('인출')));
  $('m3list').innerHTML = `<div class="m3-lh"><b>최근 기록</b><div class="m3-seg" id="m3lf">` +
    [['all', '전체'], ['in', '적재'], ['out', '인출']].map(([k, n]) => `<button type="button" data-f="${k}" aria-pressed="${k === LF}">${n}</button>`).join('') +
    `</div><small>${nf(rows.length)}건</small></div><div class="m3-rows">` +
    rows.slice(0, 60).map((r, i) => `<button type="button" class="m3-rw" data-i="${i}"><span class="t">${esc(r.t)}</span>` +
      `<span class="m">${esc(r.kind)} · ${esc(r.line)}${r.zone == null ? '' : ` <small>${r.zone}번</small>`}</span>` +
      `<span class="v">${r.ton == null ? '물량 없음' : nf(r.ton) + 't'}${r.cao == null ? '' : ` · ${nf(r.cao, 2)}%`}</span></button>`).join('') + '</div>';
  $('m3lf').onclick = (ev) => { const b = ev.target.closest('[data-f]'); if (b) { LF = b.dataset.f; listCard(); } };
  $('m3list').querySelectorAll('.m3-rw').forEach((b) => b.addEventListener('click', () => { const r = rows[+b.dataset.i];
    const id = r.kind.includes('L-Slag') ? 'LSLAG' : 'OSP' + r.line; select(E[id], {fly: true}); }));
}
function tabs() {
  $('m3tabs').innerHTML = TABS.map((t) => `<button type="button" role="tab" data-t="${t.id}" aria-selected="${t.id === curTab}">${esc(t.name)}</button>`).join('');
  $('m3tabs').onclick = (ev) => { const b = ev.target.closest('[data-t]'); if (!b) return; curTab = b.dataset.t; tabs(); updateTags();
    if (THREEOK) { Object.assign(goal, homeView()); if (REDUCED) Object.assign(cam, goal); } };
}
let hintT; function hideHint() { const h = $('m3hint'); if (h) h.classList.add('off'); }

/* ── 시작 ─────────────────────────────────────────────────────── */
if (isMobile()) $('m3hint').textContent = '끌어서 이동 · 두 손가락으로 확대·회전 · 설비를 누르면 상세';
$('m3asof').innerHTML = `<i></i>자료 기준 <b>${esc(P.data_end)}</b> · 최근 7일 ${esc(P.win_from)}~`;
tabs(); kpis(); chainCard(); listCard(); select(null);
$('m3panels').addEventListener('click', (ev) => { const on = $('m3').classList.toggle('nopanels'); ev.currentTarget.setAttribute('aria-pressed', String(on));
  if (THREEOK && camera) { Object.assign(goal, homeView()); if (REDUCED) Object.assign(cam, goal); } });
if (isMobile()) $('m3').classList.add('nodetail');

function init() {
  const st = $('m3stage');
  if (!THREEOK) { st.innerHTML = '<div class="m3-nogl">3D 도구를 불러오지 못했습니다. 카드와 상세 패널은 그대로 쓸 수 있습니다.</div>'; return; }
  try { renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'high-performance'}); } catch (err) { renderer = null; }
  if (!renderer) { THREEOK = false; st.innerHTML = '<div class="m3-nogl">이 브라우저에서는 3D 지도를 표시할 수 없습니다.<br>카드와 상세 패널은 그대로 쓸 수 있습니다.</div>'; return; }
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  st.appendChild(renderer.domElement);
  scene = new THREE.Scene(); scene.fog = new THREE.Fog('#F2F4F6', 380, 900);
  camera = new THREE.PerspectiveCamera(32, 1, 1, 1400);
  hemi = new THREE.HemisphereLight('#FFFFFF', '#C9D3E0', .66); scene.add(hemi);
  sun = new THREE.DirectionalLight('#FFFFFF', .62); sun.position.set(-60, 130, 70); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, {left: -150, right: 150, top: 100, bottom: -100, near: 10, far: 420}); sun.shadow.bias = -.0006; sun.shadow.normalBias = .05; scene.add(sun);
  raycaster = new THREE.Raycaster(); pointer = new THREE.Vector2();
  makeMats(); buildScene(); applyPalette();
  const rs = () => { const w = st.clientWidth, h = st.clientHeight; if (!w || !h) return; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  new ResizeObserver(rs).observe(st); rs();
  Object.assign(cam, homeView()); Object.assign(goal, cam);
  setupControls(); buildTags();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyPalette);
  new MutationObserver(applyPalette).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  hintT = setTimeout(hideHint, 6000);
  requestAnimationFrame(frame);
}
let lastT = performance.now(), wasNear = null;
const NEAR = 170;
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(.05, (now - lastT) / 1000); lastT = now;
  const k = REDUCED ? 1 : 1 - Math.pow(.0015, dt);
  cam.tx += (goal.tx - cam.tx) * k; cam.tz += (goal.tz - cam.tz) * k; cam.dist += (goal.dist - cam.dist) * k; cam.theta += (goal.theta - cam.theta) * k; cam.phi += (goal.phi - cam.phi) * k;
  applyCam();
  if ((cam.dist < NEAR) !== wasNear) { wasNear = cam.dist < NEAR; updateTags(); }
  if (!REDUCED) {
    FLOWS.forEach((f) => f.parts.forEach((p) => { p.t = (p.t + dt * 5 / f.tot) % 1; const q = along(f, p.t * f.tot); p.m.position.set(q.x, q.y + .5, q.z); }));
    WHEELS.forEach((w) => { if (w.on) w.wh.rotation.y += dt * 1.4; });
    if (selRing && selRing.visible) selRing.material.opacity = .55 + .35 * Math.sin(now / 260);
  } else FLOWS.forEach((f) => f.parts.forEach((p) => { const q = along(f, p.t * f.tot); p.m.position.set(q.x, q.y + .5, q.z); }));
  renderer.render(scene, camera);
  placeTags();
}
init();
window.addEventListener('resize', () => { EQ.forEach((e) => { if (TAG[e.id]) TAG[e.id]._w = 0; }); updateTags(); });
})();
"""


def build() -> str:
    payload = build_payload()
    # `</` 를 끊어 둔다 — 비고 글자에 '</script>' 가 들어와도 문서가 깨지지 않게
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    three = THREE_JS.read_text(encoding="utf-8")
    return (
        '<!doctype html>\n<html lang="ko" translate="no">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="google" content="notranslate">\n<title>석회석 3D 공정 지도</title>\n'
        f"<style>{DOC_STYLE}{PAGE_CSS}</style>\n</head>\n<body class=\"m3page\">\n"
        + nav(active="3D 공정 지도", today=payload["data_end"][:10])
        + PAGE_HTML
        + foot("")
        + f'\n<script id="m3payload" type="application/json">{js}</script>\n'
        + f"<script>/* Three.js r149 · MIT · src/visualization/vendor */\n{three}\n</script>\n"
        + f"<script>{PAGE_JS}</script>\n</body>\n</html>\n"
    )


def main():
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = P.OUTPUTS_DIR / "map3d.html"
    doc = build()
    dst.write_text(doc, encoding="utf-8")
    print(f"[OK] 3D 공정 지도: {dst} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
