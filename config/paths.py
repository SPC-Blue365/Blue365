"""프로젝트 경로 중앙 관리.

경로를 코드 곳곳에 하드코딩하지 않고 여기서 한 번만 정의한다 (CLAUDE.md §7).
사용 예:
    from config.paths import RAW_DIR
    df = pd.read_excel(RAW_DIR / "mine.xlsx")
"""

from pathlib import Path

# 이 파일(config/paths.py)의 상위 폴더 = 프로젝트 루트
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# --- 데이터 계층 (원본 → 중간 → 처리완료 → 외부참조) ---
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"            # 원본 엑셀 업로드 위치 (읽기 전용 취급)
INTERIM_DIR: Path = DATA_DIR / "interim"    # 전처리 중간 산출물
PROCESSED_DIR: Path = DATA_DIR / "processed"  # 매칭/조인 완료 통합 데이터셋
EXTERNAL_DIR: Path = DATA_DIR / "external"  # 외부 참조 데이터

# --- 산출물 ---
OUTPUTS_DIR: Path = PROJECT_ROOT / "outputs"
FIGURES_DIR: Path = OUTPUTS_DIR / "figures"
PREDICTIONS_DIR: Path = OUTPUTS_DIR / "predictions"

# --- 학습된 모델 아티팩트 ---
MODELS_DIR: Path = PROJECT_ROOT / "models"


def ensure_dirs() -> None:
    """산출물 폴더가 없으면 생성한다 (원본 data/raw 등은 건드리지 않음)."""
    for d in (INTERIM_DIR, PROCESSED_DIR, FIGURES_DIR, PREDICTIONS_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
