"""리포트 공통 스타일 [Synthesis-Agent].

`make_brief.py`(현황)와 `make_prescription.py`(처방)가 **같은 시각 언어**를 쓰도록
토큰과 기본 컴포넌트를 한곳에 둔다.

⭐️ 2026-09-03 개편 — 사용자가 제시한 관제 대시보드 스타일에 맞춘다.
  · 서체: **IBM Plex Sans KR**(본문) + **IBM Plex Mono**(수치). 숫자를 모노로 두면 자릿수가
    맞아떨어져 표·KPI 가 훨씬 정돈돼 보인다. 폰트를 못 받아도 무너지지 않게 대체 스택을 둔다.
  · 색: 따뜻한 석회석 톤 → **차가운 청회색**. 바탕 #f4f7fb, 강조 #1c5cab.
  · 라벨: 작은 대문자 + 자간(`.08em`), 값은 크게. 카드는 radius 10 + 2단 그림자.
  · 탭/칩: 알약형 버튼이 아니라 **밑줄형 탭**과 얇은 테두리 칩.

라이트/다크 세 상태(명시 선택 2 + 시스템 기본 1)를 모두 커버한다 — 어느 한 상태에서만
정의된 색이 있으면 반대 테마에서 글자가 바탕에 묻힌다.

⚠️ 이 파일은 f-string 이 아니다. 중괄호를 이스케이프하지 말 것.
"""

STYLE = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&display=swap');

:root {
  color-scheme: light;
  --ground:#f4f7fb; --surface:#ffffff; --surface-2:#eef4fc; --surface-3:#e2ecf8;
  --ink:#101c2c; --ink-2:#4d6076; --ink-3:#8496a9;
  --line:#dbe5f1; --line-2:#c6d5e8;
  --accent:#1c5cab; --accent-2:#2a78d6; --accent-soft:#e6effb; --accent-ink:#14477f;
  --good:#0ca30c; --warn:#a6740a; --bad:#d03b3b;
  --band:#e6effb; --warnfill:#fdf0d2; --badfill:#f2c3bd; --bar:#b7d3f6;
  --grid:#e9f0f8;
  --shadow:0 1px 2px rgba(16,40,72,.06), 0 8px 24px -16px rgba(16,40,72,.28);
  --radius:10px;
  /* 이전 이름 호환 */
  --paper:var(--ground); --muted:var(--ink-2); --rule:var(--line);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground:#0b121c; --surface:#131d2a; --surface-2:#18242f; --surface-3:#1f2d3d;
    --ink:#eaf1f9; --ink-2:#9fb2c6; --ink-3:#6d8199;
    --line:#243448; --line-2:#31465e;
    --accent:#3987e5; --accent-2:#5598e7; --accent-soft:#16263c; --accent-ink:#9ec5f4;
    --good:#4fb84f; --warn:#fab219; --bad:#e0685f;
    --band:#16263c; --warnfill:#3a2f10; --badfill:#5c2b26; --bar:#365981;
    --grid:#1d2b3c;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.8);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground:#0b121c; --surface:#131d2a; --surface-2:#18242f; --surface-3:#1f2d3d;
  --ink:#eaf1f9; --ink-2:#9fb2c6; --ink-3:#6d8199;
  --line:#243448; --line-2:#31465e;
  --accent:#3987e5; --accent-2:#5598e7; --accent-soft:#16263c; --accent-ink:#9ec5f4;
  --good:#4fb84f; --warn:#fab219; --bad:#e0685f;
  --band:#16263c; --warnfill:#3a2f10; --badfill:#5c2b26; --bar:#365981;
  --grid:#1d2b3c;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.8);
}
:root[data-theme="light"] {
  color-scheme: light;
  --ground:#f4f7fb; --surface:#ffffff; --surface-2:#eef4fc; --surface-3:#e2ecf8;
  --ink:#101c2c; --ink-2:#4d6076; --ink-3:#8496a9;
  --line:#dbe5f1; --line-2:#c6d5e8;
  --accent:#1c5cab; --accent-2:#2a78d6; --accent-soft:#e6effb; --accent-ink:#14477f;
  --good:#0ca30c; --warn:#a6740a; --bad:#d03b3b;
  --band:#e6effb; --warnfill:#fdf0d2; --badfill:#f2c3bd; --bar:#b7d3f6;
  --grid:#e9f0f8;
  --shadow:0 1px 2px rgba(16,40,72,.06), 0 8px 24px -16px rgba(16,40,72,.28);
}

* { box-sizing:border-box; }
body {
  background:var(--ground); color:var(--ink); margin:0;
  font-family:'IBM Plex Sans KR','Pretendard','Apple SD Gothic Neo','Malgun Gothic',
    system-ui,-apple-system,sans-serif;
  font-size:14px; line-height:1.65; -webkit-font-smoothing:antialiased;
}
.mono, .kv, table.t td.n, table.t th.n, .pmeta b {
  font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums;
}
.wrap { max-width:980px; margin:0 auto; padding:34px 22px 64px;
        display:flex; flex-direction:column; gap:34px; }

/* ── 머리말 ─────────────────────────────────────────── */
.top { display:flex; flex-direction:column; gap:10px;
       border-bottom:1px solid var(--line); padding-bottom:18px; }
.eyebrow { font-size:10.5px; letter-spacing:.14em; text-transform:uppercase;
           color:var(--ink-3); font-weight:600; }
h1 { font-size:26px; line-height:1.3; font-weight:600; letter-spacing:-.02em;
     margin:0; text-wrap:balance; }
.thesis { font-size:14.5px; line-height:1.7; color:var(--ink-2); margin:0; max-width:70ch; }
.thesis strong { color:var(--ink); font-weight:600; }
.meta { font-size:11.5px; color:var(--ink-3); letter-spacing:.01em; }

/* ── KPI ────────────────────────────────────────────── */
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:12px; }
.k { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
     padding:13px 15px 12px; box-shadow:var(--shadow);
     display:flex; flex-direction:column; gap:3px; min-width:0; }
.kv { font-size:25px; font-weight:600; letter-spacing:-.02em; line-height:1.15; }
.ku { font-size:13px; font-weight:400; color:var(--ink-2); margin-left:2px;
      font-family:'IBM Plex Sans KR',sans-serif; }
.kl { font-size:10.5px; letter-spacing:.08em; text-transform:uppercase;
      color:var(--ink-3); font-weight:600; margin-top:3px; }
.kn { font-size:11.5px; color:var(--ink-2); line-height:1.5; }
.k.good .kv { color:var(--good); }
.k.bad  .kv { color:var(--bad); }
.k.warn .kv { color:var(--warn); }

/* ── 섹션 ───────────────────────────────────────────── */
section { display:flex; flex-direction:column; gap:12px; }
section > h2 { font-size:10.5px; letter-spacing:.14em; text-transform:uppercase;
               color:var(--ink-3); font-weight:600; margin:0;
               padding-bottom:9px; border-bottom:1px solid var(--line); }
.q { font-size:18px; font-weight:600; letter-spacing:-.015em; margin:0; text-wrap:balance; }
.a { font-size:14.5px; margin:0; max-width:70ch; color:var(--ink-2); line-height:1.7; }
.a strong { color:var(--accent); font-weight:600; }
p.note { font-size:12.5px; color:var(--ink-3); margin:0; max-width:74ch; line-height:1.65; }
p.note b { color:var(--ink-2); font-weight:600; }

/* ── 카드 · 표 ──────────────────────────────────────── */
.card { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
        padding:16px 18px 18px; box-shadow:var(--shadow); overflow-x:auto; }
svg.chart { display:block; width:100%; height:auto; }
.ax { font-size:10px; fill:var(--ink-3); }
.ct { font-size:12px; fill:var(--ink); font-weight:600; }
.cs { font-size:10.5px; fill:var(--ink-3); }
.inb { font-size:11px; fill:var(--surface); font-weight:600; }
.inw { font-size:11px; fill:var(--ink); font-weight:600; }
table.t { border-collapse:collapse; width:100%; font-size:12.5px; }
table.t th { text-align:left; font-weight:600; font-size:10.5px; letter-spacing:.06em;
             text-transform:uppercase; color:var(--ink-3);
             border-bottom:1px solid var(--line-2); padding:8px 10px; white-space:nowrap; }
table.t td { padding:9px 10px; border-bottom:1px solid var(--grid); color:var(--ink-2); }
table.t td b, table.t td strong { color:var(--ink); }
table.t tr:last-child td { border-bottom:none; }
table.t td.n, table.t th.n { text-align:right; }
table.t td.c { text-align:center; color:var(--good); font-weight:600; }

/* ── 현장 인용 · 요청 목록 ──────────────────────────── */
.said { background:var(--surface); border:1px solid var(--line);
        border-left:3px solid var(--warn); border-radius:var(--radius);
        padding:13px 16px; font-size:13px; color:var(--ink-2); line-height:1.7; }
.said .lbl { display:block; font-size:10.5px; letter-spacing:.1em; text-transform:uppercase;
             color:var(--warn); margin-bottom:6px; font-weight:600; }
.said b { color:var(--ink); font-weight:600; }
ol.asks { margin:0; padding-left:0; list-style:none; counter-reset:a;
          display:flex; flex-direction:column; gap:11px; }
ol.asks li { display:grid; grid-template-columns:24px 1fr; gap:12px; align-items:start;
             font-size:14px; color:var(--ink); }
ol.asks li::before { counter-increment:a; content:counter(a);
   font-family:'IBM Plex Mono',monospace; font-size:11px; font-weight:600;
   color:var(--accent-ink); background:var(--accent-soft);
   border:1px solid var(--accent-2); width:22px; height:22px; border-radius:6px;
   display:grid; place-items:center; margin-top:2px; }
ol.asks b { font-weight:600; }
ol.asks .w { display:block; font-size:12.5px; color:var(--ink-3); margin-top:3px; line-height:1.6; }

footer { border-top:1px solid var(--line); padding-top:16px; font-size:11.5px;
         color:var(--ink-3); line-height:1.75; }
code { font-family:'IBM Plex Mono',monospace; font-size:11px;
       background:var(--surface-2); border:1px solid var(--line);
       padding:1px 5px; border-radius:4px; color:var(--ink-2); }
@media (max-width:560px) { h1 { font-size:22px; } .q { font-size:16px; } .kv { font-size:22px; } }
"""
