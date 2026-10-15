"""사내 포털 스타일 [Synthesis-Agent] — 2026-10-15 사용자 제시 레퍼런스(그룹 인트라넷).

⭐️ 왜 바꾸나: 이 산출물들은 결국 **사내에서 돌려 보는 문서**다. 사람들이 매일 보는 그룹
포털과 같은 시각 언어를 쓰면 "외부에서 온 리포트" 가 아니라 **우리 시스템의 화면**으로 읽힌다.

레퍼런스에서 가져온 것:
  · **흰 상단 바** — 로고 + 가로 메뉴 + 우측 유틸리티. 아래 1px 경계선.
  · **남색 히어로 밴드** — 그 안에 좌(넓은 배너) · 우(TODAY + 빠른 이동) 2단.
  · **연회색 바탕(#eef0f4) 위의 흰 카드** — 테두리 1px, 그림자는 거의 없고, radius 4.
  · **밑줄형 탭 머리말** — 활성 탭만 진하게 + 파란 밑줄, 우측에 ＋ 버튼.
  · **촘촘한 목록 행** — `• 제목 ……… 작성자  날짜`. 제목은 넘치면 말줄임.
  · **알약형 필터 칩** — 활성은 파란 채움, 비활성은 회색 테두리.
  · **빨간 N 배지** — 새 항목 표시.

⚠️ 토큰 **이름은 종전과 동일**하게 유지한다(`--accent`·`--bar`·`--grid` 등). 기존 SVG 차트와
   표가 그 이름을 쓰고 있어, 이름을 바꾸면 그림이 통째로 깨진다. 값만 갈아끼운다.

⚠️ 이 파일은 f-string 이 아니다. 중괄호를 이스케이프하지 말 것.
"""

STYLE = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap');

:root {
  color-scheme: light;
  /* 바탕 — 연회색 페이지 위 흰 카드 */
  --ground:#eef0f4; --surface:#ffffff; --surface-2:#f5f7fa; --surface-3:#e9edf3;
  /* 글자 */
  --ink:#1b2430; --ink-2:#5a6676; --ink-3:#98a1ae;
  /* 선 */
  --line:#e2e6ec; --line-2:#d2d8e1;
  /* 강조 — 포털 파랑 */
  --accent:#1a62d8; --accent-2:#2f7de1; --accent-soft:#e8f0fd; --accent-ink:#154fae;
  /* 상단 바 · 히어로 밴드 */
  --nav:#ffffff; --nav-ink:#2b3444; --nav-line:#e4e7ec;
  --hero:#2f3947; --hero-2:#28313d; --hero-ink:#ffffff; --hero-ink-2:#aeb8c6;
  --brand:#0b2d6b; --new:#e8402e;
  /* 상태 */
  --good:#13925a; --warn:#b4730c; --bad:#d8392b;
  --band:#e8f0fd; --warnfill:#fdf2da; --badfill:#f6cdc8; --bar:#b9d2f5;
  --grid:#edf0f5;
  /* 계열색 — 선 그래프에서 두 라인을 가르는 색. `--bar`(막대 채움)는 선으로 쓰기엔 너무 옅다. */
  --series-1:#1a62d8; --series-2:#64748b;
  --shadow:0 1px 2px rgba(27,36,48,.05);
  --radius:4px;
  /* 이전 이름 호환 */
  --paper:var(--ground); --muted:var(--ink-2); --rule:var(--line);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground:#121821; --surface:#1a222e; --surface-2:#202936; --surface-3:#273241;
    --ink:#e9eef5; --ink-2:#a3aeba; --ink-3:#727f8e;
    --line:#2a3542; --line-2:#374455;
    --accent:#4d94f0; --accent-2:#6aa6f3; --accent-soft:#17283f; --accent-ink:#a8caf7;
    --nav:#1a222e; --nav-ink:#e9eef5; --nav-line:#2a3542;
    --hero:#161d27; --hero-2:#11171f; --hero-ink:#e9eef5; --hero-ink-2:#8e9aa8;
    --brand:#8fb6f2; --new:#f06a5b;
    --good:#3cb87e; --warn:#e0a53a; --bad:#eb6d60;
    --band:#17283f; --warnfill:#3a2f12; --badfill:#5a2d27; --bar:#36598a;
    --grid:#222c39;
    --series-1:#4d94f0; --series-2:#94a3b3;
    --shadow:0 1px 2px rgba(0,0,0,.45);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground:#121821; --surface:#1a222e; --surface-2:#202936; --surface-3:#273241;
  --ink:#e9eef5; --ink-2:#a3aeba; --ink-3:#727f8e;
  --line:#2a3542; --line-2:#374455;
  --accent:#4d94f0; --accent-2:#6aa6f3; --accent-soft:#17283f; --accent-ink:#a8caf7;
  --nav:#1a222e; --nav-ink:#e9eef5; --nav-line:#2a3542;
  --hero:#161d27; --hero-2:#11171f; --hero-ink:#e9eef5; --hero-ink-2:#8e9aa8;
  --brand:#8fb6f2; --new:#f06a5b;
  --good:#3cb87e; --warn:#e0a53a; --bad:#eb6d60;
  --band:#17283f; --warnfill:#3a2f12; --badfill:#5a2d27; --bar:#36598a;
  --grid:#222c39;
  --series-1:#4d94f0; --series-2:#94a3b3;
  --shadow:0 1px 2px rgba(0,0,0,.45);
}
:root[data-theme="light"] {
  color-scheme: light;
  --ground:#eef0f4; --surface:#ffffff; --surface-2:#f5f7fa; --surface-3:#e9edf3;
  --ink:#1b2430; --ink-2:#5a6676; --ink-3:#98a1ae;
  --line:#e2e6ec; --line-2:#d2d8e1;
  --accent:#1a62d8; --accent-2:#2f7de1; --accent-soft:#e8f0fd; --accent-ink:#154fae;
  --nav:#ffffff; --nav-ink:#2b3444; --nav-line:#e4e7ec;
  --hero:#2f3947; --hero-2:#28313d; --hero-ink:#ffffff; --hero-ink-2:#aeb8c6;
  --brand:#0b2d6b; --new:#e8402e;
  --good:#13925a; --warn:#b4730c; --bad:#d8392b;
  --band:#e8f0fd; --warnfill:#fdf2da; --badfill:#f6cdc8; --bar:#b9d2f5;
  --grid:#edf0f5;
  /* 계열색 — 선 그래프에서 두 라인을 가르는 색. `--bar`(막대 채움)는 선으로 쓰기엔 너무 옅다. */
  --series-1:#1a62d8; --series-2:#64748b;
  --shadow:0 1px 2px rgba(27,36,48,.05);
}

* { box-sizing:border-box; }
body {
  background:var(--ground); color:var(--ink); margin:0;
  font-family:'Noto Sans KR','Pretendard','Apple SD Gothic Neo','Malgun Gothic',
    system-ui,-apple-system,sans-serif;
  font-size:14px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
.mono, .kv, table.t td.n, table.t th.n, .pmeta b {
  font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums;
}

/* ── 상단 바 ────────────────────────────────────────── */
.nav { background:var(--nav); border-bottom:1px solid var(--nav-line); }
.nav-in { max-width:1280px; margin:0 auto; padding:0 20px; height:58px;
          display:flex; align-items:center; gap:28px; }
.logo { display:flex; align-items:center; gap:9px; font-weight:700; font-size:17px;
        letter-spacing:-.02em; color:var(--brand); white-space:nowrap; }
.logo .dot { width:9px; height:9px; border-radius:2px; background:var(--accent);
             box-shadow:0 0 0 3px var(--accent-soft); }
.logo .sub { font-weight:500; font-size:14px; color:var(--nav-ink); }
.nav-menu { display:flex; align-items:center; gap:4px; flex:1; min-width:0;
            overflow-x:auto; scrollbar-width:none; }
.nav-menu::-webkit-scrollbar { display:none; }
.nav-menu a, .nav-menu span { display:flex; align-items:center; gap:6px; padding:8px 11px;
              border-radius:4px; font-size:13.5px; font-weight:500; color:var(--nav-ink);
              text-decoration:none; white-space:nowrap; }
.nav-menu a:hover { background:var(--surface-2); color:var(--accent); }
.nav-menu a:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.nav-menu .on { color:var(--accent); font-weight:700; background:var(--accent-soft); }
.nav-menu .ico { width:17px; height:17px; flex:none; }
.nav-util { display:flex; align-items:center; gap:14px; font-size:12.5px;
            color:var(--ink-2); white-space:nowrap; }
.nav-util b { color:var(--nav-ink); font-weight:600; }

/* ── 히어로 밴드 ────────────────────────────────────── */
.hero { background:var(--hero); }
.hero-in { max-width:1280px; margin:0 auto; padding:26px 20px 30px;
           display:grid; grid-template-columns:minmax(0,1.85fr) minmax(0,1fr); gap:18px;
           align-items:stretch; }
/* 우측 패널이 없는 문서형 산출물 — 배너가 한 칸만 차지해 잘린 것처럼 보이면 안 된다. */
.hero-in.solo { grid-template-columns:1fr; }
.hero-in.solo .hero-card { padding:28px 32px; }
.hero-in.solo .hero-card h1, .hero-in.solo .lead { max-width:66ch; }
.hero-card { background:linear-gradient(135deg,var(--accent) 0%,#0d4bb0 100%);
             border-radius:var(--radius); padding:26px 28px; color:#fff;
             display:flex; flex-direction:column; gap:12px; justify-content:center;
             position:relative; overflow:hidden; }
.hero-card::after { content:''; position:absolute; right:-70px; bottom:-90px;
                    width:260px; height:260px; border-radius:50%;
                    background:rgba(255,255,255,.07); }
.hero-eyebrow { font-size:11.5px; letter-spacing:.12em; font-weight:600;
                color:rgba(255,255,255,.78); text-transform:uppercase; }
.hero-card h1 { margin:0; font-size:27px; line-height:1.34; font-weight:700;
                letter-spacing:-.025em; text-wrap:balance; color:#fff; }
.hero-card h1 em { font-style:normal; background:rgba(255,255,255,.17);
                   padding:0 9px; border-radius:3px; }
.hero-card .lead { margin:0; font-size:14px; line-height:1.7; color:rgba(255,255,255,.9);
                   max-width:62ch; position:relative; }
.hero-strip { margin-top:4px; align-self:flex-start; background:rgba(0,0,0,.26);
              border-radius:99px; padding:7px 18px; font-size:12.5px; font-weight:500;
              position:relative; }
.hero-side { background:var(--surface); border-radius:var(--radius); padding:16px 17px;
             display:flex; flex-direction:column; gap:13px; }
.today { display:flex; align-items:center; gap:8px; font-size:12.5px; font-weight:600;
         color:var(--ink-2); letter-spacing:.02em; }
.today .led { width:7px; height:7px; border-radius:50%; background:var(--accent);
              box-shadow:0 0 0 3px var(--accent-soft); flex:none; }
.quick { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px;
         background:var(--line); border:1px solid var(--line); border-radius:var(--radius);
         overflow:hidden; }
.quick a { background:var(--surface); padding:12px 10px; text-decoration:none;
           display:flex; flex-direction:column; align-items:center; gap:6px;
           font-size:12px; font-weight:500; color:var(--ink-2); text-align:center; }
.quick a:hover { background:var(--surface-2); color:var(--accent); }
.quick .qi { width:30px; height:30px; border-radius:8px; background:var(--accent-soft);
             display:grid; place-items:center; }
.quick .qi svg { width:17px; height:17px; }

/* ── 본문 틀 ────────────────────────────────────────── */
.wrap { max-width:1280px; margin:0 auto; padding:22px 20px 44px;
        display:flex; flex-direction:column; gap:18px; }
.wrap.doc { max-width:1000px; }

/* ── 패널(카드) ─────────────────────────────────────── */
.panel, .card { background:var(--surface); border:1px solid var(--line);
                border-radius:var(--radius); box-shadow:var(--shadow); }
.panel { padding:0; display:flex; flex-direction:column; min-width:0; }
.card { padding:15px 17px 16px; overflow-x:auto; }
.phd { display:flex; align-items:center; gap:10px; padding:0 15px;
       border-bottom:1px solid var(--line); min-height:46px; flex-wrap:wrap; }
.phd h3 { margin:0; font-size:14.5px; font-weight:700; letter-spacing:-.01em;
          color:var(--ink); display:flex; align-items:center; gap:7px; }
.phd .sp { flex:1; }
.pbd { padding:14px 15px 16px; min-width:0; }

/* ── 밑줄형 탭 ──────────────────────────────────────── */
.tabs { display:flex; align-items:stretch; gap:2px; margin-bottom:-1px; }
.tabs button, .tabs a { background:none; border:0; font:inherit; cursor:pointer;
       padding:13px 14px 11px; font-size:14px; font-weight:500; color:var(--ink-3);
       border-bottom:2px solid transparent; text-decoration:none; white-space:nowrap; }
.tabs .on { color:var(--ink); font-weight:700; border-bottom-color:var(--accent); }

/* ── 칩 · 배지 ──────────────────────────────────────── */
.chip { font:inherit; cursor:pointer; font-size:12px; font-weight:500; padding:4px 11px;
        border-radius:99px; border:1px solid var(--line-2); background:var(--surface);
        color:var(--ink-2); white-space:nowrap; }
.chip:hover { border-color:var(--accent-2); color:var(--accent); }
.chip.on { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
.tag { font-size:11px; font-weight:600; padding:2px 8px; border-radius:3px;
       background:var(--accent-soft); color:var(--accent-ink); white-space:nowrap; }
.tag.mute { background:var(--surface-3); color:var(--ink-3); font-weight:500; }
.tag.good { background:#e3f5ec; color:var(--good); }
.tag.warn { background:var(--warnfill); color:var(--warn); }
.tag.bad  { background:var(--badfill); color:var(--bad); }
.new { display:inline-grid; place-items:center; width:14px; height:14px; border-radius:50%;
       background:var(--new); color:#fff; font-size:9px; font-weight:700; line-height:1;
       vertical-align:1px; }
.plus { width:22px; height:22px; border-radius:50%; border:1px solid var(--line-2);
        background:var(--surface); color:var(--ink-3); font-size:14px; line-height:1;
        display:grid; place-items:center; cursor:pointer; flex:none; }
.plus:hover { border-color:var(--accent-2); color:var(--accent); }

/* ── 촘촘한 목록 ────────────────────────────────────── */
ul.feed { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; }
ul.feed li { display:flex; align-items:center; gap:10px; padding:7px 0; font-size:13px;
             border-bottom:1px dashed var(--grid); }
ul.feed li:last-child { border-bottom:0; }
ul.feed .t { flex:1; min-width:0; color:var(--ink); overflow:hidden;
             text-overflow:ellipsis; white-space:nowrap; }
ul.feed .t::before { content:'·'; color:var(--accent); font-weight:700; margin-right:7px; }
ul.feed .t b { font-weight:600; }
ul.feed .who { font-size:11.5px; color:var(--ink-2); white-space:nowrap; }
ul.feed .d { font-size:11.5px; color:var(--ink-3); white-space:nowrap;
             font-family:'IBM Plex Mono',monospace; }

/* ── KPI 타일 ───────────────────────────────────────── */
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(164px,1fr)); gap:12px; }
/* 패널 안에서는 칸이 어중간하게 3+1 로 깨지지 않게 2열로 고정한다 */
.kpis.two { grid-template-columns:repeat(2,minmax(0,1fr)); }
@media (max-width:420px) { .kpis.two { grid-template-columns:1fr; } }
.k { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
     padding:13px 15px 12px; box-shadow:var(--shadow);
     display:flex; flex-direction:column; gap:2px; min-width:0; }
.kv { font-size:24px; font-weight:600; letter-spacing:-.02em; line-height:1.2; }
.ku { font-size:13px; font-weight:400; color:var(--ink-2); margin-left:2px;
      font-family:'Noto Sans KR',sans-serif; }
.kl { font-size:11px; letter-spacing:.04em; color:var(--ink-3); font-weight:600; margin-top:3px; }
.kn { font-size:11.5px; color:var(--ink-2); line-height:1.5; }
.k.good .kv { color:var(--good); }
.k.bad  .kv { color:var(--bad); }
.k.warn .kv { color:var(--warn); }

/* ── 문서용 본문 ────────────────────────────────────── */
section { display:flex; flex-direction:column; gap:12px; }
section > h2 { font-size:11px; letter-spacing:.1em; color:var(--ink-3); font-weight:700;
               margin:0; padding-bottom:9px; border-bottom:1px solid var(--line); }
.q { font-size:18px; font-weight:700; letter-spacing:-.02em; margin:0; text-wrap:balance; }
.a { font-size:14.5px; margin:0; max-width:72ch; color:var(--ink-2); line-height:1.75; }
.a strong { color:var(--accent); font-weight:600; }
p.note { font-size:12.5px; color:var(--ink-3); margin:0; max-width:76ch; line-height:1.7; }
p.note b { color:var(--ink-2); font-weight:600; }
.hint { font-size:11.5px; color:var(--ink-3); margin:8px 0 0; line-height:1.6; }
.empty { font-size:12.5px; color:var(--ink-3); padding:18px 0; text-align:center; }

/* ── 차트 · 표 ──────────────────────────────────────── */
svg.chart { display:block; width:100%; height:auto; }
.ax { font-size:10px; fill:var(--ink-3); }
.ct { font-size:12px; fill:var(--ink); font-weight:600; }
.cs { font-size:10.5px; fill:var(--ink-3); }
.inb { font-size:11px; fill:var(--surface); font-weight:600; }
.inw { font-size:11px; fill:var(--ink); font-weight:600; }
.tbl { overflow-x:auto; }
table.t { border-collapse:collapse; width:100%; font-size:12.5px; }
table.t th { text-align:left; font-weight:600; font-size:11px; letter-spacing:.03em;
             color:var(--ink-3); background:var(--surface-2);
             border-bottom:1px solid var(--line-2); padding:8px 10px; white-space:nowrap; }
table.t td { padding:8px 10px; border-bottom:1px solid var(--grid); color:var(--ink-2); }
table.t td b, table.t td strong { color:var(--ink); }
table.t tr:last-child td { border-bottom:none; }
table.t td.n, table.t th.n { text-align:right; }
table.t td.c { text-align:center; color:var(--good); font-weight:600; }

/* ── 현장 인용 · 요청 목록 ──────────────────────────── */
.said { background:var(--surface); border:1px solid var(--line);
        border-left:3px solid var(--warn); border-radius:var(--radius);
        padding:13px 16px; font-size:13px; color:var(--ink-2); line-height:1.75; }
.said .lbl { display:block; font-size:11px; letter-spacing:.06em; color:var(--warn);
             margin-bottom:6px; font-weight:700; }
.said b { color:var(--ink); font-weight:600; }
ol.asks { margin:0; padding-left:0; list-style:none; counter-reset:a;
          display:flex; flex-direction:column; gap:11px; }
ol.asks li { display:grid; grid-template-columns:24px 1fr; gap:12px; align-items:start;
             font-size:14px; color:var(--ink); }
ol.asks li::before { counter-increment:a; content:counter(a);
   font-family:'IBM Plex Mono',monospace; font-size:11px; font-weight:600; color:#fff;
   background:var(--accent); width:22px; height:22px; border-radius:4px;
   display:grid; place-items:center; margin-top:3px; }
ol.asks b { font-weight:600; }
ol.asks .w { display:block; font-size:12.5px; color:var(--ink-3); margin-top:3px; line-height:1.65; }

/* ── 바닥글 ─────────────────────────────────────────── */
.foot { border-top:1px solid var(--line); background:var(--surface); }
.foot-in { max-width:1280px; margin:0 auto; padding:18px 20px; font-size:11.5px;
           color:var(--ink-3); line-height:1.8; text-align:center; }
footer { border-top:1px solid var(--line); padding-top:16px; font-size:11.5px;
         color:var(--ink-3); line-height:1.75; }
code { font-family:'IBM Plex Mono',monospace; font-size:11px;
       background:var(--surface-2); border:1px solid var(--line);
       padding:1px 5px; border-radius:3px; color:var(--ink-2); }

/* ── 기존 마크업 호환 ───────────────────────────────── */
/* 종전 문서 머리말(.top). 히어로로 대체했지만 남아 있어도 깨지지 않게 둔다. */
.top { display:flex; flex-direction:column; gap:9px;
       border-bottom:1px solid var(--line); padding-bottom:16px; }
.eyebrow { font-size:11px; letter-spacing:.1em; color:var(--ink-3); font-weight:700; }
h1 { font-size:25px; line-height:1.35; font-weight:700; letter-spacing:-.025em;
     margin:0; text-wrap:balance; }
.thesis { font-size:14.5px; line-height:1.75; color:var(--ink-2); margin:0; max-width:72ch; }
.thesis strong { color:var(--ink); font-weight:600; }
.meta { font-size:11.5px; color:var(--ink-3); }
/* 대시보드 칩은 aria-pressed 로 상태를 표시한다 — 같은 모양이 되게 맞춘다. */
.chip[aria-pressed="true"] { background:var(--accent); border-color:var(--accent);
                             color:#fff; font-weight:600; }
/* 머리말 틀(.phd) 없이 바로 h3 를 쓰는 패널(대시보드)도 같은 모양으로 보이게 한다. */
.panel.plain { padding:0; gap:0; }
.panel.plain > h3 { margin:0; padding:13px 15px 11px; border-bottom:1px solid var(--line);
                    font-size:14.5px; font-weight:700; letter-spacing:-.01em;
                    display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.panel.plain > *:not(h3) { padding-left:15px; padding-right:15px; }
.panel.plain > h3 + * { padding-top:14px; }
.panel.plain > *:last-child { padding-bottom:15px; }

/* ── 격자 ───────────────────────────────────────────── */
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr)); gap:18px; }
.grid.wide { grid-template-columns:1fr; }
.grid.three { grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); }

@media (max-width:900px) {
  .hero-in { grid-template-columns:1fr; }
  .nav-util .hide-s { display:none; }
}
@media (max-width:560px) {
  .nav-in { height:52px; gap:14px; }
  .hero-card { padding:20px 18px; }
  .hero-card h1 { font-size:21px; }
  .q { font-size:16px; } .kv { font-size:21px; }
  .grid { grid-template-columns:1fr; }
}
"""

#: 상단 바 메뉴 — (라벨, 파일명, 아이콘).
#: ⭐️ **실제 링크다.** 산출물이 모두 `outputs/` 한 폴더에 나오므로 상대경로로 서로 이동한다.
#: (죽은 `href="#"` 로 두면 눌러도 아무 일이 없어 고장처럼 보인다 — 2026-10-15 실제 지적)
NAV_ITEMS = (
    ("현황 브리프", "brief.html", "chart"),
    ("배합 처방", "prescription.html", "flask"),
    ("운영 대시보드", "dashboard.html", "grid"),
    ("통합 리포트", "final_report.html", "doc"),
    ("운영 모니터", "monitor_status.html", "alert"),
    ("계획서", "plan.html", "map"),
)


def _icon(name: str) -> str:
    """상단 바·빠른이동용 인라인 SVG (외부 요청 없이 테마색을 따라간다)."""
    p = {
        "chart": "M3 17h3V9H3v8Zm5 0h3V4H8v13Zm5 0h3v-6h-3v6Z",
        "flask": "M8 2h4M9 2v6l-4 8a2 2 0 0 0 2 3h6a2 2 0 0 0 2-3l-4-8V2",
        "grid": "M3 3h7v7H3V3Zm8 0h7v7h-7V3ZM3 11h7v7H3v-7Zm8 0h7v7h-7v-7Z",
        "doc": "M5 2h7l4 4v13H5V2Zm7 0v4h4",
        "map": "M3 5l5-2 5 2 5-2v14l-5 2-5-2-5 2V5Zm5-2v14m5-12v14",
        "search": "M9 3a6 6 0 1 1 0 12A6 6 0 0 1 9 3Zm5 11 4 4",
        "alert": "M10 3 2 17h16L10 3Zm0 5v4m0 3v.5",
        "book": "M3 4h6a2 2 0 0 1 2 2v12a2 2 0 0 0-2-2H3V4Zm14 0h-6a2 2 0 0 0-2 2v12a2 2 0 0 1 2-2h6V4Z",
    }.get(name, "M3 3h14v14H3V3Z")
    return (f'<svg class="ico" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
            f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true"><path d="{p}"/></svg>')


def nav(active: str = "", user: str = "") -> str:
    """흰 상단 바 — 산출물끼리 오갈 수 있는 **실제 메뉴**.

    같은 폴더의 다른 산출물로 이동한다. 현재 보고 있는 항목은 링크 대신 활성 표시만 한다
    (자기 자신으로 가는 링크는 눌러도 제자리라 고장처럼 보인다).
    """
    items = []
    for label, fname, ico in NAV_ITEMS:
        if label == active:
            items.append(f'<span class="on" aria-current="page">{_icon(ico)}{label}</span>')
        else:
            items.append(f'<a href="{fname}">{_icon(ico)}{label}</a>')
    items = "".join(items)
    who = f'<span class="hide-s"><b>{user}</b></span>' if user else ""
    return f"""<div class="nav"><div class="nav-in">
  <span class="logo"><span class="dot"></span>SAMPYO<span class="sub">석회석 품위추적</span></span>
  <nav class="nav-menu">{items}</nav>
  <div class="nav-util">{who}<span class="hide-s">통합검색</span></div>
</div></div>"""


def hero(eyebrow: str, title: str, lead: str, strip: str = "",
         today: str = "", quick: list | None = None) -> str:
    """남색 밴드 — 좌측 파란 배너 카드 + 우측 TODAY/빠른이동 패널."""
    qs = "".join(
        f'<a href="#{a}"><span class="qi">{_icon(i)}</span>{n}</a>'
        for n, i, a in (quick or []))
    side = f"""<div class="hero-side">
    <div class="today"><span class="led"></span>TODAY {today}</div>
    <div class="quick">{qs}</div>
  </div>""" if (today or qs) else ""
    st = f'<div class="hero-strip">{strip}</div>' if strip else ""
    solo = "" if side else " solo"
    return f"""<div class="hero"><div class="hero-in{solo}">
  <div class="hero-card">
    <div class="hero-eyebrow">{eyebrow}</div>
    <h1>{title}</h1>
    <p class="lead">{lead}</p>
    {st}
  </div>
  {side}
</div></div>"""


def foot(text: str) -> str:
    return f'<div class="foot"><div class="foot-in">{text}</div></div>'
