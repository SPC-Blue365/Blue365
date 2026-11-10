"""화면 파일 만들기.

src.html 에 three.js · qms.js · 내장 QMS 기본 데이터(qms_default.json)를 넣어
  cement_plant_3d.html  — 사내망(오프라인) 완성본 (모두 파일 안에 포함)
  artifact.html         — 미리보기용 (three.js 는 CDN, 나머지 포함)
을 만듭니다.  사용: python build.py
"""
import base64
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CDN = '<script src="https://cdn.jsdelivr.net/npm/three@0.149.0/build/three.min.js"></script>'
QMS_TAG = '<script src="qms.js"></script>'
DEF_TAG = '<script id="qmsDefault" type="application/json">null</script>'


def safe(js: str) -> str:
    return js.replace("</script", "<\\/script")


src = (HERE / "src.html").read_text(encoding="utf-8")
BUILD = (dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))).strftime("%Y-%m-%d %H:%M")   # 한국 시각
src = src.replace("__B365_BUILD__", BUILD).replace("<title>", f'<meta name="b365-build" content="{BUILD}">\n<title>', 1)
for tag in (CDN, QMS_TAG, DEF_TAG):
    assert tag in src, f"src.html 에서 {tag[:40]}… 를 찾지 못했습니다"
qms = (HERE / "qms.js").read_text(encoding="utf-8")
dflt = HERE / "qms_default.json"
data = json.dumps(json.loads(dflt.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":")) if dflt.exists() else "null"
body = (src.replace(QMS_TAG, "<script>\n" + safe(qms) + "\n</script>")
           .replace(DEF_TAG, '<script id="qmsDefault" type="application/json">' + data.replace("</", "<\\/") + "</script>"))

LOGO_IMG = '<span class="logo co"><img src="logo.png" alt="삼표시멘트"></span>'
(HERE / "artifact.html").write_text(body.replace(LOGO_IMG, '<span class="logo" data-ic="cube"></span>'), encoding="utf-8")   # 미리보기에는 회사 로고 대신 기본 아이콘
logo = HERE / "logo.png"
if logo.exists():   # 사내망 완성본: 회사 로고를 파일 안에 넣음 (인터넷 없이 표시)
    body = body.replace('src="logo.png"', 'src="data:image/png;base64,' + base64.b64encode(logo.read_bytes()).decode() + '"')
lib = (HERE / "vendor" / "three.min.js").read_text(encoding="utf-8")
offline = body.replace(CDN, "<script>\n" + safe(lib) + "\n</script>")
html = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        "</head>\n<body>\n" + offline + "\n</body>\n</html>\n")
out = HERE / "cement_plant_3d.html"
out.write_text(html, encoding="utf-8")
print(f"버전 {BUILD} · 생성: {out.name} ({out.stat().st_size/1024:.0f} KB), artifact.html ({(HERE/'artifact.html').stat().st_size/1024:.0f} KB)")
