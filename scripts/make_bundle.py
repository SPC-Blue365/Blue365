"""단일 파일 허브 [Synthesis-Agent] — 산출물 전부를 **HTML 하나**에 담는다.

⭐️ 왜 필요한가 (2026-10-21 사용자 지적)

상단 메뉴를 상대경로 링크로 만들어 뒀는데, 산출물을 **낱개로 받으면 옆 파일이 없어**
눌러도 아무 일이 일어나지 않는다. 메일로 한 파일만 받는 것이 보통이므로, 그 한 파일 안에
나머지를 **품고 있어야** 메뉴가 실제로 동작한다.

**방식** — 각 문서를 gzip + base64 로 넣어 두고, 메뉴를 누르면 브라우저에서 풀어
`blob:` 주소로 만들어 `<iframe>` 에 띄운다.

  · 문서마다 자기 CSS·JS 를 **그대로** 쓴다. iframe 이라 서로 섞이지 않는다 —
    통합 리포트의 Plotly 4.5MB 와 탭 기계장치도 건드리지 않고 돌아간다.
  · 안쪽 문서의 메뉴·머리 줄·탭바는 **감춰서 담는다.** 허브가 이미 메뉴를 들고 있어 두 벌이
    되면 보기 싫고, 안쪽 링크는 어차피 먹통이다. (2026-11-17 QMS 통일 후: 문자열을 도려내지
    않고 `<html class="embedded">` 표시만 붙인다 — 감추는 일은 공용 CSS 가 한다.
    도려내기는 메뉴 마크업이 바뀔 때마다 조용히 실패했다.)
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
from src.visualization.qmsstyle import (NAV_ARCHIVE, NAV_GROUPS, NAV_ITEMS,  # noqa: E402
                                        SHELL_JS, nav_hub)
from src.visualization.qmsstyle import DOC_STYLE as STYLE  # noqa: E402

E = html.escape

#: 허브가 품을 문서들 — 메뉴에 있는 것 전부. `plan_with_figures` 는 계획서의 수치 포함본이라
#: 메뉴에 없지만 함께 담는다(계획서 화면에서 안내만 한다).
DOCS = [f for _, f, _ in NAV_ITEMS] + [f for _, f, _ in NAV_ARCHIVE] + ["plan_with_figures.html"]

#: 안쪽 문서의 <html> 여는 태그 — 여기에 `embedded` 표시를 붙여 안쪽 틀을 감춘다.
_HTML_RE = re.compile(r"<html\b([^>]*)>", re.I)


def _embed(raw: str) -> tuple[str, bool]:
    """`<html …>` 에 class="embedded" 를 붙인다 — 공용 CSS 가 안쪽 메뉴·머리 줄·탭바를 감춘다."""
    m = _HTML_RE.search(raw)
    if not m:
        return raw, False
    attrs = m.group(1)
    if re.search(r"\bclass\s*=", attrs):
        new = re.sub(r'\bclass\s*=\s*"([^"]*)"', r'class="\1 embedded"', m.group(0), count=1)
    else:
        new = f"<html{attrs} class=\"embedded\">"
    return raw[:m.start()] + new + raw[m.end():], True


def _pack(path: Path) -> tuple[str, int, int]:
    """문서 하나를 gzip+base64 로 — (payload, 원본바이트, 압축바이트)."""
    raw = path.read_text(encoding="utf-8")
    stripped, ok = _embed(raw)
    if not ok:
        print(f"      ⚠️ {path.name}: <html> 태그를 찾지 못해 그대로 담습니다")
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
    groups = {f: g for g, items in NAV_GROUPS for _, f, _ in items}
    js = json.dumps(docs, ensure_ascii=False, separators=(",", ":"))
    tj = json.dumps(titles, ensure_ascii=False, separators=(",", ":"))
    gj = json.dumps(groups, ensure_ascii=False, separators=(",", ":"))

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>석회석 품위추적 — 통합</title>
<style>{STYLE}
/* 허브 — 왼쪽 메뉴 + 머리 줄은 그대로, 본문 자리는 안쪽 문서(iframe)가 꽉 채운다 */
html, body {{ height:100% }}
body {{ overflow:hidden }}
.shell {{ height:100vh; height:100dvh }}
.mainc {{ display:flex; flex-direction:column; height:100vh; height:100dvh; min-height:0 }}
#stage {{ flex:1; min-height:0; position:relative; background:var(--bg) }}
#frame {{ width:100%; height:100%; border:0; display:block; background:var(--bg) }}
#load {{ position:absolute; inset:0; display:grid; place-items:center; align-content:center; gap:12px;
         background:var(--bg); color:var(--muted); font-size:14px }}
#load.off {{ display:none }}
#load .spin {{ width:28px; height:28px; border:3px solid var(--line);
   border-top-color:var(--primary); border-radius:50%; animation:sp .8s linear infinite }}
@keyframes sp {{ to {{ transform:rotate(360deg) }} }}
@media (prefers-reduced-motion:reduce) {{ #load .spin {{ animation:none }} }}
#oops {{ max-width:60ch; line-height:1.7; text-align:center; background:var(--warn-bg);
         color:var(--ink2); border-radius:var(--r-well); padding:14px 18px }}
@media (max-width:720px) {{
  body {{ padding-bottom:0 }}
  .mainc {{ height:calc(100vh - 68px - env(safe-area-inset-bottom,0px));
            height:calc(100dvh - 68px - env(safe-area-inset-bottom,0px)) }}
}}
</style></head><body>

{nav_hub(active=NAV_ITEMS[0][0])}

<div id="stage">
  <iframe id="frame" title="선택한 문서"></iframe>
  <div id="load"><div class="spin"></div><div id="loadtxt">여는 중…</div></div>
</div>
</div>
</div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>{SHELL_JS}</script>

<script id="docs" type="application/json">{js}</script>
<script>
const DOCS = JSON.parse(document.getElementById('docs').textContent);
const TITLES = {tj};
const GROUPS = {gj};
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
  // 왼쪽 메뉴(aria-current) · 휴대폰 탭바(aria-selected) · 머리 줄 위치를 함께 맞춘다
  document.querySelectorAll('#docnav [data-doc]').forEach(b => {{
    if (b.dataset.doc === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  }});
  document.querySelectorAll('#tabbar [data-doc]').forEach(b =>
    b.setAttribute('aria-selected', b.dataset.doc === name ? 'true' : 'false'));
  const w = document.getElementById('where');
  if (w) w.innerHTML = '품위추적 › ' + (GROUPS[name] ? GROUPS[name] + ' › ' : '') + '<b>' + title + '</b>';
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
document.querySelectorAll('[data-doc]').forEach(b =>
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
