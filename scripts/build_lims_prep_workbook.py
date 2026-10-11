"""LIMS 연동 준비서(엑셀) 생성 → docs/LIMS_연동_준비서.xlsx

사용:  python scripts/build_lims_prep_workbook.py [출력 경로]
화면 [🔗 LIMS 연동] ② 탭의 '📄 LIMS 연동 준비서(엑셀)' 버튼과 같은 내용이다(qms.lims.prep_workbook).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QMS_DATA_DIR", tempfile.mkdtemp(prefix="qms_lims_prep_"))

from qms.lims import prep_workbook  # noqa: E402
from qms.standards import SpecRegistry  # noqa: E402


def main(out: Path) -> None:
    out.write_bytes(prep_workbook(SpecRegistry()))
    print(f"저장: {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "LIMS_연동_준비서.xlsx")
