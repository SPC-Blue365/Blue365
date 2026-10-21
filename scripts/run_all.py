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


# ⚠️ 순서가 의미를 갖는다 — 통합본(make_bundle)은 **나머지를 전부 만든 뒤** 담아야 한다.
#    예전에는 run_all 이 리포트·모니터만 만들어, "원클릭" 이라면서 대시보드·브리프·처방서·
#    계획서는 따로 돌려야 했다(실제로 낡은 산출물이 섞여 나갔다).
STEPS = [
    ("매칭 통합셋 생성", "build_matched_dataset"),
    ("예측 모델 학습·저장", "train_and_save"),
    ("모니터 상태 산출", "monitor"),
    ("운영 대시보드", "make_dashboard"),
    ("현황 브리프", "make_brief"),
    ("배합 처방서", "make_prescription"),
    ("임원 계획서", "make_plan"),
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

    # 맨 마지막: 단일 파일 통합본 — 앞의 산출물이 모두 있어야 담을 수 있다
    print("\n[마무리] 단일 파일 통합본 …")
    t0 = time.time()
    try:
        from scripts import make_bundle

        make_bundle.main()
        print(f"      ✔ 완료 ({time.time() - t0:.1f}s)")
    except Exception as e:
        print(f"      ✘ 실패: {type(e).__name__}: {e}")
        failed.append("단일 파일 통합본")

    print("\n" + "=" * 70)
    if failed:
        print(f"⚠️ 일부 단계 실패: {', '.join(failed)}")
    else:
        print("✅ 전체 완료")
    print(f"산출물 위치: {OUTPUTS_DIR}")
    print("  · 블루365_통합.html   ⭐️ 이 파일 하나면 전부 열립니다 (메일로 보낼 것)")
    print("  · dashboard.html      매일 보는 화면 — 지금 정상인가")
    print("  · monitor_status.html 운영 모니터 (경보)")
    print("  · brief / prescription / plan / final_report  근거 보관")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="전체 파이프라인 원클릭 실행")
    ap.add_argument("--start", help="리포트 시작일 YYYY-MM-DD (미지정=처음)")
    ap.add_argument("--end", help="리포트 종료일 YYYY-MM-DD (미지정=끝)")
    a = ap.parse_args()
    raise SystemExit(main(a.start, a.end))
