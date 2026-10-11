"""오프라인 단일 HTML 대시보드 빌드 — Plotly·SheetJS·데이터·코드를 한 파일에 인라인한다.

사용(빌드 PC, 인터넷 필요):  python scripts/build_dashboard.py
결과:  dist/dashboard/Blue365_QMS_대시보드.html  (설치 없이 사내망 PC에서 더블클릭 → 브라우저로 열림, 완전 오프라인)

라이브러리는 registry.npmjs.org(프록시 허용)에서 받는다.
  - Plotly basic : 그래프(scatter·bar·histogram)
  - SheetJS(xlsx): 엑셀·CSV 불러오기/내보내기
"""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dashboard" / "src"
OUT = ROOT / "dist" / "dashboard" / "Blue365_QMS_대시보드.html"
CACHE = ROOT / "dist" / "dashboard" / ".libcache"

LIBS = {
    "plotly": {"url": "https://registry.npmjs.org/plotly.js-basic-dist-min/-/plotly.js-basic-dist-min-2.35.2.tgz",
               "member": "package/plotly-basic.min.js", "min_kb": 900},
    "xlsx": {"url": "https://registry.npmjs.org/xlsx/-/xlsx-0.18.5.tgz",
             "member": "package/dist/xlsx.full.min.js", "min_kb": 500},
}


def fetch_lib(name: str, spec: dict) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{name}.js"
    if cached.exists() and cached.stat().st_size > spec["min_kb"] * 1024:
        return cached.read_text(encoding="utf-8")
    print(f"  내려받기: {name} ({spec['url'].rsplit('/', 1)[-1]})")
    req = urllib.request.Request(spec["url"], headers={"User-Agent": "Blue365-dash-build"})
    with urllib.request.urlopen(req, timeout=180) as r:
        blob = r.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        js = tf.extractfile(spec["member"]).read().decode("utf-8")
    if len(js) < spec["min_kb"] * 1024:
        raise SystemExit(f"{name} 파일이 너무 작습니다({len(js)} B) — 다운로드 확인")
    cached.write_text(js, encoding="utf-8")
    return js


def safe_script(js: str) -> str:
    """인라인 <script> 안에서 조기 종료를 막는다(</script> → <\\/script)."""
    return js.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def main() -> None:
    print("[1/3] 데이터 생성")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "export_dashboard_data.py")], check=True)

    print("[2/3] 라이브러리 준비")
    plotly = fetch_lib("plotly", LIBS["plotly"])
    xlsx = fetch_lib("xlsx", LIBS["xlsx"])

    print("[3/3] 인라인 조립")
    html = (SRC / "index.html").read_text(encoding="utf-8")
    data = (SRC / "data.json").read_text(encoding="utf-8")
    parts = {
        "/*__CSS__*/": (SRC / "styles.css").read_text(encoding="utf-8"),
        "/*__PLOTLY__*/": safe_script(plotly),
        "/*__SHEETJS__*/": safe_script(xlsx),
        "/*__DATA__*/": safe_script(data),
        "/*__CHEM__*/": safe_script((SRC / "chem.js").read_text(encoding="utf-8")),
        "/*__APP__*/": safe_script((SRC / "app.js").read_text(encoding="utf-8")),
    }
    for ph, content in parts.items():
        if ph not in html:
            raise SystemExit(f"자리표시자 누락: {ph}")
        html = html.replace(ph, content, 1)
    if "/*__" in html:
        raise SystemExit("치환되지 않은 자리표시자가 남아 있습니다.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"\n완료: {OUT}  ({OUT.stat().st_size / 1e6:.1f} MB)")
    print(f"  Plotly {len(plotly) / 1024:.0f} KB · SheetJS {len(xlsx) / 1024:.0f} KB · 데이터 {len(data) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
