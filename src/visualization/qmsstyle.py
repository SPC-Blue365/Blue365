"""시멘트 품질관리 시스템(QMS) 스타일 [Synthesis-Agent] — **모든 산출물의 시각 체계**.

연혁
  · 2026-11-09 운영 현황판(대시보드)에 먼저 적용 — 사용자 요청 "시멘트 품질관리 시스템 프로젝트
    디자인 스타일 가져와서 적용해서 다시 정리해줘"(§6-0-30).
  · 2026-11-17 **나머지 산출물 6종 + 단일 파일 통합본까지 확산** — 사용자 요청 "나머지 산출물이랑
    통합본도 전부 QMS 스타일로 통일해줘"(§6-0-31). 옛 포털 스타일(`portalstyle.py`)은 되돌릴
    수 있도록 남겨 두되 더는 쓰지 않는다.

⭐️ 왜: 품질담당이 시멘트 QMS 현황판과 이 화면을 번갈아 본다. 생김새가 다르면 "다른 회사 보고서"
   로 읽힌다. 레퍼런스는 그 프로젝트의 아티팩트(claude.ai/artifact/1iZN1qJq7kZXkr6vPE1mTt)이며,
   주석에 자기 근거를 `docs/UI_디자인_가이드.md` 로 적어 두고 있다.

레퍼런스에서 가져온 것 — CSS 는 **원본을 그대로** 싣는다(`_REF`, 눈으로 베끼지 않는다):
  · 회색 바탕(#f2f4f6) + 흰 카드(radius 20px) + 파란 강조 한 색(#3182f6) — 토스식 한국 앱 문법
  · **왼쪽 세로 메뉴**(그룹 머리말 + 접기 252↔76px) → 1080px 아래 자동 축소 → 720px 아래 **하단 탭바**
  · 화면 머리 = 알약 꼬리표 + 큰 두 줄 제목(핵심 단어만 파랑) + 설명
  · 상태는 **색 + 글자**(색만으로 구분하지 않는다), 3단 테마, PC 기본 글꼴(인터넷 없이 열림)

구성
  · `STYLE`     — 대시보드(앱). 레퍼런스 전체 + 보탬.
  · `DOC_STYLE` — 읽는 문서 5종. 레퍼런스의 **틀만**(메뉴·머리 줄·탭바·토스트·화면 머리) +
                  문서 부품(.panel·.k·.tag·table.t·.said·ol.asks …)을 QMS 모양으로 다시 그린 층.
                  ⚠️ 레퍼런스 앱 구획을 통째로 실으면 `.note`·`.cap`·`.kv`·`.ok/.warn/.bad` 같은
                  이름이 문서의 같은 이름과 뜻이 달라 깨진다 — 그래서 구획 단위로 골라 싣는다.
  · `nav()`/`hero()`/`foot()` — 옛 포털 스타일과 **같은 서명**. 소비처는 import 만 바꾼다.
  · `nav_hub()` — 단일 파일 통합본 허브의 틀(메뉴가 버튼).

⚠️ 이 파일의 CSS 는 f-string 이 아니다. 중괄호를 이스케이프하지 말 것.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

#: 레퍼런스 CSS **원본 그대로**. 손대지 않는다 — 고칠 것은 아래 보탬 층에서 덮어쓴다.
_REF = """
/* 보는용 현황판 — Blue365 UI 스타일(docs/UI_디자인_가이드.md): 회색 바탕 + 흰 카드(둥근 20px) + 파란 강조 한 색.
   카드 = 위 회색 미리보기(well) + 아래 '01 제목 / 보조 설명'. 숫자는 아래 D(JSON)에서. 인터넷 없이 열림(글꼴은 PC 기본 글꼴). */
:root {
  --bg: #f2f4f6; --surface: #ffffff; --well: #f7f8fa; --ink: #191f28; --ink2: #333d4b; --muted: #6b7684; --faint: #8b95a1;
  --line: #e5e8eb; --primary: #3182f6; --primary-soft: #e8f3ff; --primary-ink: #1b64da; --on-primary: #ffffff;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4; --s6: #008300; --s7: #4a3aa7; --s8: #e34948;
  --ok: #0ca30c; --warn: #fab219; --serious: #ec835a; --bad: #d03b3b;
  --ok-bg: #e8f7ec; --warn-bg: #fff4d9; --bad-bg: #fdecec; --band: rgba(49,130,246,.10);
  --shadow: 0 1px 2px rgba(0,0,0,.03), 0 6px 20px rgba(0,0,0,.045); --glow: 0 0 0 4px rgba(49,130,246,.14);
  --scrim: rgba(0,0,0,.42); --toast: #191f28; --toast-ink: #ffffff;
  --r-card: 20px; --r-well: 14px; --ease-out: cubic-bezier(.2,.8,.2,1); --spring: cubic-bezier(.34,1.56,.64,1);
  --side: #fbfcfd; --hover: #eef1f4;
  --f-body: "Pretendard", "Pretendard Variable", "Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #101114; --surface: #1c1e23; --well: #25282e; --ink: #f2f4f6; --ink2: #d1d6db; --muted: #a0a9b3; --faint: #7d8792;
  --line: #30343b; --primary: #4593fc; --primary-soft: #1b2a42; --primary-ink: #8bbcff; --on-primary: #ffffff;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
  --ok-bg: #15301d; --warn-bg: #3a2f12; --bad-bg: #3b1a1a; --band: rgba(69,147,252,.16);
  --shadow: 0 1px 2px rgba(0,0,0,.4); --glow: 0 0 0 4px rgba(69,147,252,.22); --toast: #f2f4f6; --toast-ink: #191f28; --side: #17191e; --hover: #24282e; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #101114; --surface: #1c1e23; --well: #25282e; --ink: #f2f4f6; --ink2: #d1d6db; --muted: #a0a9b3; --faint: #7d8792;
  --line: #30343b; --primary: #4593fc; --primary-soft: #1b2a42; --primary-ink: #8bbcff; --on-primary: #ffffff;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
  --ok-bg: #15301d; --warn-bg: #3a2f12; --bad-bg: #3b1a1a; --band: rgba(69,147,252,.16);
  --shadow: 0 1px 2px rgba(0,0,0,.4); --glow: 0 0 0 4px rgba(69,147,252,.22); --toast: #f2f4f6; --toast-ink: #191f28; --side: #17191e; --hover: #24282e; color-scheme: dark }
* { box-sizing: border-box }
html, body { margin: 0 }
body { background: var(--bg); color: var(--ink); font-family: var(--f-body); font-size: 15px; line-height: 1.6; word-break: keep-all; overflow-wrap: break-word;
       font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased }
.wrap { max-width: 1180px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)) }
h1, h2, h3 { line-height: 1.3; margin: 0 }
button { font: inherit; color: inherit }
a { color: var(--primary-ink) }
:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; border-radius: 6px }
.n, td.n, th.n { text-align: right; font-variant-numeric: tabular-nums }

/* ── 앱 틀: 왼쪽 세로 메뉴(그룹별) + 오른쪽 화면(고정 머리 줄 → 내용) ── */
.shell { display: grid; grid-template-columns: 252px minmax(0, 1fr); min-height: 100vh; transition: grid-template-columns .25s var(--ease-out) }
.shell.mini { grid-template-columns: 76px minmax(0, 1fr) }
.side { position: sticky; top: 0; height: 100vh; overflow-y: auto; background: var(--side); border-right: 1px solid var(--line); padding: 18px 14px 16px; display: flex; flex-direction: column; gap: 4px; min-width: 0; scrollbar-width: thin }
.brand { display: flex; align-items: center; gap: 10px; padding: 2px 6px 12px; font-weight: 800; font-size: 17px; letter-spacing: -.01em; white-space: nowrap }
.logo { width: 34px; height: 34px; border-radius: 10px; background: var(--primary); color: #fff; display: grid; place-items: center; flex: none }
.logo svg { width: 18px; height: 18px }
.brand small { font-size: 11px; color: var(--faint); font-weight: 700 }
.collapse { margin-left: auto; width: 32px; height: 32px; border: 0; background: none; border-radius: 8px; cursor: pointer; color: var(--faint); display: grid; place-items: center }
.collapse:hover { background: var(--hover); color: var(--ink) }
.ws { display: flex; align-items: center; gap: 10px; border: 1px solid var(--line); background: var(--surface); border-radius: 14px; padding: 10px 12px; margin-bottom: 6px; box-shadow: var(--shadow) }
.ws .av { width: 32px; height: 32px; border-radius: 50%; background: var(--primary-soft); color: var(--primary-ink); display: grid; place-items: center; font-weight: 800; font-size: 13px; flex: none }
.ws div { min-width: 0 } .ws b { display: block; font-size: 13.5px; white-space: nowrap } .ws small { color: var(--faint); font-size: 12px; white-space: nowrap }
.grp { font-size: 11px; font-weight: 700; color: var(--faint); letter-spacing: .12em; padding: 14px 10px 4px; white-space: nowrap }
.navi { display: flex; align-items: center; gap: 11px; width: 100%; border: 1px solid transparent; background: none; border-radius: 12px; padding: 8px 10px; cursor: pointer; color: var(--ink2); font-size: 14.5px; text-align: left; white-space: nowrap; transition: background .15s }
.navi svg { width: 19px; height: 19px; flex: none; color: var(--muted) }
.navi:hover { background: var(--hover) }
.navi[aria-current="page"] { background: var(--surface); border-color: var(--line); box-shadow: var(--shadow); font-weight: 700; color: var(--ink) }
.navi[aria-current="page"] svg { color: var(--primary) }
.navi .badge { margin-left: auto }
.side .spacer { flex: 1; min-height: 12px }
.upd { border: 1px solid var(--line); background: var(--surface); border-radius: 14px; padding: 11px 12px; font-size: 12.5px; color: var(--muted); box-shadow: var(--shadow) }
.upd b { display: flex; align-items: center; gap: 6px; color: var(--ink); font-size: 13px }
.upd b i { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px var(--ok-bg) }
.shell.mini .lbl, .shell.mini .ws div, .shell.mini .upd, .shell.mini .brand .txt, .shell.mini .navi .badge { display: none }
.shell.mini .grp { height: 12px; padding: 0; font-size: 0 }
.shell.mini .navi, .shell.mini .ws { justify-content: center; padding-inline: 0 }
.shell.mini .navi { position: relative } .shell.mini .navi.has-b::after { content: ""; position: absolute; top: 6px; right: 14px; width: 8px; height: 8px; border-radius: 50%; background: var(--bad) }
.shell.mini .brand { flex-direction: column } .shell.mini .collapse { margin: 0 }
.mainc { min-width: 0 }
.top { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--bg) 86%, transparent); backdrop-filter: saturate(1.4) blur(12px); -webkit-backdrop-filter: saturate(1.4) blur(12px);
       border-bottom: 1px solid transparent; transition: border-color .2s }
.top.scrolled { border-bottom-color: var(--line) }
.bar { display: flex; align-items: center; gap: 10px; min-height: 60px }
.mbrand { display: none; align-items: center; gap: 8px; font-weight: 800; font-size: 16px; white-space: nowrap }
.mbrand .logo { width: 28px; height: 28px; border-radius: 8px } .mbrand .logo svg { width: 15px; height: 15px }
.where { font-size: 14px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0 }
.where b { color: var(--ink); font-weight: 700 }
.tag { display: inline-flex; align-items: center; height: 26px; padding: 0 11px; border-radius: 999px; background: var(--primary-soft); color: var(--primary-ink); font-size: 12.5px; font-weight: 700; white-space: nowrap }
.tag.demo { background: var(--warn-bg); color: var(--ink2) }
.refchip { display: inline-flex; align-items: center; gap: 7px; height: 36px; padding: 0 13px; border-radius: 999px; background: var(--surface); border: 1px solid var(--line); font-size: 13px; color: var(--ink2); white-space: nowrap }
.refchip i { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px var(--ok-bg) }
.grow { flex: 1 }
.iconbtn { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 12px; cursor: pointer; font-size: 13.5px; font-weight: 600; color: var(--ink2) }
.iconbtn:hover { background: var(--well) }
.iconbtn svg { width: 18px; height: 18px }
.badge { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; background: var(--bad); color: #fff; font-size: 11px; font-weight: 800; line-height: 1; margin-left: 4px; vertical-align: 2px }

/* ── 배너(맨 위 안내, 닫기 ×) ── */
.banner { display: flex; gap: 10px; align-items: flex-start; background: var(--primary-soft); color: var(--ink2); border-radius: 14px; padding: 11px 14px; margin-top: 14px; font-size: 14px }
.banner.warn { background: var(--warn-bg) }
.banner .ic { flex: none; width: 20px; height: 20px; border-radius: 50%; background: var(--primary); color: #fff; display: grid; place-items: center; font-size: 12px; font-weight: 800; margin-top: 1px }
.banner.warn .ic { background: var(--warn); color: #1d1d1d }
.banner p { margin: 0; flex: 1 }
.banner button { border: 0; background: none; cursor: pointer; color: var(--muted); font-size: 18px; line-height: 1; padding: 0 2px }

/* ── 화면 머리: 알약 꼬리표 + 큰 두 줄 제목(핵심 단어만 파랑) ── */
.page { padding-block: 22px 40px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; animation: fadeThrough .26s var(--ease-out) both }
.page > *, .ctrl > div { min-width: 0; max-width: 100% }
.crumb { display: flex; gap: 8px; align-items: center; font-size: 13.5px; color: var(--muted) }
.crumb a { color: var(--muted); text-decoration: none } .crumb a:hover { color: var(--ink) }
.crumb .back { display: inline-flex; align-items: center; gap: 4px; color: var(--primary-ink); font-weight: 700; cursor: pointer; border: 0; background: none; padding: 0 }
.hl { font-size: clamp(27px, 4.4vw, 40px); font-weight: 800; letter-spacing: -.025em; line-height: 1.25; margin-top: 10px }
.hl em { font-style: normal; color: var(--primary) }
.lead { color: var(--muted); font-size: 14.5px; margin: 8px 0 0 }
.sec { font-size: 17px; font-weight: 800; letter-spacing: -.01em; margin: 10px 0 -4px; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap }
.sec small { font-size: 13px; font-weight: 500; color: var(--muted) }

/* ── 카드(흰 카드 + 회색 미리보기 + 번호 제목) ── */
.grid { display: grid; gap: 14px }
.g-auto { grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr)) }
.g-stage { grid-template-columns: repeat(auto-fill, minmax(min(100%, 190px), 1fr)) }
.g2 { grid-template-columns: repeat(2, minmax(0, 1fr)) }
.g-kpi { grid-template-columns: repeat(4, minmax(0, 1fr)) }
@media (max-width: 1240px) { .g-kpi { grid-template-columns: repeat(2, minmax(0, 1fr)) } }
@media (max-width: 560px) { .g-kpi { grid-template-columns: minmax(0, 1fr) } }
.g12 { grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) }
.card { background: var(--surface); border-radius: var(--r-card); padding: 12px; box-shadow: var(--shadow); border: 2px solid transparent; min-width: 0;
        animation: rise .34s var(--ease-out) both; animation-delay: calc(var(--i, 0) * 35ms); transition: border-color .2s, box-shadow .2s, transform .25s var(--spring) }
.card.pad { padding: 18px 20px }
.card.click { cursor: pointer } .card.click:hover { transform: translateY(-2px) }
.card.sel { border-color: var(--primary); box-shadow: var(--shadow), var(--glow) }
.well { background: var(--well); border-radius: var(--r-well); padding: 16px; min-height: 112px; display: grid; align-content: center; gap: 4px; position: relative }
.cap { padding: 12px 6px 4px }
.cap .t { font-size: 16px; font-weight: 800; letter-spacing: -.01em; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap }
.no { color: var(--primary); font-weight: 800; font-size: 14px; font-variant-numeric: tabular-nums }
.cap small { display: block; color: var(--faint); font-size: 13px; margin-top: 2px }
.big { font-size: 30px; font-weight: 800; letter-spacing: -.02em; line-height: 1.15 }
.big span { font-size: 15px; font-weight: 700; color: var(--muted); margin-left: 3px }
.corner { position: absolute; top: 12px; right: 12px }
.card h3 { font-size: 16px; font-weight: 800; margin-bottom: 10px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap }

/* ── 상태 칩(색 + 글자, 색만으로 구분하지 않음) ── */
.pill { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 10px; border-radius: 999px; font-size: 12.5px; font-weight: 700; white-space: nowrap; color: var(--ink2) }
.pill::before { content: ""; width: 7px; height: 7px; border-radius: 50% }
.ok { background: var(--ok-bg) } .ok::before { background: var(--ok) }
.warn { background: var(--warn-bg) } .warn::before { background: var(--warn) }
.bad { background: var(--bad-bg) } .bad::before { background: var(--bad) }
.mute { background: var(--well) } .mute::before { background: var(--faint) }
.card .mute { background: var(--bg) }

/* ── 세그먼트(하나만 고르는 짧은 선택지) · 칩(거르기) ── */
.ctrl { display: flex; gap: 14px 22px; flex-wrap: wrap; align-items: flex-end; min-width: 0 }
.ctrl .lab { font-size: 13px; font-weight: 600; color: var(--muted); display: block; margin-bottom: 6px }
.seg { display: inline-flex; background: var(--line); padding: 3px; border-radius: 12px; gap: 2px; max-width: 100%; overflow-x: auto }
.seg button { border: 0; background: transparent; padding: 6px 14px; border-radius: 9px; cursor: pointer; font-size: 14px; font-weight: 600; color: var(--muted); white-space: nowrap; transition: background .2s, color .2s }
.seg button[aria-pressed="true"] { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.12) }
.chips { display: flex; gap: 8px; flex-wrap: wrap }
.chips button { display: inline-flex; align-items: center; gap: 4px; height: 34px; padding: 0 14px; border: 1px solid var(--line); background: var(--surface); color: var(--ink2); border-radius: 999px; cursor: pointer; font-size: 14px; font-weight: 600; white-space: nowrap; transition: background .2s, border-color .2s }
.chips button[aria-pressed="true"] { background: var(--primary-soft); border-color: var(--primary); color: var(--primary-ink) }
.chips button[aria-pressed="true"]::before { content: "✓"; font-weight: 800 }
.chips .cnt { color: var(--faint); font-weight: 600; font-size: 13px }
.chips button[aria-pressed="true"] .cnt { color: var(--primary-ink) }
@media (max-width: 720px) { .chips.scrollx { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin-inline: -16px; padding-inline: 16px } }

/* ── 목록·표 ── */
.list { display: grid }
.li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 12px 8px; border-bottom: 1px solid var(--line); cursor: pointer; border-radius: 12px; transition: background .15s }
.li:last-child { border-bottom: 0 }
.li:hover { background: var(--well) }
.li.sel { background: var(--primary-soft) }
.li .main b { font-weight: 700 } .li .main small { display: block; color: var(--muted); font-size: 13px }
.chev { color: var(--faint); font-size: 18px }
table { border-collapse: collapse; width: 100%; font-size: 14px }
th { text-align: left; font-weight: 600; color: var(--faint); font-size: 12.5px; border-bottom: 1px solid var(--line); padding: 8px; white-space: nowrap }
td { border-bottom: 1px solid var(--line); padding: 9px 8px; vertical-align: middle }
tr:last-child td { border-bottom: 0 }
tr.selrow td { background: var(--primary-soft) }
.scroll { overflow-x: auto } .tall { max-height: 380px; overflow: auto }
.note { font-size: 13px; color: var(--muted); margin: 0 }

/* ── 그래프 ── */
.legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-bottom: 6px }
.legend i { display: inline-block; width: 14px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 5px }
.chart { position: relative } .chart svg { display: block; width: 100%; height: auto; touch-action: pan-y }
.axis text { fill: var(--faint); font-size: 11px }
.ctip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 7px 10px; font-size: 12.5px; box-shadow: 0 6px 20px rgba(0,0,0,.12); white-space: nowrap; z-index: 2 }

/* ── 진행 링 · 진행 바 · 범위 바 · 평점 요약형 막대 ── */
.ring { display: grid; place-items: center; position: relative; width: 92px; height: 92px; margin: 0 auto }
.ring svg { position: absolute; inset: 0; transform: rotate(-90deg) }
.ring b { font-size: 21px; font-weight: 800 }
.ring circle { transition: stroke-dashoffset .9s var(--ease-out) }
.pbar { height: 8px; border-radius: 999px; background: var(--line); overflow: hidden } .pbar > i { display: block; height: 100%; border-radius: 999px; background: var(--primary); transition: width .7s var(--ease-out) }
.sum { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 18px; align-items: center }
.sum .tot { text-align: center } .sum .tot .big { font-size: 40px } .sum .tot small { color: var(--muted); font-size: 12.5px; display: block }
.sum .rows { display: grid; gap: 7px }
.sum .r { display: grid; grid-template-columns: 34px minmax(0, 1fr) 30px; gap: 8px; align-items: center; font-size: 13px; color: var(--muted) }
.sum .r .n { color: var(--ink2); font-weight: 700 }
.range { position: relative; height: 34px; margin: 14px 0 18px }
.range .trk { position: absolute; left: 0; right: 0; top: 15px; height: 4px; border-radius: 4px; background: var(--line) }
.range .bd { position: absolute; top: 12px; height: 10px; border-radius: 6px; background: color-mix(in srgb, var(--primary) 28%, transparent) }
.range .pt { position: absolute; top: 9px; width: 16px; height: 16px; margin-left: -8px; border-radius: 50%; background: var(--primary); border: 3px solid var(--surface); box-shadow: 0 1px 4px rgba(0,0,0,.25); transition: left .35s var(--spring) }
.range .mk { position: absolute; top: 4px; width: 2px; height: 26px; margin-left: -1px; background: var(--bad) }
.range .mk.l { background: var(--serious) }
.range .ml { position: absolute; top: -12px; font-size: 11px; color: var(--muted); transform: translateX(-50%); white-space: nowrap }

/* ── 단계 표시(세로 스테퍼) ── */
.steps { list-style: none; margin: 0; padding: 0; counter-reset: st }
.steps > li { position: relative; padding: 0 0 18px 46px; counter-increment: st }
.steps > li::before { content: counter(st); position: absolute; left: 0; top: 0; width: 30px; height: 30px; border-radius: 50%; background: var(--primary); color: var(--on-primary); display: grid; place-items: center; font-weight: 800; font-size: 14px }
.steps > li::after { content: ""; position: absolute; left: 14px; top: 34px; bottom: 4px; width: 2px; background: var(--primary-soft) }
.steps > li:last-child::after { display: none } .steps > li:last-child { padding-bottom: 0 }
.steps h4 { margin: 3px 0 4px; font-size: 15px; font-weight: 800 }
.steps ul { margin: 2px 0 0; padding-left: 18px }
.hstep { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; counter-reset: hs }
.hstep > div { position: relative; padding: 42px 10px 0 0; counter-increment: hs; font-size: 14px }
.hstep > div::before { content: counter(hs); position: absolute; top: 0; left: 0; width: 30px; height: 30px; border-radius: 50%; background: var(--primary); color: var(--on-primary); display: grid; place-items: center; font-weight: 800 }
.hstep > div::after { content: ""; position: absolute; top: 14px; left: 36px; right: 6px; height: 2px; background: var(--primary-soft) }
.hstep > div:last-child::after { display: none }
.hstep b { display: block; font-size: 15px }
.hyp { display: grid; grid-template-columns: 60px minmax(0, 1fr) minmax(70px, 22%) 104px; gap: 6px 10px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 14px }
.hyp:last-child { border-bottom: 0 }
.hyp .ax { font-weight: 700; color: var(--muted); font-size: 13px }

/* ── 직접 입력(라벨은 칸 위에 — 자리표시자로 대신하지 않음) ── */
.calc { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px }
.calc label { font-size: 13px; font-weight: 600; color: var(--muted); display: block; margin-bottom: 5px }
.calc input { font: inherit; width: 100%; height: 42px; padding: 0 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); color: var(--ink); font-variant-numeric: tabular-nums; transition: border-color .15s, box-shadow .15s }
.calc input:focus { outline: none; border-color: var(--primary); box-shadow: var(--glow) }
.calc input.err { border-color: var(--bad) }
.ferr { color: var(--bad); font-size: 12.5px; margin-top: 4px }

/* ── 빈 화면 ── */
.empty { display: grid; place-items: center; text-align: center; gap: 6px; color: var(--muted); background: var(--well); border-radius: var(--r-well); padding: 28px 16px; font-size: 14px }
.empty::before { content: ""; width: 40px; height: 40px; border-radius: 50%; background: var(--line) }

/* ── 툴팁(ⓘ 누르면 설명) ── */
.qi { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; border: 1.5px solid var(--faint); color: var(--faint); font-size: 11px; font-weight: 800; cursor: pointer; background: none; padding: 0; vertical-align: 1px; font-style: normal }
.qi:hover { border-color: var(--primary); color: var(--primary) }
.pop { position: fixed; z-index: 60; max-width: 280px; background: var(--toast); color: var(--toast-ink); font-size: 13px; line-height: 1.5; padding: 9px 12px; border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.2); animation: fadeIn .15s var(--ease-out) }

/* ── 토스트 ── */
.toast { position: fixed; left: 50%; bottom: calc(28px + env(safe-area-inset-bottom, 0px)); transform: translate(-50%, 20px); opacity: 0; z-index: 70; background: var(--toast); color: var(--toast-ink);
         padding: 10px 18px; border-radius: 999px; font-size: 14px; font-weight: 600; pointer-events: none; transition: opacity .2s, transform .3s var(--spring); white-space: nowrap }
.toast.on { opacity: 1; transform: translate(-50%, 0) }

/* ── 모달(넓은 화면) / 바텀시트(휴대폰) ── */
.scrim { position: fixed; inset: 0; background: var(--scrim); z-index: 50; display: grid; place-items: center; padding: 16px; animation: fadeIn .2s var(--ease-out) }
.sheet { background: var(--surface); color: var(--ink); border-radius: 22px; width: min(460px, 100%); padding: 22px; box-shadow: 0 20px 50px rgba(0,0,0,.25); animation: pop .26s var(--spring); display: grid; gap: 12px }
.sheet h3 { font-size: 19px; font-weight: 800 }
.sheet .grab { display: none }
.btns { display: flex; gap: 8px; margin-top: 4px }
.btn { flex: 1; height: 48px; border-radius: 14px; border: 0; font-weight: 700; font-size: 15px; cursor: pointer; background: var(--well); color: var(--ink2) }
.btn.primary { background: var(--primary); color: var(--on-primary) }
.kv { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 6px 10px; font-size: 14px } .kv dt { color: var(--muted) } .kv dd { margin: 0 }

/* ── 하단 탭바(휴대폰) · 맨 위로 버튼 · 코치마크 ── */
.tabbar { display: none }
.fab { position: fixed; right: max(16px, env(safe-area-inset-right, 0px)); bottom: calc(24px + env(safe-area-inset-bottom, 0px)); z-index: 30; width: 48px; height: 48px; border-radius: 50%; border: 0; cursor: pointer;
       background: var(--surface); color: var(--ink2); box-shadow: 0 6px 18px rgba(0,0,0,.16); display: grid; place-items: center; opacity: 0; transform: scale(.7); pointer-events: none; transition: opacity .2s, transform .3s var(--spring) }
.fab.on { opacity: 1; transform: none; pointer-events: auto }
.coach { position: fixed; z-index: 65; max-width: 290px; background: var(--toast); color: var(--toast-ink); border-radius: 14px; padding: 12px 14px; font-size: 14px; box-shadow: 0 12px 30px rgba(0,0,0,.25); animation: pop .3s var(--spring) }
.coach::before { content: ""; position: absolute; left: 26px; top: -6px; width: 12px; height: 12px; background: var(--toast); transform: rotate(45deg) }
.coach.up::before { top: auto; bottom: -6px }
.coach.left::before { left: -6px; top: 22px }
.coach button { margin-top: 8px; border: 0; border-radius: 999px; background: var(--primary); color: #fff; font-weight: 700; padding: 5px 14px; cursor: pointer }
footer { color: var(--muted); font-size: 13px; padding-block: 0 40px; display: grid; gap: 6px }

@media (max-width: 860px) { .g2, .g12 { grid-template-columns: 1fr } }
@media (max-width: 1080px) and (min-width: 721px) { .shell, .shell.mini { grid-template-columns: 76px minmax(0, 1fr) }
  .shell .lbl, .shell .ws div, .shell .upd, .shell .brand .txt, .shell .navi .badge, .shell .collapse { display: none }
  .shell .grp { height: 12px; padding: 0; font-size: 0 } .shell .navi, .shell .ws { justify-content: center; padding-inline: 0 }
  .shell .navi { position: relative } .shell .navi.has-b::after { content: ""; position: absolute; top: 6px; right: 14px; width: 8px; height: 8px; border-radius: 50%; background: var(--bad) }
  .refchip { display: none } }
@media (max-width: 720px) {
  body { padding-bottom: calc(68px + env(safe-area-inset-bottom, 0px)) }
  .shell, .shell.mini { grid-template-columns: minmax(0, 1fr) } .side { display: none } .mbrand { display: flex } .where, .refchip { display: none }
  .tabbar { display: grid; grid-template-columns: repeat(6, 1fr); position: fixed; left: 0; right: 0; bottom: 0; z-index: 40; background: var(--surface); border-top: 1px solid var(--line); padding: 6px 4px calc(6px + env(safe-area-inset-bottom, 0px)) }
  .tabbar button { border: 0; background: none; display: grid; justify-items: center; gap: 2px; padding: 4px 0; cursor: pointer; color: var(--faint); font-size: 10.5px; font-weight: 700; position: relative }
  .tabbar button svg { width: 22px; height: 22px }
  .tabbar button[aria-selected="true"] { color: var(--primary) }
  .tabbar .badge { position: absolute; top: 0; left: 52%; margin: 0; min-width: 16px; height: 16px; font-size: 10px }
  .fab { bottom: calc(84px + env(safe-area-inset-bottom, 0px)) }
  .toast { bottom: calc(88px + env(safe-area-inset-bottom, 0px)) }
  .scrim { place-items: end center; padding: 0 }
  .sheet { width: 100%; border-radius: 22px 22px 0 0; padding: 10px 18px calc(18px + env(safe-area-inset-bottom, 0px)); animation: sheetUp .32s var(--ease-out) }
  .sheet .grab { display: block; width: 40px; height: 5px; border-radius: 3px; background: var(--line); margin: 0 auto 4px }
  .hide-sm { display: none }
  .hyp { grid-template-columns: 52px minmax(0, 1fr) } .hyp .pbar, .hyp .vd { grid-column: 2 }
  .hstep { grid-template-columns: 1fr; gap: 14px } .hstep > div { padding: 2px 0 0 42px; min-height: 30px } .hstep > div::after { display: none }
  .big { font-size: 26px } #share span { display: none }
  .sum .tot .big { font-size: 34px }
}
@keyframes rise { from { opacity: 0; transform: translateY(10px) } to { opacity: 1; transform: none } }
@keyframes fadeThrough { from { opacity: 0; transform: scale(.992) } to { opacity: 1; transform: none } }
@keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
@keyframes pop { from { opacity: 0; transform: scale(.94) } to { opacity: 1; transform: none } }
@keyframes sheetUp { from { transform: translateY(100%) } to { transform: none } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important } }
@media print { .side, .top, .tabbar, .fab, .banner button { display: none !important } .shell { display: block } .card { break-inside: avoid; box-shadow: none; border: 1px solid #ddd } }
"""


def _sections(css: str) -> dict[str, str]:
    """레퍼런스 CSS 를 `/* ── 이름 ── */` 머리말 단위로 나눈다(순서 보존)."""
    out = {}
    for part in re.split(r"(?m)^(?=/\* ── )", css):
        m = re.match(r"/\* ── ([^─(:]+)", part)
        out[m.group(1).strip() if m else "PRELUDE"] = part
    return out


_S = _sections(_REF)

#: 문서에 싣는 레퍼런스 구획.
#: ⚠️ 문서들은 자기 클래스 이름(.note·.cap·.kv·.card·.grid·.empty·.ok/.warn/.bad …)을
#:    이미 쓰고 있다. 레퍼런스의 **앱 구획**(카드·상태 칩·목록·그래프·빈 화면·진행 링 …)이
#:    같은 이름을 다른 뜻으로 정의하므로 그대로 실으면 문서가 깨진다(대시보드에서 실제로
#:    `.bad` 가 숫자 뒤에 칩 배경을 깔았다 — §6-0-30). → **틀(메뉴·머리 줄·탭바·토스트)과
#:    화면 머리만** 싣고, 문서 부품은 아래 DOC 층에서 QMS 모양으로 다시 그린다.
_DOC_KEEP = ("PRELUDE", "앱 틀", "화면 머리", "토스트", "하단 탭바")
_missing = [k for k in _DOC_KEEP if k not in _S]
assert not _missing, f"레퍼런스 구획이 사라졌다: {_missing}"

# ── 공통 보탬 ① 토큰 이름 호환층 ──────────────────────────────────────────
ALIAS = """
/* ══════════════════════════════════════════════════════════════════════
   아래부터는 이 저장소 전용 보탬 — 레퍼런스에 없는 것만 더한다.
   ══════════════════════════════════════════════════════════════════════ */

/* ⚠️ **토큰 이름 호환층**. 문서·차트 코드가 옛 포털 스타일 이름(--accent · --bar · --grid ·
      --good · --ink-2/3 · --surface-2 · --radius · --series-1/2 …)을 그대로 쓴다. 이름을
      바꾸면 그림이 통째로 깨지므로, QMS 팔레트 **값**을 옛 **이름**에 다시 묶어 둔다. */
:root {
  --ground: var(--bg); --paper: var(--bg); --rule: var(--line);
  --surface-2: var(--well); --surface-3: var(--well);
  --ink-2: var(--muted); --ink-3: var(--faint);
  --line-2: var(--line); --grid: var(--line);
  --accent: var(--primary); --accent-2: var(--primary); --accent-soft: var(--primary-soft); --accent-ink: var(--primary-ink);
  --good: var(--ok); --warnfill: var(--warn-bg); --badfill: var(--bad-bg);
  --series-1: var(--s1); --series-2: var(--s2);
  --radius: var(--r-well); --brand: var(--primary-ink); --new: var(--bad);
  --nav: var(--surface); --nav-ink: var(--ink2); --nav-line: var(--line);
  --hero: var(--bg); --hero-2: var(--bg); --hero-ink: var(--ink); --hero-ink-2: var(--muted);
  /* 글자용 상태색 — 레퍼런스의 --warn(#fab219)·--ok 는 점·막대 채움용이라 흰 바탕 **글자**로
     쓰면 대비가 모자란다. 글자에는 아래 -ink 를 쓴다. */
  --ok-ink: #0a7d0a; --warn-ink: #9a6400; --bad-ink: #c23030;
  --bar: #c3cbd6;                       /* 막대 채움 — 선으로 쓰면 묻히므로 계열색과 따로 둔다 */
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bar: #495260; --ok-ink: #6fd27a; --warn-ink: #f2c14e; --bad-ink: #f28b8b } }
:root[data-theme="dark"] { --bar: #495260; --ok-ink: #6fd27a; --warn-ink: #f2c14e; --bad-ink: #f28b8b }
"""

# ── 공통 보탬 ② 틀 — 문서 메뉴·하위 화면·한 파일 통합본 안쪽 ─────────────────
SHELL_EXTRA = """
/* 문서 메뉴는 **진짜 링크**(a)다 — 버튼과 같은 모양이 되게 맞춘다 */
a.navi { text-decoration: none }
a.navi:visited { color: var(--ink2) }
span.navi[aria-current="page"] { cursor: default }
.tabbar a { display: grid; justify-items: center; gap: 2px; padding: 4px 0; color: var(--faint); font-size: 10.5px; font-weight: 700; text-decoration: none; position: relative }
.tabbar a svg { width: 22px; height: 22px }
.tabbar [aria-current="page"] { color: var(--primary) }
.tabbar span[aria-current="page"] { display: grid; justify-items: center; gap: 2px; padding: 4px 0; font-size: 10.5px; font-weight: 700 }
.tabbar span[aria-current="page"] svg { width: 22px; height: 22px }
.upd code { font-size: 11.5px }

/* 운영 현황판의 하위 화면 — 현재 문서 항목 아래에 한 단 들여 붙인다 */
.subnav { display: grid; gap: 2px; margin: 2px 0 6px 21px; padding-left: 9px; border-left: 2px solid var(--line) }
.subnav:empty { display: none }
.subnav .navi { font-size: 13.5px; padding: 6px 10px }
.subnav .navi svg { width: 16px; height: 16px }
.subnav .navi[aria-current="page"] { background: var(--primary-soft); border-color: transparent; box-shadow: none; color: var(--primary-ink) }
.shell.mini .subnav { margin-left: 0; padding-left: 0; border-left: 0 }
@media (max-width: 1080px) and (min-width: 721px) { .shell .subnav { margin-left: 0; padding-left: 0; border-left: 0 } }

/* 한 파일 통합본 안쪽에 담길 때 — 바깥 허브가 메뉴를 그리므로 안쪽 틀은 감춘다 */
html.embedded .side, html.embedded .top, html.embedded .tabbar, html.embedded .fab { display: none !important }
html.embedded .shell, html.embedded .shell.mini { display: block }
html.embedded body { padding-bottom: 0 }
"""

# ── 대시보드(앱) 전용 ────────────────────────────────────────────────────────
DASH_EXTRA = """
/* 직접 그린 SVG 차트 — 축 글자(.ax)와 범례 글자(.cs)는 fill 로 색을 준다 */
.chart { display: block; width: 100%; height: auto }
.ax { fill: var(--faint); font-size: 11px }
.cs { fill: var(--muted); font-size: 11px; font-weight: 600 }

/* 작은 설명 줄 */
.hint { font-size: 13px; color: var(--muted); margin: 10px 0 0; line-height: 1.65 }
.hint b { color: var(--ink2); font-weight: 700 }
.card .hint:first-child { margin-top: 0 }

/* 라인 카드 안의 숫자 묶음 */
.statrow { display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr)); gap: 10px }
.stat .v { font-size: 23px; font-weight: 800; letter-spacing: -.025em; line-height: 1.2 }
.stat .v small { font-size: 13px; font-weight: 700; color: var(--muted); margin-left: 2px }
.stat .l { font-size: 12px; color: var(--faint); font-weight: 700; margin-top: 2px }
/* ⚠️ 값 강조는 `.is-*` 로 쓴다. 레퍼런스의 상태 칩이 `.ok/.warn/.bad` 를 **배경색** 규칙으로
      이미 쓰고 있어, 같은 이름을 숫자에 붙이면 숫자 뒤에 칩 배경이 깔린다(2026-11-09 발견). */
.v.is-good { color: var(--ok) } .v.is-bad { color: var(--bad) } .v.is-warn { color: var(--warn-ink) }
.gauge { height: 8px; border-radius: 999px; background: var(--line); overflow: hidden; margin-top: 14px }
.gauge i { display: block; height: 100%; border-radius: 999px; background: var(--primary); transition: width .7s var(--ease-out) }

/* 구역별 재고 막대 */
.zbar { display: grid; grid-template-columns: 40px minmax(0, 1fr) 112px; gap: 10px; align-items: center; font-size: 13px; padding: 3px 0 }
.zbar .zn { text-align: right; color: var(--muted); font-weight: 700 }
.zbar .zt { height: 16px; background: var(--well); border-radius: 5px; overflow: hidden }
.zbar .zt i { display: block; height: 100% }
.zbar .zv { text-align: right; color: var(--muted); font-size: 12.5px }
.zhd { font-size: 13px; color: var(--faint); font-weight: 700; margin: 12px 0 6px }
.zhd:first-child { margin-top: 0 }

/* 기간(년-월-일) 직접 입력 · 기록 검색 */
.dates { display: inline-flex; align-items: center; gap: 8px }
.dates input[type=date] { font: inherit; height: 38px; padding: 0 11px; border: 1px solid var(--line); border-radius: 12px;
  background: var(--surface); color: var(--ink); font-variant-numeric: tabular-nums }
.dates input[type=date]:focus { outline: none; border-color: var(--primary); box-shadow: var(--glow) }
.dates .tilde { color: var(--faint) }
.search { font: inherit; height: 40px; width: 100%; max-width: 300px; padding: 0 13px; border: 1px solid var(--line);
  border-radius: 12px; background: var(--surface); color: var(--ink) }
.search:focus { outline: none; border-color: var(--primary); box-shadow: var(--glow) }

/* 추적 연결 점수판 — 머릿줄 숫자를 크게 */
.score { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap }
.score .pct { font-size: 44px; font-weight: 800; letter-spacing: -.03em; line-height: 1 }
.score .pct.is-good { color: var(--ok) } .score .pct.is-warn { color: var(--warn-ink) } .score .pct.is-bad { color: var(--bad) }

/* 휴대폰·통합본 안쪽에서 하위 화면을 고르는 칩 줄 — 넓은 화면에서는 왼쪽 메뉴가 맡는다 */
.vchips { display: none }
@media (max-width: 720px) { .vchips { display: flex } }
html.embedded .vchips { display: flex }
"""

# ── 문서(읽는 산출물) 전용 — 옛 포털 부품 이름을 QMS 모양으로 다시 그린다 ─────────
DOC = """
/* ══ 문서 층 — 부품 이름은 종전(포털) 그대로, 모양만 QMS ══════════════════ */
/* 본문 틀 — 레퍼런스 .wrap(폭 1180 · 좌우 여백)에 세로 흐름만 더한다 */
.mainc > .wrap { display: flex; flex-direction: column; gap: 16px; padding-block: 18px 40px; min-width: 0 }
.mainc > .wrap.pg { padding-block: 22px 2px; gap: 0 }
.mainc > .wrap.ft { padding-block: 0 }
.mainc > .wrap > * { min-width: 0; max-width: 100% }

/* 화면 머리(히어로 자리) — 꼬리표 + 큰 두 줄 제목 + 설명 */
.pg .lead { max-width: 72ch }
.pg .lead b, .pg .lead strong { color: var(--ink2) }
.pgstrip { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 12px }
.pgquick { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px }
.pgquick a { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 14px; border: 1px solid var(--line); background: var(--surface);
  color: var(--ink2); border-radius: 999px; font-size: 14px; font-weight: 600; text-decoration: none; white-space: nowrap; transition: background .2s, border-color .2s }
.pgquick a:hover { border-color: var(--primary); color: var(--primary-ink) }
.pgquick svg { width: 16px; height: 16px; color: var(--primary) }

/* 카드·패널 — 흰 카드(둥근 20px) */
.mainc .card, .panel { background: var(--surface); border: 0; border-radius: var(--r-card); box-shadow: var(--shadow); min-width: 0 }
.mainc .card { padding: 18px 20px; overflow-x: auto }
.panel { display: flex; flex-direction: column; padding: 0 }
.phd { display: flex; align-items: center; gap: 10px; padding: 16px 20px 0; flex-wrap: wrap }
.phd .sp { flex: 1 }
.pbd { padding: 12px 20px 20px; min-width: 0 }
.phd h3, .panel.plain > h3, .mainc .card > h3 { margin: 0; font-size: 16px; font-weight: 800; letter-spacing: -.01em; color: var(--ink);
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap }
.mainc .card > h3 { margin-bottom: 10px }
.panel.plain { padding: 18px 20px 20px; gap: 12px }

/* 격자 */
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 14px }
.grid.wide { grid-template-columns: minmax(0, 1fr) }
.grid.three { grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)) }

/* KPI 타일 — 페이지 바탕 위에서는 흰 카드, 카드 안에서는 회색 미리보기(well) */
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr)); gap: 14px }
.kpis.two { grid-template-columns: repeat(2, minmax(0, 1fr)) }
@media (max-width: 420px) { .kpis.two { grid-template-columns: minmax(0, 1fr) } }
.k { background: var(--surface); border-radius: var(--r-card); box-shadow: var(--shadow); padding: 16px 18px; display: flex; flex-direction: column; gap: 2px; min-width: 0 }
.card .k, .panel .k { background: var(--well); box-shadow: none; border-radius: var(--r-well) }
.kv { font-size: 28px; font-weight: 800; letter-spacing: -.02em; line-height: 1.15; font-variant-numeric: tabular-nums }
.ku { font-size: 15px; font-weight: 700; color: var(--muted); margin-left: 3px; letter-spacing: 0 }
.kl { font-size: 13px; color: var(--faint); font-weight: 700; margin-top: 4px }
.kn { font-size: 13px; color: var(--muted); line-height: 1.55 }
.k.good .kv { color: var(--ok-ink) } .k.bad .kv { color: var(--bad-ink) } .k.warn .kv { color: var(--warn-ink) }

/* 꼬리표 — 레퍼런스 .tag(알약)에 상태 변형을 더한다. 색만으로 구분하지 않게 글자가 함께 간다 */
.tag.mute { background: var(--well); color: var(--muted) }
.tag.good { background: var(--ok-bg); color: var(--ok-ink) }
.tag.warn { background: var(--warn-bg); color: var(--warn-ink) }
.tag.bad { background: var(--bad-bg); color: var(--bad-ink) }
.mainc .tag { height: 24px; padding: 0 10px; font-size: 12.5px }

/* 세그먼트형 탭 · 칩 */
.tabs { display: inline-flex; background: var(--line); padding: 3px; border-radius: 12px; gap: 2px; max-width: 100%; overflow-x: auto }
.tabs button, .tabs a { border: 0; background: transparent; padding: 6px 14px; border-radius: 9px; cursor: pointer; font: inherit; font-size: 14px;
  font-weight: 600; color: var(--muted); white-space: nowrap; text-decoration: none }
.tabs .on, .tabs [aria-selected="true"] { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.12) }
.chip { display: inline-flex; align-items: center; gap: 4px; height: 34px; padding: 0 14px; border: 1px solid var(--line); background: var(--surface);
  color: var(--ink2); border-radius: 999px; cursor: pointer; font: inherit; font-size: 14px; font-weight: 600; white-space: nowrap; text-decoration: none }
.chip:hover { border-color: var(--primary) }
.chip.on, .chip[aria-pressed="true"] { background: var(--primary-soft); border-color: var(--primary); color: var(--primary-ink) }
.new { display: inline-grid; place-items: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; background: var(--bad); color: #fff; font-size: 11px; font-weight: 800; line-height: 1; vertical-align: 2px }

/* 글 — 질문·답·주석 */
section { display: flex; flex-direction: column; gap: 12px; min-width: 0 }
/* 섹션 머리는 질문(.q, 20px)보다 작아야 위계가 선다 — 파란 작은 머리말(레퍼런스의 .no 색) */
section > h2 { font-size: 13.5px; font-weight: 800; color: var(--primary-ink); margin: 14px 0 -4px; padding: 0; border: 0 }
.q { font-size: 20px; font-weight: 800; letter-spacing: -.02em; line-height: 1.4; margin: 0; text-wrap: balance }
.a { font-size: 15px; margin: 0; max-width: 72ch; color: var(--ink2); line-height: 1.75 }
.a strong { color: var(--primary-ink); font-weight: 700 }
p.note { font-size: 13px; color: var(--muted); margin: 0; max-width: 76ch; line-height: 1.7 }
p.note b { color: var(--ink2); font-weight: 700 }
.hint { font-size: 13px; color: var(--muted); margin: 8px 0 0; line-height: 1.65 }
.empty { color: var(--muted); background: var(--well); border-radius: var(--r-well); padding: 24px 16px; text-align: center; font-size: 14px }
.mono, .pmeta b { font-variant-numeric: tabular-nums }

/* 차트 · 표 */
svg.chart { display: block; width: 100%; height: auto }
.ax { font-size: 11px; fill: var(--faint) }
.ct { font-size: 12.5px; fill: var(--ink); font-weight: 700 }
.cs { font-size: 11px; fill: var(--muted) }
.inb { font-size: 11px; fill: var(--surface); font-weight: 700 }
.inw { font-size: 11px; fill: var(--ink); font-weight: 700 }
.tbl { overflow-x: auto }
table.t { border-collapse: collapse; width: 100%; font-size: 14px; font-variant-numeric: tabular-nums }
table.t th { text-align: left; font-weight: 600; color: var(--faint); font-size: 12.5px; background: none; border-bottom: 1px solid var(--line); padding: 8px; white-space: nowrap }
table.t td { border-bottom: 1px solid var(--line); padding: 9px 8px; color: var(--ink2); vertical-align: middle }
table.t td b, table.t td strong { color: var(--ink) }
table.t tr:last-child td { border-bottom: 0 }
table.t td.n, table.t th.n { text-align: right }
table.t td.c { text-align: center; color: var(--ok-ink); font-weight: 700 }

/* 현장 인용 — 레퍼런스의 노란 안내 배너 모양 */
.said { background: var(--warn-bg); border-radius: var(--r-well); padding: 14px 16px; font-size: 14px; color: var(--ink2); line-height: 1.75 }
.said .lbl { display: block; font-size: 12.5px; color: var(--warn-ink); margin-bottom: 6px; font-weight: 800 }
.said b { color: var(--ink); font-weight: 700 }

/* 요청 목록 — 레퍼런스의 세로 스테퍼(번호 원) */
ol.asks { margin: 0; padding: 0; list-style: none; counter-reset: a; display: flex; flex-direction: column; gap: 14px }
ol.asks li { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 14px; align-items: start; font-size: 15px; color: var(--ink) }
ol.asks li::before { counter-increment: a; content: counter(a); width: 30px; height: 30px; border-radius: 50%; background: var(--primary); color: var(--on-primary);
  display: grid; place-items: center; font-weight: 800; font-size: 14px }
ol.asks b { font-weight: 700 }
ol.asks .w { display: block; font-size: 13px; color: var(--muted); margin-top: 3px; line-height: 1.65 }

/* 촘촘한 목록 */
ul.feed { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column }
ul.feed li { display: flex; align-items: center; gap: 10px; padding: 10px 4px; font-size: 14px; border-bottom: 1px solid var(--line) }
ul.feed li:last-child { border-bottom: 0 }
ul.feed .t { flex: 1; min-width: 0; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
ul.feed .who, ul.feed .d { font-size: 13px; color: var(--muted); white-space: nowrap }

/* 코드·옛 머리말 호환 */
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; background: var(--well); border-radius: 6px; padding: 1px 6px; color: var(--ink2) }
pre { background: var(--well); border-radius: var(--r-well); padding: 14px; overflow-x: auto; font-size: 12.5px }
.eyebrow { font-size: 12.5px; color: var(--faint); font-weight: 700 }
.thesis { font-size: 15px; line-height: 1.75; color: var(--ink2); margin: 0; max-width: 72ch }
.thesis strong { color: var(--ink); font-weight: 700 }
.meta { font-size: 13px; color: var(--faint) }
@media (max-width: 560px) { .q { font-size: 18px } .kv { font-size: 24px } }
/* 문서 안의 재현 안내 바닥글 — 레퍼런스 footer 는 화면 맨 아래용(아래 여백 40px)이라 본문 안에선 줄인다 */
/* ⚠️ 레퍼런스 footer 는 grid 라 글자와 <code> 가 줄마다 쪼개진다 → 문서 안에선 보통 글 흐름으로 */
.mainc > .wrap:not(.ft) > footer { display: block; padding: 16px 0 0; border-top: 1px solid var(--line); line-height: 1.75 }
"""

#: 대시보드(앱) — 레퍼런스 전체 + 보탬. 순서가 곧 우선순위다.
STYLE = _REF + ALIAS + SHELL_EXTRA + DASH_EXTRA
#: 문서(읽는 산출물) — 레퍼런스의 틀만 + 보탬 + 문서 층.
DOC_STYLE = "".join(_S[k] for k in _DOC_KEEP) + ALIAS + SHELL_EXTRA + DOC


# ══════════════════════════════════════════════════════════════════════════
# 메뉴 — 산출물 6종. 모든 문서가 **같은 왼쪽 세로 메뉴**를 쓴다.
# ══════════════════════════════════════════════════════════════════════════
#: (이름, 파일, 아이콘, 휴대폰 탭바 짧은 이름)
#: ⭐️ **매일 보는 화면** — 품질담당이 "지금 정상인가" 를 판단하는 데 쓴다(§6-0-28).
NAV_ITEMS = (
    ("운영 현황판", "dashboard.html", "overview"),
    ("운영 모니터", "monitor_status.html", "alert"),
)
#: **근거 자료** — 매일 볼 것이 아니라 "왜 그런가" 를 따질 때 여는 것들. 한 묶음 뒤로 뺀다.
NAV_ARCHIVE = (
    ("현황 브리프", "brief.html", "brief"),
    ("배합 처방", "prescription.html", "flask"),
    ("통합 리포트", "final_report.html", "doc"),
    ("계획서", "plan.html", "map"),
)
NAV_GROUPS = (("매일 보기", NAV_ITEMS), ("근거 자료", NAV_ARCHIVE))
SHORT = {"운영 현황판": "현황판", "운영 모니터": "모니터", "현황 브리프": "브리프",
         "배합 처방": "처방", "통합 리포트": "리포트", "계획서": "계획서"}

# ── 운영 현황판의 하위 화면 ──
#: (키, 이름, 짧은 이름)
VIEWS = (
    ("overview", "종합 현황", "현황"),
    ("trend",    "품위 추이", "품위"),
    ("stock",    "적치장 재고", "재고"),
    ("cross",    "교차인출",  "교차"),
    ("recent",   "최근 기록", "기록"),
)

ICONS = {
    # 하위 화면
    "overview": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/>',
    "trend": '<path d="M3 17l5-6 4 3 7-8"/><path d="M3 21h18"/>',
    "stock": '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4"/><path d="M12 11v10"/>',
    "cross": '<path d="M4 8h12"/><path d="m13 5 3 3-3 3"/><path d="M20 16H8"/><path d="m11 13-3 3 3 3"/>',
    "recent": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6"/><path d="M9 16h5"/>',
    # 문서
    "alert": '<path d="M12 4 3 20h18z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
    "brief": '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M3 20h18"/>',
    "flask": '<path d="M9 3h6"/><path d="M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/><path d="M7.5 15h9"/>',
    "doc": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6"/><path d="M9 16h6"/>',
    "map": '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15"/><path d="M15 6v15"/>',
    "grid": '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    "chart": '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M3 20h18"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.2-4.2"/>',
    "book": '<path d="M4 5a2 2 0 0 1 2-2h5v17H6a2 2 0 0 0-2 2z"/><path d="M20 5a2 2 0 0 0-2-2h-5v17h5a2 2 0 0 1 2 2z"/>',
}

LOGO = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
        'stroke-linecap="round" stroke-linejoin="round"><path d="M4 18 9 9l4 6 3-4 4 7"/></svg>')
_COLLAPSE = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
             'stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></svg>')
_SHARE = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
          'stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/>'
          '<path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>')
_UP = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" '
       'stroke-linecap="round" stroke-linejoin="round"><path d="m6 15 6-6 6 6"/></svg>')


def icon(key: str) -> str:
    """메뉴·탭바에서 쓰는 선 아이콘(레퍼런스와 같은 24×24 · 선 2px)."""
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS.get(key, "")}</svg>')


_icon = icon   # 옛 이름(portalstyle._icon) 호환


def views_js() -> str:
    """JS 쪽에서 쓰는 하위 화면 정의 — 파이썬 정의를 한 곳에서 내려보낸다(중복 금지)."""
    return json.dumps(dict(views=[list(v) for v in VIEWS], icons=ICONS),
                      ensure_ascii=False, separators=(",", ":"))


def _group_of(label: str) -> str:
    for g, items in NAV_GROUPS:
        if any(lb == label for lb, _, _ in items):
            return g
    return ""


def _menu(active: str, sub: bool, hub: bool) -> str:
    """왼쪽 세로 메뉴 본문. hub=True 면 링크 대신 **안쪽 문서를 바꾸는 버튼**."""
    out = []
    for g, items in NAV_GROUPS:
        out.append(f'<div class="grp">{g}</div>')
        for label, fname, ico in items:
            inner = f'{icon(ico)}<span class="lbl">{label}</span>'
            if hub:
                cur = ' aria-current="page"' if label == active else ""
                out.append(f'<button class="navi" data-doc="{fname}" title="{label}"{cur}>{inner}</button>')
            elif label == active:
                # 자기 자신으로 가는 링크는 눌러도 제자리라 고장처럼 보인다 → 표시만 한다
                out.append(f'<span class="navi" aria-current="page" title="{label}">{inner}</span>')
                if sub:
                    out.append('<div class="subnav" id="tabs" aria-label="화면"></div>')
            else:
                out.append(f'<a class="navi" href="{fname}" title="{label}">{inner}</a>')
    return "".join(out)


def _tabbar(active: str, hub: bool) -> str:
    """휴대폰 하단 탭바 — 문서 6종(레퍼런스의 6칸 그대로)."""
    out = []
    for _, items in NAV_GROUPS:
        for label, fname, ico in items:
            inner = f'{icon(ico)}<span>{SHORT.get(label, label)}</span>'
            if hub:
                cur = ' aria-selected="true"' if label == active else ' aria-selected="false"'
                out.append(f'<button role="tab" data-doc="{fname}"{cur}>{inner}</button>')
            elif label == active:
                out.append(f'<span aria-current="page">{inner}</span>')
            else:
                out.append(f'<a href="{fname}">{inner}</a>')
    return f'<nav class="tabbar" id="tabbar" aria-label="문서">{"".join(out)}</nav>'


def _shell_open(active: str, *, sub: bool = False, hub: bool = False, today: str = "",
                where: str = "", state: str = "") -> str:
    """레퍼런스 틀(.shell = 왼쪽 메뉴 + 오른쪽 화면)을 **연다**. 닫는 것은 foot()."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    grp = _group_of(active)
    where = where or (f'품위추적 › {grp + " › " if grp else ""}<b>{active}</b>' if active else "품위추적")
    upd = state or ('<b><i></i>파이프라인 실행 때 갱신</b>재현 <code>python scripts/run_all.py</code>')
    return f"""{_tabbar(active, hub)}
<div class="shell" id="shell">
<aside class="side" aria-label="메뉴">
  <div class="brand"><span class="logo">{LOGO}</span><span class="txt">Blue365 <small>석회석</small></span>
    <button class="collapse" id="collapse" aria-label="메뉴 접기" title="메뉴 접기">{_COLLAPSE}</button></div>
  <div class="ws" title="석회석 광산 → OSP → 야드 품위 추적 · 조회 전용"><span class="av">품</span><div><b>품위 추적</b><small>보는용 · 조회 전용</small></div></div>
  <nav id="docnav" aria-label="문서">{_menu(active, sub, hub)}</nav>
  <div class="spacer"></div>
  <div class="upd" id="upd">{upd}</div>
</aside>
<div class="mainc">
<header class="top" id="top">
  <div class="wrap">
    <div class="bar">
      <div class="mbrand"><span class="logo">{LOGO}</span>Blue365</div>
      <div class="where" id="where">{where}</div>
      <span class="tag">보는용</span>
      <span class="grow"></span>
      <span class="refchip" id="refchip"><i></i>기준일 {today}</span>
      <button class="iconbtn" id="share" aria-label="공유">{_SHARE}<span>공유</span></button>
    </div>
  </div>
</header>"""


def nav(active: str = "", user: str = "", *, sub: bool = False, today: str = "") -> str:
    """QMS 틀을 열고 왼쪽 세로 메뉴·머리 줄·휴대폰 탭바를 그린다.

    ⚠️ **foot() 과 짝이다.** nav() 가 `.shell`·`.mainc` 를 열고 foot() 이 닫는다.
       문서 본문은 그 사이에 그대로 쓴다(종전 포털 스타일과 같은 호출 순서 — 소비처를
       고치지 않고 틀만 바꾸기 위해서다). 짝을 빼먹어도 브라우저가 </body> 에서 닫아 준다.
    `sub=True` 면 현재 항목 아래에 하위 화면 자리(#tabs)를 둔다(운영 현황판 전용).
    `user` 는 옛 서명 호환용으로 받기만 한다.
    """
    return _shell_open(active, sub=sub, today=today)


def nav_hub(active: str = "") -> str:
    """단일 파일 허브용 틀 — 메뉴가 링크가 아니라 **안쪽 문서를 바꾸는 버튼**이다.

    산출물을 낱개로 받으면 옆 파일이 없어 상대경로 링크가 먹통이 된다(2026-10-21 지적).
    허브는 문서들을 한 파일 안에 품고 있으므로 이동이 아니라 교체다.
    """
    return _shell_open(active, hub=True,
                       state='<b><i></i>한 파일에 모두 담김</b><span id="hubstate"></span>')


def hero(eyebrow: str, title: str, lead: str, strip: str = "",
         today: str = "", quick: list | None = None) -> str:
    """화면 머리 — 레퍼런스의 `알약 꼬리표 + 큰 두 줄 제목(핵심 단어만 파랑) + 설명`.

    종전 포털의 남색 밴드 자리다. 서명은 그대로 두어 소비처를 고치지 않는다.
    `today` 는 머리 줄 기준일 칩이 맡으므로 여기서는 쓰지 않는다.
    """
    st = f'<div class="pgstrip"><span class="tag mute">{strip}</span></div>' if strip else ""
    qs = "".join(f'<a href="#{a}">{icon(i)}{n}</a>' for n, i, a in (quick or []))
    qk = f'<div class="pgquick">{qs}</div>' if qs else ""
    return f"""<div class="wrap pg"><div>
  <span class="tag">{eyebrow}</span>
  <h1 class="hl">{title}</h1>
  <p class="lead">{lead}</p>
  {st}{qk}
</div></div>"""


#: 틀 공통 동작 — 메뉴 접기 · 머리 줄 그림자 · 맨 위로 · 공유. (대시보드도 이걸 쓴다)
SHELL_JS = r"""
(() => {
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 저장 불가 환경 */ } },
  };
  const shell = $('shell'), col = $('collapse');
  const setMini = (on) => {
    if (!shell || !col) return;
    shell.classList.toggle('mini', on);
    const t = on ? '메뉴 펼치기' : '메뉴 접기';
    col.setAttribute('aria-label', t); col.title = t;
    store.set('b365_side_mini', on ? '1' : '');
  };
  if (col) col.addEventListener('click', () => setMini(!shell.classList.contains('mini')));
  if (store.get('b365_side_mini')) setMini(true);

  let toastT;
  window.b365toast = (msg) => {
    const t = $('toast'); if (!t) return;
    t.textContent = msg; t.classList.add('on');
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 2000);
  };
  const top = $('top'), fab = $('fab');
  addEventListener('scroll', () => {
    if (top) top.classList.toggle('scrolled', scrollY > 4);
    if (fab) fab.classList.toggle('on', scrollY > 600);
  }, {passive: true});
  if (fab) fab.addEventListener('click', () => scrollTo({
    top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}));

  const sh = $('share');
  if (sh) sh.addEventListener('click', async () => {
    const url = location.href, isFile = location.protocol === 'file:';
    if (!isFile && navigator.share) {
      try { await navigator.share({title: document.title, url}); return; }
      catch (e) { if (e && e.name === 'AbortError') return; }
    }
    const text = isFile ? decodeURI(location.pathname.replace(/^\/([A-Za-z]:)/, '$1')).replace(/\//g, '\\') : url;
    try { await navigator.clipboard.writeText(text); window.b365toast(isFile ? '파일 위치를 복사했어요' : '링크를 복사했어요'); }
    catch (e) { window.b365toast('복사가 막혀 있어요 — 주소창의 주소를 복사해 주세요'); }
  });
})();
"""


def foot(text: str) -> str:
    """바닥글을 쓰고 nav() 가 연 틀을 **닫는다**. 맨 위로 버튼·토스트·틀 동작을 붙인다."""
    return f"""<div class="wrap ft"><footer><div>{text}</div></footer></div>
</div>
</div>
<button class="fab" id="fab" aria-label="맨 위로">{_UP}</button>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>{SHELL_JS}</script>"""
