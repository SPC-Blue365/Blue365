"""리포트 공통 스타일 [Synthesis-Agent].

`make_brief.py`(현황)와 `make_prescription.py`(처방)가 **같은 시각 언어**를 쓰도록
토큰과 기본 컴포넌트를 한곳에 둔다. 색은 전부 CSS 변수로 정의하고, 라이트/다크 세 상태
(명시 선택 2 + 시스템 기본 1)를 모두 커버한다 — 어느 한 상태에서만 정의된 색이 있으면
반대 테마에서 글자가 바탕에 묻힌다.

⚠️ 이 파일은 f-string 이 아니다. 중괄호를 이스케이프하지 말 것.
"""

STYLE = """
:root {
  --paper:#faf9f6; --surface:#ffffff; --ink:#17191a; --muted:#6f6b62;
  --rule:#e2ded6; --grid:#efece5; --accent:#2f6b63; --bar:#b3ab9b;
  --band:#e8efec; --warnfill:#e6d9bd; --badfill:#c98b80;
  --good:#35702f; --warn:#8d6207; --bad:#a1352c; --shadow:0 1px 2px rgba(23,25,26,.05);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper:#131518; --surface:#1a1d21; --ink:#e9e6e0; --muted:#9a948a;
    --rule:#2c3036; --grid:#23272c; --accent:#57a396; --bar:#6d685f;
    --band:#1e2b29; --warnfill:#4a3f27; --badfill:#8d4a40;
    --good:#6aab5f; --warn:#c9993a; --bad:#d3766a; --shadow:none;
  }
}
:root[data-theme="dark"] {
  --paper:#131518; --surface:#1a1d21; --ink:#e9e6e0; --muted:#9a948a;
  --rule:#2c3036; --grid:#23272c; --accent:#57a396; --bar:#6d685f;
  --band:#1e2b29; --warnfill:#4a3f27; --badfill:#8d4a40;
  --good:#6aab5f; --warn:#c9993a; --bad:#d3766a; --shadow:none;
}
:root[data-theme="light"] {
  --paper:#faf9f6; --surface:#ffffff; --ink:#17191a; --muted:#6f6b62;
  --rule:#e2ded6; --grid:#efece5; --accent:#2f6b63; --bar:#b3ab9b;
  --band:#e8efec; --warnfill:#e6d9bd; --badfill:#c98b80;
  --good:#35702f; --warn:#8d6207; --bad:#a1352c; --shadow:0 1px 2px rgba(23,25,26,.05);
}
* { box-sizing:border-box; }
body {
  background:var(--paper); color:var(--ink); margin:0;
  font-family:'Pretendard','Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',
    system-ui,-apple-system,sans-serif;
  font-size:16px; line-height:1.75; -webkit-font-smoothing:antialiased;
  font-variant-numeric:tabular-nums;
}
.wrap { max-width:840px; margin:0 auto; padding:56px 24px 72px;
        display:flex; flex-direction:column; gap:52px; }
.top { display:flex; flex-direction:column; gap:14px; }
.eyebrow { font-size:12px; letter-spacing:.16em; color:var(--muted); font-weight:600; }
h1 { font-size:34px; line-height:1.3; font-weight:700; letter-spacing:-.02em;
      margin:0; text-wrap:balance; }
.thesis { font-size:19px; line-height:1.65; color:var(--ink); margin:0; max-width:62ch;
           border-left:2px solid var(--accent); padding-left:16px; }
.meta { font-size:13px; color:var(--muted); }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:1px;
         background:var(--rule); border:1px solid var(--rule); border-radius:3px;
         overflow:hidden; }
.k { background:var(--surface); padding:18px 18px 16px; }
.kv { font-size:31px; font-weight:700; letter-spacing:-.02em; line-height:1.15; }
.ku { font-size:15px; font-weight:600; margin-left:3px; color:var(--muted); }
.kl { font-size:13px; margin-top:5px; line-height:1.4; }
.kn { font-size:12px; color:var(--muted); margin-top:2px; line-height:1.4; }
.k.good .kv { color:var(--good); }
.k.bad  .kv { color:var(--bad); }
.k.warn .kv { color:var(--warn); }
section { display:flex; flex-direction:column; gap:14px; }
section > h2 { font-size:13px; letter-spacing:.13em; color:var(--muted);
                font-weight:700; margin:0; padding-bottom:10px;
                border-bottom:1px solid var(--rule); }
.q { font-size:22px; font-weight:700; letter-spacing:-.015em; margin:0; text-wrap:balance; }
.a { font-size:17px; margin:0; max-width:62ch; color:var(--ink); }
.a strong { color:var(--accent); font-weight:700; }
p.note { font-size:14.5px; color:var(--muted); margin:0; max-width:64ch; }
.card { background:var(--surface); border:1px solid var(--rule); border-radius:3px;
         padding:16px; box-shadow:var(--shadow); overflow-x:auto; }
svg.chart { display:block; width:100%; height:auto; }
.ax { font-size:10.5px; fill:var(--muted); }
.ct { font-size:12.5px; fill:var(--ink); font-weight:700; }
.cs { font-size:11px; fill:var(--muted); }
.inb { font-size:11.5px; fill:var(--surface); font-weight:700; }
.inw { font-size:11.5px; fill:var(--ink); font-weight:700; }
table.t { border-collapse:collapse; width:100%; font-size:14px; }
table.t th { text-align:left; font-weight:600; font-size:12px; letter-spacing:.04em;
              color:var(--muted); border-bottom:1px solid var(--rule); padding:7px 10px; }
table.t td { padding:8px 10px; border-bottom:1px solid var(--grid); }
table.t tr:last-child td { border-bottom:none; }
table.t td.n, table.t th.n { text-align:right; }
table.t td.c { text-align:center; color:var(--good); font-weight:600; }
.said { background:var(--surface); border:1px solid var(--rule); border-left:2px solid var(--warn);
         border-radius:3px; padding:14px 16px; font-size:14.5px; }
.said .lbl { display:block; font-size:12px; letter-spacing:.06em; color:var(--warn);
              margin-bottom:6px; font-weight:700; }
ol.asks { margin:0; padding-left:0; list-style:none; counter-reset:a;
           display:flex; flex-direction:column; gap:12px; }
ol.asks li { display:grid; grid-template-columns:26px 1fr; gap:12px; align-items:start;
              font-size:15px; }
ol.asks li::before { counter-increment:a; content:counter(a); font-size:12px; font-weight:700;
   color:var(--surface); background:var(--accent); width:22px; height:22px; border-radius:50%;
   display:grid; place-items:center; margin-top:3px; }
ol.asks .w { display:block; font-size:13.5px; color:var(--muted); margin-top:2px; }
footer { border-top:1px solid var(--rule); padding-top:18px; font-size:12.5px;
          color:var(--muted); line-height:1.7; }
@media (max-width:560px) { h1 { font-size:27px; } .q { font-size:19px; } }
"""
