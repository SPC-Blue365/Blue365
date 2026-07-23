"""프로젝트 경로 중앙 관리 (데이터 라우팅).

경로를 코드 곳곳에 하드코딩하지 않고 여기서 한 번만 정의한다 (CLAUDE.md §7).

⭐️ 데이터 보관 정책 = 로컬 전용 (Local-Only):
    원본/가공 데이터는 로컬에만 두고 GitHub(원격)에는 절대 커밋하지 않는다 (CLAUDE.md §2-5).
    - 기본값: 데이터는 저장소 안의 `PROJECT_ROOT/data/` 에 두되 `.gitignore`로 원격 커밋에서 제외.
    - 데이터를 저장소 '바깥'의 로컬 경로에 두고 싶으면 환경변수로 지정한다:
          export BLUE365_DATA_DIR="/path/to/local/data"      # 데이터 루트 (raw/interim/... 상위)
          export BLUE365_OUTPUTS_DIR="/path/to/local/outputs" # (선택) 산출물 루트
          export BLUE365_MODELS_DIR="/path/to/local/models"   # (선택) 모델 루트
      → 이렇게 하면 데이터가 git 트리와 완전히 분리되어 실수로도 커밋되지 않는다.

사용 예:
    from config.paths import RAW_DIR
    df = pd.read_excel(RAW_DIR / "mine.xlsx")
"""

import os
from pathlib import Path

# 이 파일(config/paths.py)의 상위 폴더 = 프로젝트 루트
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]


def _resolve(env_var: str, default: Path) -> Path:
    """환경변수가 있으면 그 로컬 경로를, 없으면 기본값을 사용한다."""
    val = os.environ.get(env_var)
    return Path(val).expanduser().resolve() if val else default


# --- 데이터 계층 (원본 → 중간 → 처리완료 → 외부참조) : 로컬 전용 ---
# BLUE365_DATA_DIR 로 저장소 바깥 경로 지정 가능 (미지정 시 저장소 내 data/, .gitignore 처리)
DATA_DIR: Path = _resolve("BLUE365_DATA_DIR", PROJECT_ROOT / "data")
RAW_DIR: Path = DATA_DIR / "raw"              # 원본 엑셀 업로드 위치 (읽기 전용 취급)
INTERIM_DIR: Path = DATA_DIR / "interim"      # 전처리 중간 산출물
PROCESSED_DIR: Path = DATA_DIR / "processed"  # 매칭/조인 완료 통합 데이터셋
EXTERNAL_DIR: Path = DATA_DIR / "external"    # 외부 참조 데이터

# --- 산출물 (로컬 전용) ---
OUTPUTS_DIR: Path = _resolve("BLUE365_OUTPUTS_DIR", PROJECT_ROOT / "outputs")
FIGURES_DIR: Path = OUTPUTS_DIR / "figures"
PREDICTIONS_DIR: Path = OUTPUTS_DIR / "predictions"

# --- 학습된 모델 아티팩트 (로컬 전용) ---
MODELS_DIR: Path = _resolve("BLUE365_MODELS_DIR", PROJECT_ROOT / "models")


def ensure_dirs() -> None:
    """데이터/산출물 폴더가 없으면 생성한다 (원본 파일은 건드리지 않음).

    로컬 전용 정책상 이 폴더들은 git에 커밋되지 않으므로, 새 환경/머신에서
    처음 실행할 때 폴더 자체가 없을 수 있어 안전하게 만들어 준다.
    """
    for d in (
        RAW_DIR,
        INTERIM_DIR,
        PROCESSED_DIR,
        EXTERNAL_DIR,
        FIGURES_DIR,
        PREDICTIONS_DIR,
        MODELS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
