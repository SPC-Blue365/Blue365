"""오프라인 HTML 대시보드: 데이터 내보내기(spec·sample)와 소스 자리표시자 검증(파이썬 측).

JS 계산(chem.js)은 Python과 동일 값을 내는지 빌드 시 별도로 대조한다(scripts/build_dashboard.py 참고).
"""

import importlib.util
import json
import re
from pathlib import Path

from qms.standards import SpecRegistry
from qms.store import RAW_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dashboard" / "src"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EXP = _load("export_dashboard_data", ROOT / "scripts" / "export_dashboard_data.py")


def test_spec_payload_structure():
    spec = EXP.spec_payload()
    reg = SpecRegistry()
    assert len(spec["items"]) == len(reg.all())
    keys = {it["key"] for it in spec["items"]}
    assert {"clk_fcao", "clk_lsf", "phy_s28", "phy_crvi"} <= keys
    fcao = next(it for it in spec["items"] if it["key"] == "clk_fcao")
    assert fcao["limits"]["*"] == {"lsl": 0.4, "usl": 1.8, "target": 1.0} and fcao["keyItem"]
    assert spec["products"] == ["1종", "3종"]
    assert set(spec["tables"]) == set(RAW_COLUMNS)
    assert "product" not in spec["tables"]["physical"]["columns"]


def test_sample_payload_is_clean_json():
    sample = EXP.sample_payload()
    assert set(sample) >= {"raw_meal", "clinker", "cement", "physical"}
    blob = json.dumps(sample)                                  # NaN·Inf 없이 직렬화 가능해야 함
    assert "NaN" not in blob and "Infinity" not in blob
    phys = sample["physical"]
    assert phys["byProduct"] and phys["rows"][0][1] in ("1종", "3종")
    assert phys["rows"][0].count(phys["rows"][0][1]) == len([v for v in phys["rows"][0] if v == phys["rows"][0][1]])
    # 품종이 값 자리에 중복으로 들어가지 않음(열 수 = 1(ts)+1(product)+컬럼 수)
    assert all(len(r) == 2 + len(phys["columns"]) for r in phys["rows"])


def test_source_files_have_placeholders():
    html = (SRC / "index.html").read_text(encoding="utf-8")
    for ph in ("/*__CSS__*/", "/*__PLOTLY__*/", "/*__SHEETJS__*/", "/*__DATA__*/", "/*__CHEM__*/", "/*__APP__*/"):
        assert ph in html, ph
    chem = (SRC / "chem.js").read_text(encoding="utf-8")
    assert "predictClinker" in chem and "bogue" in chem and "requiredDose" in chem
    app = (SRC / "app.js").read_text(encoding="utf-8")
    assert "deriveAll" in app and "loadFile" in app and "구분별 5칸 채우기" in app   # 배합 다원료 UI


def test_build_script_inlines_without_leftover_placeholder(tmp_path, monkeypatch):
    """조립 로직: 모든 자리표시자가 치환되고 </script> 가 안전하게 이스케이프되는지(라이브러리 다운로드는 생략)."""
    B = _load("build_dashboard", ROOT / "scripts" / "build_dashboard.py")
    assert B.safe_script("a</script>b") == "a<\\/script>b"
    html = (SRC / "index.html").read_text(encoding="utf-8")
    parts = {
        "/*__CSS__*/": "body{}", "/*__PLOTLY__*/": "/*p*/", "/*__SHEETJS__*/": "/*x*/",
        "/*__DATA__*/": '{"a":1}', "/*__CHEM__*/": "/*c*/", "/*__APP__*/": "/*a*/",
    }
    for ph, val in parts.items():
        assert ph in html
        html = html.replace(ph, val, 1)
    assert "/*__" not in html and re.search(r"window\.__QMS_DATA__\s*=\s*\{", html)
