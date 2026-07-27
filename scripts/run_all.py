"""전체 파이프라인 원클릭 실행 [Main-Agent].

실행:
    python scripts/run_all.py                       # 전체 기간
    python scripts/run_all.py --start 2026-06-15    # 기간 지정 리포트

순서: 검증 게이트 → 매칭 통합셋 → 모델 학습·저장 → 모니터 상태 → 최종 통합 리포트.
데이터(data/raw/) 배치 후 이 스크립트 하나만 실행하면 모든 산출물이 생성된다(로컬 전용).
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from config.paths import OUTPUTS_DIR, RAW_DIR
from config import schema as S


STEPS = [
    ("매칭 통합셋 생성", "build_matched_dataset"),
    ("예측 모델 학습·저장", "train_and_save"),
    ("모니터 상태 산출", "monitor"),
]


def _run(module_name: str) -> bool:
    import importlib

    mod = importlib.import_module(f"scripts.{module_name}")
    mod.main()
    return True


def main(start=None, end=None) -> int:
    src = RAW_DIR / S.DATA_FILE
    if not src.exists():
        print(f"❌ 데이터가 없습니다: {src}")
        print("   data/raw/ 에 엑셀을 배치한 뒤 다시 실행하세요 (로컬 전용).")
        return 1

    print("=" * 70)
    print(f"석회석 CaO 추적·예측 파이프라인 전체 실행  (데이터: {src.name})")
    print("=" * 70)

    failed = []
    for i, (label, mod) in enumerate(STEPS, 1):
        print(f"\n[{i}/{len(STEPS)+1}] {label} …")
        t0 = time.time()
        try:
            _run(mod)
            print(f"      ✔ 완료 ({time.time() - t0:.1f}s)")
        except Exception as e:  # 한 단계 실패해도 나머지는 진행하고 마지막에 보고
            print(f"      ✘ 실패: {type(e).__name__}: {e}")
            failed.append(label)

    # 마지막: 최종 통합 리포트 (기간 인자 전달)
    print(f"\n[{len(STEPS)+1}/{len(STEPS)+1}] 최종 통합 리포트 생성 …")
    t0 = time.time()
    try:
        from scripts import make_final_report

        make_final_report.main(start, end)
        print(f"      ✔ 완료 ({time.time() - t0:.1f}s)")
    except Exception as e:
        print(f"      ✘ 실패: {type(e).__name__}: {e}")
        failed.append("최종 통합 리포트")

    print("\n" + "=" * 70)
    if failed:
        print(f"⚠️ 일부 단계 실패: {', '.join(failed)}")
    else:
        print("✅ 전체 완료")
    print(f"산출물 위치: {OUTPUTS_DIR}")
    print("  · final_report.html   (임원 발표용 통합 리포트)")
    print("  · monitor_status.html (운영 모니터 상태)")
    print("대시보드 실행: streamlit run streamlit_app.py")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="전체 파이프라인 원클릭 실행")
    ap.add_argument("--start", help="리포트 시작일 YYYY-MM-DD (미지정=처음)")
    ap.add_argument("--end", help="리포트 종료일 YYYY-MM-DD (미지정=끝)")
    a = ap.parse_args()
    raise SystemExit(main(a.start, a.end))
