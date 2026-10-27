"""통합 업로드 양식(엑셀) 생성 → docs/Blue365_QMS_업데이트_양식.xlsx

시트: 사용법 · 공정구분(코드표) · 원료 · 킬른 · 클링커 · 클링커일일 · 시멘트 · 물성 · 출하시멘트
      · 인수검사(원료·석고·고령토) · 항목사전
양식 내용은 qms/upload_template.py 한 곳에서 정의한다(앱의 📥 데이터 관리 → 입력 템플릿과 같은 파일).

사용:  python scripts/build_lims_update_workbook.py [출력경로]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qms.upload_template import build_upload_template  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "Blue365_QMS_업데이트_양식.xlsx"


def build() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build_upload_template())
    print("저장:", OUT)
    return OUT


if __name__ == "__main__":
    build()
