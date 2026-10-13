"""브라우저 자동 번역 차단.

Streamlit 기본 시작 페이지(static/index.html)는 `<html lang="en">` 이라, 크롬·엣지가 한국어 화면을 '영어 페이지'로 보고
자동 번역(영어→한국어)을 켜면 한국어 문구가 엉뚱하게 바뀐다(예: 종합 현황→비교 현황, 보고서→반대, 출하시멘트→빈칸).
시작 페이지를 `lang="ko"` + 번역 금지(`translate="no"`, `<meta name="google" content="notranslate">`)로 고쳐 막는다.
설치(1_SETUP)·실행(2_RUN·3_RUN_SHARE) 때와 앱 시작 때 확인하며, 이미 고쳐져 있으면 아무것도 하지 않는다.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

MARK = 'name="google" content="notranslate"'
META = '<meta name="google" content="notranslate" />'
HTML_TAG = '<html lang="ko" translate="no" class="notranslate">'
# 앱 안에서 한 번 더 지정(시작 페이지를 고치지 못한 경우의 보조 수단 — 화면을 그린 뒤 적용되므로 완전하지는 않음)
RUNTIME_JS = """<script>(function(){var d=window.parent&&window.parent.document?window.parent.document:document;
var h=d.documentElement;h.setAttribute('lang','ko');h.setAttribute('translate','no');h.classList.add('notranslate');
if(d.body){d.body.setAttribute('translate','no');d.body.classList.add('notranslate');}
if(!d.querySelector('meta[name="google"][content="notranslate"]')){var m=d.createElement('meta');m.name='google';
m.content='notranslate';d.head.appendChild(m);}})();</script>"""


def index_path() -> Path | None:
    spec = importlib.util.find_spec("streamlit")
    if spec is None or not spec.origin:
        return None
    p = Path(spec.origin).parent / "static" / "index.html"
    return p if p.exists() else None


def patched(text: str) -> str:
    out = re.sub(r"<html\b[^>]*>", HTML_TAG, text, count=1)
    if MARK not in out:
        out = re.sub(r"(<meta\s+charset=[^>]*>)", r"\1\n    " + META, out, count=1, flags=re.I)
        if MARK not in out:                                  # charset 태그가 없으면 <head> 바로 뒤
            out = re.sub(r"(<head[^>]*>)", r"\1\n    " + META, out, count=1, flags=re.I)
    return out


def is_patched(path: Path) -> bool:
    try:
        t = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return MARK in t and HTML_TAG in t


def ensure(path: Path | None = None) -> str:
    """'ok'(이미 적용) · 'patched'(이번에 고침) · 'missing'(파일 없음) · 'readonly'(쓰기 불가)."""
    path = path or index_path()
    if path is None:
        return "missing"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "missing"
    new = patched(text)
    if new == text:
        return "ok"
    try:
        path.write_text(new, encoding="utf-8")
    except OSError:
        return "readonly"
    return "patched"
