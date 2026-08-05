"""공정별 데이터 스키마 스펙 & 확정 규칙 (Source Spec).

data_v1.xlsx 기준. EDA + 사용자 확인으로 확정된 값 (docs/data_schema.md 와 동기화).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# === 시트명 상수 ===
SHEET_MINE_49Q = "광산(49Q)_XRF"
SHEET_MINE_47Q = "광산(47Q)_감마레이"
SHEET_MINE_45Q = "45Q 감마레이 data"
SHEET_OSP_OLD = "OSP인출_기존"       # 기존 라인
SHEET_OSP_NEW = "OSP인출_신설"       # 신설 라인
SHEET_YARD_CNA = "CNA data"          # ⭐️ 최종 목표 기준 (야드 실시간 분석기)
SHEET_YC_OLD = "기존라인 야드변경"     # 야드변경별 물량·CaO·MgO (기존)
SHEET_YC_NEW = "신설라인 야드변경"     # 야드변경별 물량·CaO·MgO (신설)

# === 라인 구분 (공정구분) ===
LINE_OLD = "기존"
LINE_NEW = "신설"
LINE_IDLE = "운휴"

# === OSP 인출 P/W 컬럼 (라인별 사용 분리) ===
PW_COLS_OLD = [" P/W1호", " P/W2호"]   # 기존 라인이 사용
PW_COLS_NEW = [" P/W3호", " P/W4호"]   # 신설 라인이 사용
PW_COLS_ALL = [" P/W1호", " P/W2호", " P/W3호", " P/W4호"]

# === 확정 규칙 ===
# 인출량(총톤)은 한 회차에 적힌 구역 수로 '균등 배분'한다. (사용자 확인)
WITHDRAWAL_SPLIT = "equal"

# 복합 구역코드(예: "50/55", "55-45", "100-0", "15~35") 분리 구분자
# 2026-08-05 갱신본에서 쉼표 표기가 처음 등장("25~30, 65~40") → 쉼표·공백도 구분자로 추가.
# (빠뜨리면 "30, 65" 가 숫자 변환에 실패해 구역 하나가 조용히 사라진다)
ZONE_DELIMITERS = r"[/\-~,\s]+"


@dataclass
class SourceSpec:
    """검증 게이트용 역할 컬럼 매핑 (src/data/validation.py 에서 사용).

    정제(clean.py) 후 tidy 프레임의 '역할 컬럼'을 지정한다. 컬럼명을 코드에
    하드코딩하지 않기 위한 계약.
    """

    name: str
    time_col: Optional[str] = None
    cao_col: Optional[str] = None
    tonnage_col: Optional[str] = None
    key_cols: list[str] = field(default_factory=list)
    allow_zero_tonnage: bool = False   # 0톤 허용 여부(야드 적재량 등)
    expect_unique: bool = True         # Key 조합이 유일해야 하는지(False면 중복 검사 생략)


# 데이터파일 (로컬 전용)
DATA_FILE = "data_v1.xlsx"

# 라인 → (야드 시트, 별칭) 페어링 (사용자 확정: 기존↔45Q, 신설↔CNA)
YARD_PAIR = {
    LINE_OLD: (SHEET_MINE_45Q, "45Q·4-5K 킬른"),
    LINE_NEW: (SHEET_YARD_CNA, "CNA·6-7K 킬른"),
}

# 라인 운전 상태 메모 — 가동 중지·보수 등으로 데이터 갱신이 멈춘 라인을 명시한다.
# 데이터 지연은 자동 감지되지만, 그 '이유'는 현장만 알기에 여기에 기록한다(상태 변경 시 이 값만 수정).
LINE_NOTES = {
    # 2026-08-05 사용자 확정: 07/21~07/28 기존 라인은 가동하지 않았고 OSP 재고만 채웠다.
    # OSP인출_기존의 기록 공백은 누락이 아니라 '실제 미가동'이다 → 인출 0 이 참값.
    LINE_OLD: ("가동 중지 (2026-07/21~) — 채굴분은 OSP 재고 적재만, 인출 없음. "
               "45Q 야드 데이터도 갱신 없음"),
}

# === 복합 라인 라벨 처리 ⭐️ (2026-08-05 버그 수정) =====================
# 광산 `공정구분` 에 한 교대가 두 상태에 걸친 복합 라벨이 들어온다.
# 이전에는 이 값이 라인명과 달라 **라인별 집계에서 통째로 빠졌다** (7행 21,065톤, 총량의 1.7%).
#   · "운휴/기존" · "운휴/신설" → 운휴는 가동하지 않은 시간이라 실물량이 없다.
#     따라서 물량 전량을 뒤쪽 실제 라인에 귀속한다. (모호하지 않음)
#   · "기존/신설" → 한 교대에 두 라인이 모두 가동. **균등 배분** (2026-08-05 사용자 확정 —
#     구역 45/70 처럼 구역이 둘이어도 위치 대응이 아니라 균등 배분이 맞다).
LINE_SPLIT_DELIM = "/"

# "운휴/기존" 은 **그 교대의 절반은 운휴, 절반만 이송**했다는 뜻이다 (2026-08-05 사용자 확정).
# 물량은 전량 실제 라인에 귀속되지만(운휴는 생산이 없다), **가동 시간이 절반**이므로
# 시간당 생산량으로 환산할 때 이 비율을 써야 한다.
IDLE_ACTIVE_RATIO = 0.5

# === 라인 귀속 정정 (사용자 확정) ⭐️ =================================
# 2026-08-05 갱신본은 47Q 07월 하순을 재입력하며 7,834톤을 신설→기존으로 재귀속했다.
# 인출이 0인 미가동 창(§6-0-6)에서 'Δ재고 = 적재' 로 감사한 결과 그 배분은 실사와 배치되고
# (기존 불일치 +8,966 → +16,738톤, 신설이 적재<인출이 되어 재고 증가와 모순, OSP1 용량 초과),
# **사용자가 "갱신 전 기준이 맞다"고 확정**했다 (2026-08-05).
#
# 아래는 갱신 전 기록에 시간 겹침 다수결로 대응시켜 얻은 정정 목록이다.
#   · 시각·라인 라벨만 담는다 — 품위·물량은 원본 그대로 쓴다(데이터를 코드에 넣지 않는다, §6.1).
#   · 07/21 이전 블록은 두 버전이 일치해 정정 대상이 없다(규칙이 무해함을 보이는 자기검증).
#   · ⚠️ 원본 시트의 `공정구분` 이 현장에서 바로잡히면 **이 표를 지워야 한다.**
#     적용 건수가 기대와 다르면 조용히 넘어가지 않고 경고한다(clean.apply_line_overrides).
MINE_LINE_OVERRIDES = [
    dict(source="47Q", date="2026-07-22", start="16:00", end="17:10", line=LINE_NEW),
    dict(source="47Q", date="2026-07-23", start="16:00", end="17:10", line=LINE_NEW),
    dict(source="47Q", date="2026-07-24", start="15:40", end="18:00", line=LINE_OLD),
    dict(source="47Q", date="2026-07-27", start="08:40", end="16:00", line=LINE_NEW),
]

# === 생산방법 (C/R) & 생산능력 ⭐️ (2026-08-05 사용자 사전 고지) ==========
# 다음 갱신본에 **생산방법(C/R)** 컬럼이 추가될 예정이다. 값과 시간당 생산능력:
#   G/C       = 자이레토리 크러셔 (Gyratory Crusher)  1,500~1,600 t/h
#   H/C       = 함마 크러셔      (Hammer Crusher)    1,000~1,100 t/h
#   G/C+H/C   = 동시 가동                            1,500~1,600 t/h
#
# ⭐️ 동시 가동이 **가산되지 않는다**(1,600+1,100 ≠ 2,700)는 점이 핵심이다.
#    크러셔 하류에 병목(컨베이어·이송 계통)이 있어 동시 가동은 처리량이 아니라
#    **여유·이중화**를 얻는 운전으로 봐야 한다. 배합 최적화의 제약식도 이렇게 세운다.
#
# 용도(다음 갱신 때):
#   ① 교대별 적재 기록을 **능력 상한으로 감사** — 상한 초과 기록은 물리적으로 불가능하다.
#      (사전 점검: 49Q 159개 교대 중 G/C 상한 초과 0건, 최대 1,564 t/h 로 상한에 근접 →
#       사용자 제시 능력치가 실측과 정합. H/C 상한 초과 32건은 G/C·동시가동 구간일 것.)
#   ② 재고 추이 재분석 — 생산방법별 처리율로 적재 곡선을 세분화한다.
CRUSHER_CAPACITY_TPH = {
    "G/C": (1500, 1600),        # 자이레토리
    "H/C": (1000, 1100),        # 함마
    "G/C+H/C": (1500, 1600),    # 동시 가동 — 가산되지 않는다
}
COL_CRUSHER = "C/R"             # 다음 갱신본의 생산방법 컬럼명(예정)

# === 검증 게이트 스펙 (정제 후 tidy 프레임 기준) ===
# 매칭(조인) 전에 이 스펙으로 무결성을 검사한다. (CLAUDE.md §3 Matching-Agent 검증 게이트)
SPEC_MINE = SourceSpec(
    name="광산(정제)", time_col="date", cao_col="cao", tonnage_col="tonnage",
    key_cols=["date", "line", "zone"],
    expect_unique=False,   # 같은 일자·라인·구역에 교대/구간별 다중 기록이 정상
)
SPEC_OSP = SourceSpec(
    name="OSP인출(정제)", time_col="datetime", cao_col=None, tonnage_col="withdrawn_ton",
    key_cols=["datetime", "line", "zone"],
)
SPEC_YARD = SourceSpec(
    name="야드측정(정제)", time_col="datetime", cao_col="cao", tonnage_col="load",
    key_cols=["datetime"], allow_zero_tonnage=True,   # 설비 정지 시 적재량 0 가능
)
SPEC_YARDCHANGE = SourceSpec(
    name="야드변경(정제)", time_col="datetime", cao_col="cao", tonnage_col="tonnage",
    key_cols=["datetime", "line"],
)


# === 최종 품질 목표 (CLAUDE.md §1) ===
@dataclass(frozen=True)
class Target:
    cao_mean: float = 44.6
    cao_std_max: float = 0.5
    tol: float = 0.5

    @property
    def lower(self) -> float:
        return self.cao_mean - self.tol

    @property
    def upper(self) -> float:
        return self.cao_mean + self.tol


TARGET = Target()


# ── 채굴 교대 시간대 (사용자 확정, 2026-07-28) ──────────────────────────────
# 49Q 광산은 '채굴시간(교대)'만 있고 시각이 없다. 아래 시간대로 실제 시각을 부여한다.
#   1차 08:00~16:00 · 2차 16:00~24:00 · 3차 00:00~08:00 (모두 채굴일자 당일 기준)
# 값 = (시작 시, 종료 시). 종료 24 는 자정을 뜻한다.
SHIFT_HOURS = {
    "1차": (8, 16),
    "2차": (16, 24),
    "3차": (0, 8),
}

# 교대 인수인계 시간(분). 교대 시작 직후 이 시간만큼은 실제 채굴이 이뤄지지 않는다.
# 대표 시각(중점) 계산에 반영할지는 HANDOVER_APPLIED 로 결정한다.
HANDOVER_MINUTES = 30

# 인수인계 시간 반영 여부.
# 검증 결과 대표 시각이 15분 움직일 뿐이고 구간 귀속이 바뀌는 행이 없어 제외한다.
# (구간 최소 길이 42시간 대비 15분 = 0.6%. 사용자 지침: 큰 차이 없으면 제외)
HANDOVER_APPLIED = False


# ── OSP 실사 재고 (2026-07-30 추가) ────────────────────────────────────────
SHEET_OSP_STOCK = "OSP 재고"

# 시트 배치: 좌우 2블록이 나란히 (가운데 4번 열은 빈 칸)
#   0~3열 = OSP1(기존 라인) · 5~8열 = OSP2(신설 라인), 헤더는 3번째 행(index 2)
STOCK_BLOCKS = {"OSP1": [0, 1, 2, 3], "OSP2": [5, 6, 7, 8]}
STOCK_HEADER_ROW = 2
OSP_TO_LINE = {"OSP1": LINE_OLD, "OSP2": LINE_NEW}

# 재고 실사 시각(사용자 확정): 교대 중간에 1시간 동안 파악 → 그 중점을 대표 시각으로
#   1차 12~13시 → 12:30 · 2차 20~21시 → 20:30 · 3차 04~05시 → 04:30
# (채굴 교대 중점 SHIFT_HOURS 와는 별개다 — 실사는 교대 중간에 따로 이뤄진다)
STOCK_TAKE_HOURS = {1: 12.5, 2: 20.5, 3: 4.5}

# 실사값은 1,000톤 단위 개략치다(전 구간 100%가 1,000의 배수, 고유값 27개).
# 절대 수준 파악에는 쓰되, 소수점 단위 정밀 대조에는 쓰지 않는다.
STOCK_ROUNDING_TON = 1000
