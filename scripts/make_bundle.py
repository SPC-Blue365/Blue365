"""단일 파일 허브 [Synthesis-Agent] — 산출물 전부를 **HTML 하나**에 담는다.

⭐️ 왜 필요한가 (2026-10-21 사용자 지적)

상단 메뉴를 상대경로 링크로 만들어 뒀는데, 산출물을 **낱개로 받으면 옆 파일이 없어**
눌러도 아무 일이 일어나지 않는다. 메일로 한 파일만 받는 것이 보통이므로, 그 한 파일 안에
나머지를 **품고 있어야** 메뉴가 실제로 동작한다.

**방식** — 각 문서를 gzip + base64 로 넣어 두고, 메뉴를 누르면 브라우저에서 풀어
`blob:` 주소로 만들어 `<iframe>` 에 띄운다.

  · 문서마다 자기 CSS·JS 를 **그대로** 쓴다. iframe 이라 서로 섞이지 않는다 —
    통합 리포트의 Plotly 4.5MB 와 탭 기계장치도 건드리지 않고 돌아간다.
  · 안쪽 문서의 상단 바는 **빼고 담는다.** 허브가 이미 메뉴를 들고 있어 두 줄이 되면
    보기 싫고, 안쪽 링크는 어차피 먹통이다.
  · 한 번 푼 문서는 캐시해 두 번째부터는 즉시 뜬다.

용량: 원본 합계 약 10.6MB → gzip+base64 로 약 4.1MB.

실행: python scripts/make_bundle.py  →  outputs/블루365_통합.html
"""

from __future__ import annotations

import base64
import gzip
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths as P                                      # noqa: E402
from src.visualization.portalstyle import NAV_ARCHIVE, NAV_ITEMS, STYLE, nav_hub  # noqa: E402

E = html.escape

#: 허브가 품을 문서들 — 메뉴에 있는 것 전부. `plan_with_figures` 는 계획서의 수치 포함본이라
#: 메뉴에 없지만 함께 담는다(계획서 화면에서 안내만 한다).
DOCS = [f for _, f, _ in NAV_ITEMS] + [f for _, f, _ in NAV_ARCHIVE] + ["plan_with_figures.html"]

#: 안쪽 문서에서 걷어낼 상단 바. 허브가 이미 들고 있다.
_NAV_RE = re.compile(r'<div class="nav"><div class="nav-in">.*?</div></div>', re.S)


def _pack(path: Path) -> tuple[str, int, int]:
    """문서 하나를 gzip+base64 로 — (payload, 원본바이트, 압축바이트)."""
    raw = path.read_text(encoding="utf-8")
    stripped, n = _NAV_RE.subn("", raw, count=1)
    if n == 0:
        print(f"      ⚠️ {path.name}: 상단 바를 찾지 못해 그대로 담습니다")
    b = stripped.encode("utf-8")
    gz = gzip.compress(b, 9)
    return base64.b64encode(gz).decode("ascii"), len(b), len(gz)


def build() -> str:
    docs, total_raw, total_gz, missing = {}, 0, 0, []
    for name in DOCS:
        f = P.OUTPUTS_DIR / name
        if not f.exists():
            missing.append(name)
            continue
        payload, raw, gz = _pack(f)
        docs[name] = payload
        total_raw += raw
        total_gz += gz
        print(f"      · {name:<26}{raw/1048576:6.2f}MB → {gz/1048576:5.2f}MB")
    if missing:
        print(f"      ⚠️ 빠진 문서: {missing} — 먼저 생성하세요")
    if not docs:
        raise SystemExit("담을 문서가 없습니다. scripts/run_all.py 등을 먼저 실행하세요.")

    first = NAV_ITEMS[0][1]
    titles = {f: n for n, f, _ in (*NAV_ITEMS, *NAV_ARCHIVE)}
    titles["plan_with_figures.html"] = "계획서(수치 포함)"
    js = json.dumps(docs, ensure_ascii=False, separators=(",", ":"))
    tj = json.dumps(titles, ensure_ascii=False, separators=(",", ":"))

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>석회석 품위추적 — 통합</title>
<style>{STYLE}
html, body {{ height:100%; }}
body {{ display:flex; flex-direction:column; overflow:hidden; }}
#stage {{ flex:1; min-height:0; position:relative; background:var(--ground); }}
#frame {{ width:100%; height:100%; border:0; display:block; background:var(--ground); }}
#load {{ position:absolute; inset:0; display:grid; place-items:center; gap:10px;
         background:var(--ground); color:var(--ink-2); font-size:13.5px; }}
#load.off {{ display:none; }}
#load .spin {{ width:26px; height:26px; border:3px solid var(--line);
   border-top-color:var(--accent); border-radius:50%; animation:sp .8s linear infinite; }}
@keyframes sp {{ to {{ transform:rotate(360deg); }} }}
@media (prefers-reduced-motion:reduce) {{ #load .spin {{ animation:none; }} }}
#oops {{ max-width:60ch; line-height:1.7; text-align:center; }}
</style></head><body>

{nav_hub(active=NAV_ITEMS[0][0])}

<div id="stage">
  <iframe id="frame" title="선택한 문서"></iframe>
  <div id="load"><div class="spin"></div><div id="loadtxt">여는 중…</div></div>
</div>

<script id="docs" type="application/json">{js}</script>
<script>
const DOCS = JSON.parse(document.getElementById('docs').textContent);
const TITLES = {tj};
const cache = {{}};
const frame = document.getElementById('frame');
const load  = document.getElementById('load');
const txt   = document.getElementById('loadtxt');

function b64bytes(b64) {{
  const s = atob(b64), n = s.length, a = new Uint8Array(n);
  for (let i = 0; i < n; i++) a[i] = s.charCodeAt(i);
  return a;
}}

async function unpack(b64) {{
  const bytes = b64bytes(b64);
  // DecompressionStream 이 없는 구형 브라우저도 있으므로 반드시 확인한다
  if (typeof DecompressionStream !== 'function') throw new Error('nogzip');
  const ds = new DecompressionStream('gzip');
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  return await new Response(stream).text();
}}

async function show(name) {{
  const title = TITLES[name] || name;
  document.querySelectorAll('.navbtn').forEach(b => {{
    const on = b.dataset.doc === name;
    b.classList.toggle('on', on);
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  }});
  if (!DOCS[name]) {{ fail(title + ' 문서가 이 파일에 들어 있지 않습니다.'); return; }}
  if (cache[name]) {{ frame.src = cache[name]; load.classList.add('off'); return; }}
  load.classList.remove('off');
  txt.textContent = title + ' 여는 중…';
  try {{
    const html = await unpack(DOCS[name]);
    cache[name] = URL.createObjectURL(new Blob([html], {{type: 'text/html'}}));
    frame.src = cache[name];
  }} catch (e) {{
    fail(e && e.message === 'nogzip'
      ? '이 브라우저는 압축 해제를 지원하지 않습니다. 크롬·엣지·사파리 최신 버전에서 열어 주세요.'
      : (title + ' 를 여는 중 문제가 생겼습니다: ' + e));
  }}
}}

function fail(msg) {{
  load.classList.remove('off');
  load.innerHTML = '<div id="oops">⚠️ ' + msg + '</div>';
}}

frame.addEventListener('load', () => {{ if (frame.src) load.classList.add('off'); }});
document.querySelectorAll('.navbtn').forEach(b =>
  b.addEventListener('click', () => show(b.dataset.doc)));
show({json.dumps(first)});
</script>
</body></html>"""


def main() -> None:
    P.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    print("[담는 중]")
    doc = build()
    dst = P.OUTPUTS_DIR / "블루365_통합.html"
    dst.write_text(doc, encoding="utf-8")
    print(f"\n[OK] 단일 파일 통합본: {dst} "
          f"({len(doc.encode('utf-8')) / 1048576:.1f} MB · 이 파일 하나만 있으면 됩니다)")


if __name__ == "__main__":
    main()
