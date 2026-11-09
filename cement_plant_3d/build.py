"""오프라인(사내망)용 단일 HTML 파일 생성.

src.html 의 CDN <script> 를 vendor/three.min.js 내용으로 바꿔 넣고,
문서 골격(doctype/head/body)을 씌워 cement_plant_3d.html 을 만든다.
사용: python cement_plant_3d/build.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
CDN = '<script src="https://cdn.jsdelivr.net/npm/three@0.149.0/build/three.min.js"></script>'

src = (HERE / "src.html").read_text(encoding="utf-8")
lib = (HERE / "vendor" / "three.min.js").read_text(encoding="utf-8")
assert CDN in src, "src.html 에서 three.js CDN 태그를 찾지 못했습니다"
body = src.replace(CDN, "<script>\n" + lib.replace("</script", "<\\/script") + "\n</script>")

html = (
    '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    "</head>\n<body>\n" + body + "\n</body>\n</html>\n"
)
out = HERE / "cement_plant_3d.html"
out.write_text(html, encoding="utf-8")
print(f"생성: {out} ({out.stat().st_size/1024:.0f} KB)")
