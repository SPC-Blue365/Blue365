"""원인 가설 지식베이스 (화학 · 원료 · 공정 · 설비 · 시험오차 5축).

각 이상 현상(항목 × 방향)에 대해 원인 가설을 정의한다. 가설마다
  - mechanism : 메커니즘 설명 (근거 수준을 basis 로 표기: 이론/문헌/경험칙)
  - checks    : 데이터로 검증할 수 있는 증거 조건 (diagnosis 모듈이 자동 평가)
  - verify    : 사람이 추가로 확인할 시험·현장 점검 항목
  - short_term: 단기 조치(재발·확산 방지, 수일 이내)
  - root_cause: 근본 대책(재발 방지, 시스템·기준 개선)
  - prior     : 사전 가중치(경험상 발생 빈도, 1.0 = 보통)

Check.lag = (a, b) 시간 단위: 증거를 볼 구간 = [이벤트 시작 − b시간, 이벤트 종료 − a시간]
  · (0, 0)     이벤트와 같은 시간대
  · (-12, 12)  로트(정오 기준) 생산일 전체
  · (12, 60)   시멘트 생산 1~2일 전 클링커(사일로 체류 가정)
  · (2, 8)     클링커 2~8시간 전 생료(프리히터·킬른 체류 + 시료 지연)
  · (0, 4)     클링커 0~4시간 전 킬른 운전
  · (-8, -2)   이벤트 2~8시간 후 (하류 공정 반영 여부 확인)

특수 증거
  __resid    28일 강도 실측 − 조기강도 기반 예측(LOO 잔차 z). 크게 음수면 시험오차/후기강도 요인
  __isolated 이벤트가 1~2점의 단발성이면 시험·시료 채취 오차 가능성 ↑

※ 본 지식베이스의 정량 수치(예: 'Blaine 100 cm²/g 당 강도 약 1 MPa')는 업계 경험칙이며
  공장마다 다르다. 공장 데이터 회귀분석·실험으로 검증 후 수정해 사용할 것.
"""

from __future__ import annotations

from dataclasses import dataclass, field

AXES = ["화학", "원료", "공정", "설비", "시험오차"]
AXIS_ICON = {"화학": "⚗️", "원료": "⛰️", "공정": "🔥", "설비": "⚙️", "시험오차": "🧪"}

SAME = (0, 0)
DAY = (-12, 12)
CLK_FOR_CEM = (12, 60)
RM_FOR_CEM = (14, 68)
RM_FOR_CLK = (2, 8)
KILN_FOR_CLK = (0, 4)
AFTER = (-8, -2)


@dataclass(frozen=True)
class Check:
    item: str
    expect: str                 # high | low | var | dev | out | change
    lag: tuple[float, float] = SAME
    weight: float = 1.0
    invert: bool = False        # True 이면 '변화가 없을수록' 지지 (예: 하류 미반영 → 분석오차)
    note: str = ""


@dataclass(frozen=True)
class Hypothesis:
    axis: str
    title: str
    mechanism: str
    checks: tuple[Check, ...] = ()
    verify: tuple[str, ...] = ()
    short_term: tuple[str, ...] = ()
    root_cause: tuple[str, ...] = ()
    prior: float = 1.0
    basis: str = "경험칙"
    owner: str = "품질"          # 확인 담당 부서(제안)


@dataclass(frozen=True)
class Phenomenon:
    title: str
    impact: str                       # 제품 품질·공정에 미치는 영향
    hypotheses: tuple[Hypothesis, ...] = field(default_factory=tuple)
    related_products: tuple[str, ...] = ()   # 영향 확인이 필요한 제품 항목


# ── 공통 가설 블록 ──────────────────────────────────────────────────────
def _h_c3s_low(lag=CLK_FOR_CEM, prior=1.0) -> Hypothesis:
    return Hypothesis(
        "화학", "클링커 C₃S 저하(광물 조성 변화)",
        "C₃S(알라이트)는 3~28일 강도의 주 기여 광물이다. 경험칙: C₃S 1%p 감소 시 28일 강도 약 0.3~0.5 MPa 감소"
        "(공장별 상이 — 자체 회귀분석으로 확인 필요).",
        (Check("clk_c3s", "low", lag, 1.0), Check("clk_lsf", "low", lag, 0.5)),
        ("해당 기간 클링커 XRF 재분석·Bogue C₃S 확인", "XRD-Rietveld 정량으로 C₃S/C₂S 실측(Bogue와 편차 확인)",
         "클링커 현미경 관찰(알라이트 크기·형태, 벨라이트 군집)"),
        ("분말도 상향(+100~150 cm²/g)으로 강도 보상(밀 생산성 저하 감수)", "해당 클링커 사용 제품의 3·7일 강도 추적 강화"),
        ("생료 LSF 목표·변동(σ) 관리 강화", "소성 운전 기준(소성대 온도·O₂·f-CaO 피드백) 표준화"),
        prior, "이론+경험칙", "품질")


def _h_underburn(lag_fcao=CLK_FOR_CEM, prior=1.0, for_strength=True) -> Hypothesis:
    return Hypothesis(
        "공정", "소성 부족(소성대 온도·열량 부족)",
        "소성대 온도·체류시간 부족 시 C₂S + CaO → C₃S 반응이 완결되지 않아 f-CaO↑, C₃S↓, 클링커가 다공질(리터중량↓)이 된다."
        + (" 그 결과 강도가 저하된다." if for_strength else ""),
        (Check("clk_fcao", "high", lag_fcao, 1.0), Check("kiln_bzt", "low", lag_fcao, 0.8),
         Check("clk_lw", "low", lag_fcao, 0.5), Check("kiln_sec_air", "low", lag_fcao, 0.3)),
        ("킬른 운전 추이(소성대 온도·주모터 부하·2차 공기 온도) 확인", "시간대별 f-CaO·리터중량 대조",
         "석탄 공업분석(발열량·회분·휘발분·수분)"),
        ("f-CaO 기준 초과 클링커 분리 저장 또는 혼합 비율 제한", "소성 강화(연료·버너 조정) 및 원료 투입량 일시 감량"),
        ("석탄 입고 품질 기준(발열량 하한) 및 혼탄 관리", "f-CaO 기반 소성 피드백 운전 기준서 수립", "버너 화염 형상 점검·개선"),
        prior, "이론+경험칙", "생산(소성)")


def _h_fineness_low(prior=1.0, early=False) -> Hypothesis:
    gain = "3일 강도 약 1~1.5 MPa" if early else "28일 강도 약 0.5~1 MPa"
    return Hypothesis(
        "공정", "분말도 저하·입도분포 조대화(분쇄 공정)",
        f"분말도는 수화 반응 표면적을 결정하며 특히 조기강도에 민감하다. 경험칙: Blaine 100 cm²/g 당 {gain}.",
        (Check("cem_blaine", "low", DAY, 1.0), Check("cem_r45", "high", DAY, 0.6)),
        ("Blaine·45μm 잔사 재측정", "레이저 입도분석(PSD, RRSB 균등계수 n)", "밀 운전 데이터(세퍼레이터 rpm·순환부하·투입량)"),
        ("세퍼레이터 속도 상향·밀 투입량 감량으로 분말도 회복", "분말도 미달 구간 제품 출하 보류·재시험"),
        ("분쇄 매체 충진율·마모 정기 관리", "세퍼레이터 정비 주기 수립", "분말도 자동제어(온라인 PSD 분석기) 도입 검토"),
        prior, "이론+경험칙", "생산(분쇄)")


def _h_so3_offopt(prior=0.8) -> Hypothesis:
    return Hypothesis(
        "화학", "SO₃(석고) 최적치 이탈",
        "SO₃가 최적치에서 벗어나면 C₃A 수화 제어가 부적절해져 강도가 저하된다. 과다 시 응결 지연·지연 팽창 위험, "
        "부족 시 급결·조기강도 저하.",
        (Check("cem_so3", "dev", DAY, 1.0),),
        ("SO₃ 재분석(XRF ↔ 중량법 KS L 5120 교차)", "석고 정량공급기 실적(설정 대비 실제)", "SO₃ 수준별 모르타르 강도 최적화 시험"),
        ("석고 투입 설정 복귀 및 공급기 점검", "SO₃ 이탈 구간 제품 분리·추가 시험"),
        ("석고 공급기 정기 교정·막힘 감지 알람", "품종별 최적 SO₃ 정기 재설정(분기 1회)"),
        prior, "이론+경험칙", "생산(분쇄)")


def _h_loi_high(prior=0.6) -> Hypothesis:
    return Hypothesis(
        "원료", "혼합재(석회석) 과다·클링커 풍화",
        "소량혼합성분(석회석) 증가 시 희석효과로 강도가 낮아진다. 강열감량 상승은 클링커 풍화(prehydration)·"
        "석고 결정수 영향일 수도 있다.",
        (Check("cem_loi", "high", DAY, 1.0),),
        ("LOI·CO₂ 분석으로 석회석 혼입률 추정", "혼합재 정량공급기 실적 확인", "클링커 저장기간·야적 여부 확인"),
        ("혼합재 투입률 설정 복귀",),
        ("혼합재 투입 자동제어·실적 모니터링", "클링커 저장 관리(선입선출·야적 최소화)"),
        prior, "경험칙", "생산(분쇄)")


def _h_raw_var(prior=0.6) -> Hypothesis:
    return Hypothesis(
        "원료", "생료 화학 변동 증가(LSF 변동성)",
        "생료 LSF 변동이 크면 과소성·소성부족 구간이 혼재해 클링커 품질 편차가 커지고 평균 강도가 낮아진다.",
        (Check("rm_lsf", "var", RM_FOR_CEM, 1.0), Check("clk_lsf", "var", CLK_FOR_CEM, 0.6)),
        ("생료 LSF 시간대별 표준편차 확인", "혼합사일로 레벨·혼합효과(입·출 σ 비) 확인"),
        ("원료 조합 제어 게인·샘플링 주기 점검",),
        ("원료 예비균질화(파일링) 운영 개선", "원료밀 조합제어(XRF 온라인 피드백) 고도화"),
        prior, "경험칙", "생산(원료)")


def _h_test_strength(age_label: str, with_resid: bool, prior=0.8) -> Hypothesis:
    checks = [Check("lab_cure_temp", "out", SAME, 1.0), Check("lab_temp", "out", SAME, 0.5),
              Check("lab_rh", "out", SAME, 0.3), Check("sand_lot", "change", SAME, 0.4)]
    if with_resid:
        checks.insert(0, Check("__resid", "low", SAME, 1.2,
                               note="조기강도·화학으로 설명되지 않는 28일 편차"))
    return Hypothesis(
        "시험오차", f"{age_label} 강도 시험 조건 이탈·시험 오차",
        "강도는 양생 온도(20±1 ℃)·시험실 조건·공시체 성형·재하 속도에 민감하다(KS L ISO 679). "
        "조기강도와 화학 성분이 정상인데 특정 재령만 낮으면 시험오차 가능성이 높다.",
        tuple(checks),
        ("양생수조 온도 기록 확인", "예비 공시체 재시험 또는 보관 시료 재성형", "재하 속도(2,400±200 N/s) 및 시험기 교정 상태 확인",
         "표준사 Lot·성형자 변경 여부 확인"),
        ("해당 로트 결과 보류 후 재시험으로 확정", "양생수조 온도 제어기 점검·수리"),
        ("양생조 온도 자동기록·이탈 알람(±1 ℃)", "시험자 간 비교시험(숙련도) 정기 실시", "시험기 정기 교정 관리"),
        prior, "규격+경험칙", "품질(시험실)")


def _h_cooling(prior=0.4) -> Hypothesis:
    return Hypothesis(
        "설비", "클링커 냉각 불량(냉각기)",
        "서랭 시 C₃S 분해·벨라이트 조대화·C₃A 결정화로 반응성이 낮아질 수 있다. 2차 공기 온도 저하는 냉각기 열회수 이상의 신호.",
        (Check("kiln_sec_air", "low", CLK_FOR_CEM, 0.6),),
        ("냉각기 그레이트 속도·냉각 팬 풍량 확인", "냉각기 출구 클링커 온도 확인", "클링커 현미경 관찰(알라이트 분해 흔적)"),
        ("냉각기 운전 조건(그레이트 속도·풍량) 조정",),
        ("냉각기 정비(그레이트 플레이트·팬) 계획 반영",),
        prior, "문헌+경험칙", "설비")


def _h_alkali(prior=0.4) -> Hypothesis:
    return Hypothesis(
        "화학", "알칼리 증가(후기강도 저하)",
        "알칼리(Na₂Oeq) 증가는 조기강도를 높이지만 28일 이후 강도 발현을 저해하는 경향이 있다(문헌·경험칙).",
        (Check("clk_na2oeq", "high", CLK_FOR_CEM, 0.8),),
        ("클링커·시멘트 K₂O/Na₂O 분석", "원료·연료 알칼리 투입량(바이패스 운전 여부) 확인"),
        ("바이패스 추기량 조정(설비 보유 시)",),
        ("원료·대체연료 알칼리 투입 관리 기준 수립",),
        prior, "문헌+경험칙", "품질")


def _h_isolated(what: str, prior=0.5) -> Hypothesis:
    return Hypothesis(
        "시험오차", f"{what} 분석·시료 채취 오차",
        "단발성 이탈이면서 연관 항목에 변화가 없으면 시료 대표성·분석 오차 가능성이 높다.",
        (Check("__isolated", "high", SAME, 1.0),),
        ("동일 시료 재분석(이중 분석)", "표준시료(CRM)로 분석기 점검", "시료 채취 위치·방법 확인"),
        ("재분석 결과로 판정 확정", "재분석 전까지 조치는 보류하되 다음 시료 채취 주기 단축"),
        ("분석기 일상 점검(표준시료 관리도) 운영", "시료 채취 절차서 정비"),
        prior, "경험칙", "품질(시험실)")


# ── 현상별 지식베이스 ───────────────────────────────────────────────────
def _strength_low(age: str) -> Phenomenon:
    early = age in ("1일", "3일", "7일")
    hyps = [
        _h_fineness_low(prior=1.3 if early else 0.9, early=early),
        _h_underburn(prior=1.0),
        _h_c3s_low(prior=1.0),
        _h_so3_offopt(prior=0.9 if early else 0.7),
        _h_test_strength(age, with_resid=(age == "28일"), prior=0.8),
        _h_raw_var(prior=0.5),
        _h_loi_high(prior=0.5),
        _h_cooling(prior=0.35),
    ]
    if age == "28일":
        hyps.append(_h_alkali())
    return Phenomenon(
        f"{age} 압축강도 저하",
        "KS L 5201 강도 기준 여유 감소 → 레미콘 배합 강도 확보 문제·고객 클레임 위험. 28일 결과는 생산 후 28일 뒤 확인되므로 "
        "조기강도·화학 지표로 선제 대응이 중요.",
        tuple(hyps), ("phy_s28",))


def _pred_low() -> Phenomenon:
    base = _strength_low("3일")
    return Phenomenon(
        "28일 강도 예측치 저하(조기 경보)",
        "실측 전 단계의 예측 경보. 예측 근거(조기강도·분말도·C₃S)의 이상을 먼저 해소하고 28일 실측으로 확인해야 한다.",
        tuple(h for h in base.hypotheses if h.axis != "시험오차") + (Hypothesis(
            "시험오차", "예측 모델 오차(입력 데이터·모델 한계)",
            "예측은 과거 데이터로 학습된 회귀식이다. 학습 범위를 벗어난 조건이거나 입력(조기강도) 자체가 오차를 포함할 수 있다.",
            (), ("예측 모델 R²·RMSE 확인", "조기강도 시험 조건 확인", "28일 실측 결과와 대조"),
            ("28일 실측 전까지 '예측 경보' 상태로 관리",), ("데이터 누적에 따른 모델 정기 재학습(월 1회)",),
            0.4, "통계", "품질"),),
        ("phy_s28",))


def _fcao_high() -> Phenomenon:
    return Phenomenon(
        "클링커 자유석회(f-CaO) 상승",
        "미반응 석회 증가 → C₃S 감소로 강도 저하, 과다 시 안정도(팽창) 불량 위험. 소성 상태의 1차 지표.",
        (
            _h_underburn(lag_fcao=KILN_FOR_CLK, prior=1.2, for_strength=False),
            Hypothesis("원료", "생료 LSF 과다(석회 과포화)",
                       "LSF가 높을수록 결합해야 할 CaO가 많아 같은 소성 조건에서 f-CaO가 증가한다. "
                       "경험칙: LSF +1 당 f-CaO 약 +0.2~0.3%p.",
                       (Check("rm_lsf", "high", RM_FOR_CLK, 1.0), Check("clk_lsf", "high", SAME, 1.0)),
                       ("생료·클링커 LSF 추이 확인", "석회석 품위(CaO) 및 채광 위치 변경 이력 확인"),
                       ("원료 조합비 보정(석회석 비율↓)", "목표 LSF 일시 하향"),
                       ("석회석 품위 예측(채광 시추 데이터) 기반 조합 관리", "조합 제어 응답시간 단축"),
                       1.0, "이론+경험칙", "생산(원료)"),
            Hypothesis("화학", "SM 과다·액상량 부족(난소성 조성)",
                       "SM이 높거나 액상량이 적으면 소성성이 나빠져 석회 결합이 지연된다.",
                       (Check("clk_sm", "high", SAME, 0.8), Check("clk_liquid", "low", SAME, 0.8)),
                       ("클링커 SM·IM·액상량 추이 확인", "부원료(규석·철광석) 투입 비율 확인"),
                       ("부원료 비율 조정으로 SM 복귀",), ("SM·IM 목표 범위 재설정(소성성 시험 기반)",),
                       0.6, "이론+경험칙", "생산(원료)"),
            Hypothesis("원료", "생료 분말도 조대(90·200μm 잔사 증가)",
                       "조대한 석영·방해석 입자는 반응성이 낮아 f-CaO가 남는다. 경험칙: 200μm 잔사(석영)가 특히 민감.",
                       (Check("rm_r90", "high", RM_FOR_CLK, 1.0), Check("rm_r200", "high", RM_FOR_CLK, 0.6)),
                       ("생료 잔사(90·200μm) 재측정", "원료밀 세퍼레이터·롤러 마모 상태 확인"),
                       ("원료밀 세퍼레이터 속도 조정",), ("원료밀 정비 주기·분말도 관리기준 재설정",),
                       0.7, "문헌+경험칙", "생산(원료)"),
            Hypothesis("공정", "연소 분위기 불량(CO↑·O₂↓)",
                       "공기 부족·불완전 연소는 화염 온도와 열전달을 떨어뜨리고 환원 분위기에서 클링커 품질을 저하시킨다.",
                       (Check("kiln_co", "high", KILN_FOR_CLK, 1.0), Check("kiln_o2", "low", KILN_FOR_CLK, 0.6)),
                       ("킬른 입구 가스(O₂·CO) 추이", "ID 팬·댐퍼 개도 확인", "석탄 미분도·공급 안정성 확인"),
                       ("O₂ 목표 상향(공기량 증가)", "석탄 공급 안정화"), ("연소 제어 루프(O₂·CO 기반) 튜닝",),
                       0.8, "이론+경험칙", "생산(소성)"),
            Hypothesis("원료", "석탄 품질 저하(발열량↓)",
                       "발열량이 낮은 석탄은 같은 투입량에서 열량이 부족하다. 투입량을 늘렸는데도 소성대 온도가 낮으면 석탄 품질을 의심.",
                       (Check("coal_rate", "high", KILN_FOR_CLK, 0.8), Check("kiln_bzt", "low", KILN_FOR_CLK, 0.8)),
                       ("석탄 공업분석(발열량·회분·수분)", "석탄 입고 Lot·혼탄 비율 확인"),
                       ("고발열량 석탄 혼탄 비율 상향",), ("석탄 입고 검사 기준(발열량 하한) 강화",),
                       0.7, "경험칙", "생산(소성)"),
            Hypothesis("공정", "원료 투입량 증가(열부하 과다)",
                       "투입량 증가 대비 연료가 따라가지 못하면 소성이 부족해진다.",
                       (Check("kiln_feed", "high", KILN_FOR_CLK, 1.0),),
                       ("투입량 변경 이력 확인",), ("투입량 원복 또는 연료 증량",), ("투입량 변경 시 연료 연동 운전 기준",),
                       0.5, "경험칙", "생산(소성)"),
            _h_isolated("f-CaO"),
        ),
        ("phy_s28", "phy_autoclave"))


def _fcao_low() -> Phenomenon:
    return Phenomenon(
        "클링커 자유석회(f-CaO) 과저(과소성)",
        "품질상 문제는 적으나 연료 과다 사용·내화물 손상·클링커 분쇄성 저하(밀 동력 증가)의 신호.",
        (
            Hypothesis("공정", "과소성(소성대 온도 과다)",
                       "필요 이상의 열량은 f-CaO를 과도하게 낮추고 연료 원단위를 높인다.",
                       (Check("kiln_bzt", "high", KILN_FOR_CLK, 1.0), Check("coal_rate", "high", KILN_FOR_CLK, 0.5)),
                       ("소성대 온도·석탄 원단위 확인",), ("석탄 투입량 감량",), ("f-CaO 목표 범위 기반 연료 최적 운전",),
                       1.0, "이론", "생산(소성)"),
            Hypothesis("원료", "생료 LSF 저하",
                       "LSF가 낮으면 쉽게 결합되어 f-CaO가 낮아지지만 C₃S도 줄어 강도가 저하될 수 있다.",
                       (Check("rm_lsf", "low", RM_FOR_CLK, 1.0), Check("clk_lsf", "low", SAME, 1.0)),
                       ("생료·클링커 LSF 확인",), ("조합비 보정(석회석 비율↑)",), ("LSF 제어 정밀도 향상",),
                       1.0, "이론", "생산(원료)"),
            Hypothesis("공정", "원료 투입량 감소",
                       "투입량 감소 시 열부하가 줄어 과소성되기 쉽다.",
                       (Check("kiln_feed", "low", KILN_FOR_CLK, 1.0),), ("투입량 변경 이력 확인",),
                       ("연료 감량",), ("투입량-연료 연동 운전",), 0.5, "경험칙", "생산(소성)"),
            _h_isolated("f-CaO"),
        ))


def _lsf(table_prefix: str, direction: str) -> Phenomenon:
    up = direction == "high"
    word = "상승" if up else "저하"
    impact = ("LSF↑ → 난소성·f-CaO↑·연료 증가" if up else "LSF↓ → C₃S↓·강도 저하") + " (클링커 품질 직결)"
    if table_prefix == "rm":
        hyps = (
            Hypothesis("원료", f"석회석 품위(CaO) {'상승' if up else '저하'}",
                       "채광 벤치·구역 변경, 협잡물(점토·규석질) 혼입 변화로 석회석 CaO 품위가 바뀌면 생료 LSF가 변한다.",
                       (Check("rm_cao", direction, SAME, 1.0),),
                       ("석회석 입고 분석(CaO·SiO₂) 및 채광 위치 확인", "예비균질화 파일 성분 확인"),
                       ("원료 조합비 즉시 보정", "자동 조합 제어 목표값 재확인"),
                       ("채광 계획 단계 품위 관리(시추 데이터 블렌딩)", "예비균질화 효과(파일링 방식) 개선"),
                       1.2, "경험칙", "생산(원료)·채광"),
            Hypothesis("원료", "부원료(점토·규석·철광석) 성분·투입 변동",
                       "SiO₂ 공급원이 줄거나 늘면 LSF가 반대로 움직인다.",
                       (Check("rm_sio2", "low" if up else "high", SAME, 1.0),),
                       ("부원료 입고 분석", "부원료 정량공급기 실적"),
                       ("부원료 투입 설정 보정",), ("부원료 입고 검사·저장 관리 강화",), 0.9, "경험칙", "생산(원료)"),
            Hypothesis("설비", "원료 정량공급기 편차·호퍼 막힘",
                       "정량공급기 교정 불량이나 원료 수분 증가에 따른 호퍼 브리징으로 실제 투입 비율이 설정과 달라진다.",
                       (), ("정량공급기 설정 vs 실적 비교", "호퍼 막힘·수분 이력 확인", "공급기 교정(실부하 검교정)"),
                       ("막힘 해소·공급기 점검",), ("공급기 정기 교정·편차 알람 설정",), 0.8, "경험칙", "설비"),
            Hypothesis("공정", "원료 조합 제어 지연(샘플링·피드백 주기)",
                       "분석 주기가 길거나 제어 게인이 부적절하면 원료 변동을 늦게 따라간다.",
                       (), ("조합 제어 로그(설정 변경 시각)와 LSF 변화 시각 비교",),
                       ("수동 보정 빈도 상향",), ("온라인 분석기(크로스벨트 등) 도입·제어 튜닝",), 0.6, "경험칙", "생산(원료)"),
            Hypothesis("시험오차", "XRF 검량선 드리프트·시료 대표성",
                       "생료 LSF가 변했는데 이후 클링커 LSF에 반영되지 않으면 분석 오차일 가능성이 있다.",
                       (Check("clk_lsf", direction, AFTER, 1.0, invert=True), Check("__isolated", "high", SAME, 0.6)),
                       ("표준시료(CRM)로 XRF 점검", "동일 시료 재분석", "자동 샘플러 상태 확인"),
                       ("재분석 후 조합 보정 여부 결정",), ("XRF 표준시료 관리도 운영",), 0.6, "경험칙", "품질(시험실)"),
        )
    else:
        hyps = (
            Hypothesis("원료", f"생료 LSF {word}",
                       "클링커 LSF는 생료 LSF와 석탄회 흡수로 결정된다.",
                       (Check("rm_lsf", direction, RM_FOR_CLK, 1.0),),
                       ("생료 LSF 추이 확인",), ("원료 조합비 보정",), ("생료 LSF 관리 정밀도 향상",), 1.2, "이론", "생산(원료)"),
            Hypothesis("공정", f"석탄회 흡수량 변화(연료 {'감소' if up else '증가'})",
                       "석탄회는 SiO₂·Al₂O₃가 많아 흡수량이 늘면 클링커 LSF가 낮아지고, 줄면 높아진다.",
                       (Check("coal_rate", "low" if up else "high", KILN_FOR_CLK, 0.8),),
                       ("석탄 투입량·회분 확인",), ("생료 목표 LSF에 석탄회 보정 반영",), ("석탄 회분 변동을 반영한 조합 설계",),
                       0.6, "이론", "생산(소성)"),
            _h_isolated("클링커 XRF"),
        )
    name = "생료" if table_prefix == "rm" else "클링커"
    return Phenomenon(f"{name} LSF {word}", impact, hyps, ("clk_fcao", "phy_s28"))


def _so3(direction: str) -> Phenomenon:
    up = direction == "high"
    return Phenomenon(
        f"시멘트 SO₃ {'과다' if up else '부족'}",
        ("KS L 5201 SO₃ 상한(1종 3.5%) 초과 시 규격 부적합. 과다 시 응결 지연·지연 팽창 위험" if up
         else "SO₃ 부족 시 C₃A 급결·위응결, 조기강도 저하 위험"),
        (
            Hypothesis("설비", "석고 정량공급기 이상(막힘·교정 불량)",
                       "석고 공급기 이상은 SO₃ 급변의 가장 흔한 원인이다(경험칙).",
                       (), ("공급기 설정 대비 실적 비교", "석고 호퍼 막힘·수분 확인", "공급기 실부하 교정"),
                       ("공급기 점검·설정 복귀", "SO₃ 분석 주기 단축(1시간)"),
                       ("공급기 편차 알람·정기 교정", "SO₃ 온라인 제어 루프 구축"), 1.3, "경험칙", "설비"),
            Hypothesis("원료", "석고 품위(순도) 변동",
                       "천연석고·배연탈황석고 혼용 비율이나 순도 변화로 같은 투입량에서도 SO₃가 달라진다.",
                       (), ("석고 입고 분석(SO₃·결정수)", "석고 혼용 비율 확인"),
                       ("석고 투입량 보정",), ("석고 입고 검사 기준·혼용 비율 관리",), 0.8, "경험칙", "품질"),
            Hypothesis("화학", f"클링커 SO₃ {'증가' if up else '감소'}(연료 황분·휘발)",
                       "연료 황분 증가나 소성 분위기 변화로 클링커 SO₃가 변하면 시멘트 SO₃도 변한다.",
                       (Check("clk_so3", direction, CLK_FOR_CEM, 1.0),),
                       ("클링커 SO₃·연료 황분 확인",), ("석고 투입량 보정",), ("클링커 SO₃를 반영한 석고 투입 제어",),
                       0.6, "이론", "품질"),
            _h_isolated("SO₃"),
        ),
        ("phy_ist", "phy_s28"))


def _blaine_low() -> Phenomenon:
    return Phenomenon(
        "시멘트 분말도(Blaine) 저하",
        "조기강도 저하(경험칙: 100 cm²/g 당 3일 강도 1~1.5 MPa) → 28일 강도 저하로 이어짐. KS 하한(1종 2,800) 근접 시 규격 위험.",
        (
            Hypothesis("설비", "세퍼레이터 분급 성능 저하",
                       "로터 속도 저하·블레이드 마모·풍량 변화 시 조립자가 제품으로 넘어가 분말도↓·45μm 잔사↑.",
                       (Check("cem_r45", "high", SAME, 1.0),),
                       ("세퍼레이터 rpm·풍량·차압 확인", "로터 블레이드 마모 점검", "제품·리젝트 입도 비교(Tromp 곡선)"),
                       ("세퍼레이터 속도 상향·풍량 조정", "분말도 회복까지 출하 품질 확인 강화"),
                       ("세퍼레이터 예방정비 주기 수립", "분급 효율 정기 평가(Tromp 곡선)"), 1.2, "경험칙", "설비"),
            Hypothesis("공정", "밀 투입량 과다",
                       "투입량을 늘리면 체류시간이 짧아져 분말도가 낮아진다.",
                       (Check("cem_mill_feed", "high", SAME, 1.0),),
                       ("투입량 변경 이력 확인",), ("투입량 원복",), ("분말도-투입량 연동 제어",), 0.9, "이론", "생산(분쇄)"),
            Hypothesis("설비", "분쇄 매체(볼) 마모·충진율 저하",
                       "볼 마모로 충진율·크기 분포가 변하면 분쇄 효율이 떨어진다.",
                       (), ("밀 전력 원단위 추이", "볼 충진율 측정(정지 시)", "밀 내부 다이어프램 막힘 점검"),
                       ("볼 보충 계획 앞당김",), ("볼 충진·분급 관리 기준 수립",), 0.8, "경험칙", "설비"),
            Hypothesis("원료", "클링커 분쇄성 저하(과소성·벨라이트↑)",
                       "과소성(조밀) 클링커나 C₂S가 많은 클링커는 분쇄가 어렵다.",
                       (Check("clk_lw", "high", CLK_FOR_CEM, 0.6), Check("clk_c2s", "high", CLK_FOR_CEM, 0.4)),
                       ("클링커 리터중량·C₂S 확인", "밀 전력 원단위 확인"), ("분쇄조제 투입 검토",),
                       ("클링커 품질 목표(리터중량·C₂S) 관리",), 0.5, "경험칙", "생산(소성)"),
            _h_isolated("분말도"),
        ),
        ("phy_s3", "phy_s7", "phy_s28"))


def _setting(direction: str, which: str) -> Phenomenon:
    up = direction == "high"
    if up:
        hyps = (
            Hypothesis("화학", "SO₃ 과다", "석고(SO₃) 증가는 C₃A 수화를 억제해 응결을 지연시킨다.",
                       (Check("cem_so3", "high", DAY, 1.0),), ("SO₃ 재분석",), ("석고 투입량 보정",),
                       ("품종별 SO₃ 최적치 관리",), 1.1, "이론", "생산(분쇄)"),
            Hypothesis("공정", "분말도 저하", "분말도가 낮으면 수화가 느려 응결이 지연된다.",
                       (Check("cem_blaine", "low", DAY, 1.0),), ("Blaine 재측정",), ("분말도 회복",),
                       ("분말도 관리 강화",), 0.9, "이론", "생산(분쇄)"),
            Hypothesis("원료", "분쇄조제·유기물 과다", "분쇄조제 과다 투입이나 유기물 혼입은 응결을 지연시킬 수 있다.",
                       (), ("분쇄조제 투입량 확인",), ("분쇄조제 투입량 복귀",), ("분쇄조제 투입 관리 기준",),
                       0.5, "경험칙", "생산(분쇄)"),
            Hypothesis("시험오차", "시험 온도·표준주도 조건", "시험실 온도가 낮거나 표준주도 수량이 많으면 응결이 길게 측정된다.",
                       (Check("lab_temp", "low", SAME, 1.0), Check("lab_temp", "out", SAME, 0.6)),
                       ("시험실 온도·표준주도 수량 확인", "재시험"), ("재시험으로 확정",), ("시험조건 기록 자동화",),
                       0.6, "규격+경험칙", "품질(시험실)"),
        )
    else:
        hyps = (
            Hypothesis("화학", "SO₃ 부족", "석고가 부족하면 C₃A가 급격히 수화해 응결이 빨라진다.",
                       (Check("cem_so3", "low", DAY, 1.0),), ("SO₃ 재분석",), ("석고 투입량 보정",),
                       ("품종별 SO₃ 최적치 관리",), 1.1, "이론", "생산(분쇄)"),
            Hypothesis("공정", "밀 출구 온도 과고(석고 탈수 → 위응결)",
                       "밀 온도가 높으면 이수석고가 반수석고로 탈수되어 위응결(false set)이 생길 수 있다.",
                       (Check("cem_mill_temp", "high", DAY, 1.0),), ("밀 출구 온도·살수량 확인",),
                       ("밀 살수·냉각 강화",), ("밀 온도 상한 관리(예: 120 ℃)",), 0.8, "문헌+경험칙", "생산(분쇄)"),
            Hypothesis("화학", "C₃A 증가", "C₃A가 많으면 초기 수화가 빨라 응결이 짧아진다.",
                       (Check("clk_c3a", "high", CLK_FOR_CEM, 1.0),), ("클링커 Al₂O₃·Fe₂O₃(IM) 확인",),
                       ("SO₃ 상향 검토",), ("IM 목표 관리",), 0.7, "이론", "품질"),
            Hypothesis("공정", "분말도 과다", "분말도가 높으면 수화가 빨라 응결이 짧아진다.",
                       (Check("cem_blaine", "high", DAY, 1.0),), ("Blaine 재측정",), ("분말도 조정",),
                       ("분말도 관리 범위 준수",), 0.6, "이론", "생산(분쇄)"),
            Hypothesis("시험오차", "시험 온도·표준주도 조건", "시험실 온도가 높으면 응결이 짧게 측정된다.",
                       (Check("lab_temp", "high", SAME, 1.0), Check("lab_temp", "out", SAME, 0.6)),
                       ("시험실 온도 확인", "재시험"), ("재시험으로 확정",), ("시험조건 기록 자동화",),
                       0.6, "규격+경험칙", "품질(시험실)"),
        )
    label = "초결" if which == "ist" else "종결"
    return Phenomenon(f"{label} 시간 {'지연' if up else '단축'}",
                      "KS L 5201: 초결 60분 이상, 종결 10시간 이하. 응결 이상은 레미콘 시공성(슬럼프 손실·마감)에 직접 영향.",
                      hyps, ("phy_ist", "phy_fst"))


def _autoclave_high() -> Phenomenon:
    return Phenomenon(
        "오토클레이브 팽창도(안정도) 상승",
        "KS L 5201 안정도 0.8% 이하. 페리클레이스(MgO)·f-CaO의 지연 수화 팽창은 구조물 균열로 이어질 수 있는 중대 품질 위험.",
        (
            Hypothesis("원료", "MgO 증가(석회석 백운석 혼입)",
                       "MgO가 클링커에 고용 한계(약 2%) 이상 들어가면 페리클레이스로 존재해 장기 팽창을 일으킨다.",
                       (Check("cem_mgo", "high", DAY, 1.0), Check("clk_mgo", "high", CLK_FOR_CEM, 1.0),
                        Check("rm_mgo", "high", RM_FOR_CEM, 0.6)),
                       ("시멘트·클링커·석회석 MgO 분석", "채광 구역별 MgO(백운석) 분포 확인", "XRD 페리클레이스 정량"),
                       ("고MgO 석회석 사용 중단·저MgO 원료와 블렌딩", "출하 전 안정도 시험 강화(로트별)"),
                       ("채광 계획에 MgO 품위 관리 반영", "클링커 급랭으로 페리클레이스 미세화"), 1.2, "이론+규격", "생산(원료)·채광"),
            Hypothesis("공정", "f-CaO 과다", "미반응 석회의 수화 팽창도 안정도를 악화시킨다.",
                       (Check("clk_fcao", "high", CLK_FOR_CEM, 1.0),), ("클링커 f-CaO 확인",),
                       ("소성 강화",), ("f-CaO 관리 강화",), 0.8, "이론", "생산(소성)"),
            Hypothesis("설비", "클링커 냉각 지연(페리클레이스 조대화)",
                       "서랭하면 페리클레이스 결정이 커져 팽창 위험이 커진다.",
                       (Check("kiln_sec_air", "low", CLK_FOR_CEM, 0.5),), ("냉각기 운전 상태 확인",),
                       ("냉각기 운전 조정",), ("냉각기 성능 개선",), 0.4, "문헌", "설비"),
            _h_isolated("오토클레이브 시험"),
        ),
        ("phy_autoclave",))


def _mgo_high(where: str) -> Phenomenon:
    checks = {"rm": (), "clk": (Check("rm_mgo", "high", RM_FOR_CLK, 1.0),),
              "cem": (Check("clk_mgo", "high", CLK_FOR_CEM, 1.0), Check("rm_mgo", "high", RM_FOR_CEM, 0.6))}[where]
    return Phenomenon(
        "MgO 상승",
        "KS L 5201 MgO 5.0% 이하. MgO 증가는 안정도(오토클레이브 팽창) 악화로 이어질 수 있다.",
        (
            Hypothesis("원료", "석회석 백운석(돌로마이트) 혼입",
                       "채광 구역 내 백운석질 석회석이 섞이면 MgO가 증가한다.",
                       checks, ("석회석 입고 MgO 분석", "채광 구역·벤치 확인", "파일 성분 확인"),
                       ("고MgO 원료 사용 비율 축소·블렌딩",), ("채광 계획 단계 MgO 품위 관리",), 1.3, "경험칙", "채광"),
            Hypothesis("원료", "부원료·대체원료 MgO", "슬래그 등 부원료의 MgO가 높을 수 있다.",
                       (), ("부원료 입고 분석",), ("부원료 비율 조정",), ("부원료 입고 기준 설정",), 0.5, "경험칙", "품질"),
            _h_isolated("MgO"),
        ),
        ("phy_autoclave",))


def _bzt_low() -> Phenomenon:
    return Phenomenon(
        "소성대 온도 저하",
        "소성 부족 → f-CaO↑·C₃S↓ → 강도 저하. 장시간 지속 시 코팅 불안정·클링커 더스트 증가.",
        (
            Hypothesis("원료", "석탄 품질 저하(발열량↓·수분↑)",
                       "투입량을 늘렸는데도 온도가 낮으면 석탄 발열량 저하를 의심한다.",
                       (Check("coal_rate", "high", SAME, 1.0),), ("석탄 공업분석", "입고 Lot 확인"),
                       ("고발열량 석탄 혼탄", "석탄 건조 강화"), ("석탄 입고 검사 기준 강화",), 1.1, "경험칙", "생산(소성)"),
            Hypothesis("공정", "원료 투입량 증가(열부하)", "투입량 증가 대비 연료 부족.",
                       (Check("kiln_feed", "high", SAME, 1.0),), ("투입량 변경 이력",), ("투입량 원복·연료 증량",),
                       ("투입량-연료 연동 운전",), 0.7, "이론", "생산(소성)"),
            Hypothesis("공정", "연소 공기 부족·불완전 연소", "O₂ 부족·CO 발생은 화염 온도를 낮춘다.",
                       (Check("kiln_o2", "low", SAME, 0.8), Check("kiln_co", "high", SAME, 1.0)),
                       ("O₂·CO 추이", "ID 팬 부하"), ("공기량 조정",), ("연소 제어 튜닝",), 0.9, "이론", "생산(소성)"),
            Hypothesis("설비", "냉각기 열회수 저하(2차 공기 온도↓)", "2차 공기 온도가 낮으면 화염 온도가 낮아진다.",
                       (Check("kiln_sec_air", "low", SAME, 1.0),), ("냉각기 운전·클링커 베드 두께 확인",),
                       ("냉각기 운전 조정",), ("냉각기 성능 개선",), 0.7, "이론", "설비"),
            Hypothesis("시험오차", "파이로미터 오염·방사율 설정 오류(계측 오차)",
                       "온도는 낮게 표시되는데 f-CaO가 정상이면 계측 오차 가능성이 있다.",
                       (Check("clk_fcao", "high", (-4, 0), 1.0, invert=True),),
                       ("파이로미터 렌즈·퍼지 에어 점검", "휴대용 온도계 비교 측정"), ("계측기 청소·재교정",),
                       ("계측기 정기 교정 계획",), 0.5, "경험칙", "설비(계장)"),
        ),
        ("clk_fcao", "phy_s28"))


def _co_high() -> Phenomenon:
    return Phenomenon(
        "킬른 입구 CO 상승",
        "환원 분위기 → 클링커 품질 저하(갈색 클링커·C₃S 분해 경향), SO₃ 휘발 증가로 프리히터 빌드업, "
        "EP(전기집진기) CO 트립 등 안전 위험.",
        (
            Hypothesis("공정", "연료 과다·공기 부족", "공기비 부족 시 불완전 연소로 CO가 발생한다.",
                       (Check("kiln_o2", "low", SAME, 1.0), Check("coal_rate", "high", SAME, 0.7)),
                       ("O₂·석탄 투입량 추이", "ID 팬·댐퍼 개도"), ("O₂ 목표 상향", "석탄 투입 안정화"),
                       ("연소 제어(O₂·CO 기반) 튜닝",), 1.2, "이론", "생산(소성)"),
            Hypothesis("설비", "버너·석탄 미분 공급 이상", "석탄 미분도 불량·공급 맥동·버너 팁 마모는 불완전 연소를 일으킨다.",
                       (), ("석탄 미분도(90μm 잔사)·수분", "석탄 공급기 맥동 확인", "버너 팁 점검"),
                       ("석탄밀 운전 조정",), ("버너·석탄 공급 설비 예방정비",), 0.9, "경험칙", "설비"),
            Hypothesis("원료", "석탄 품질 변화(휘발분·발열량)", "석탄 성상이 바뀌면 연소 특성이 변한다.",
                       (Check("kiln_bzt", "low", SAME, 0.6),), ("석탄 공업분석",), ("혼탄 비율 조정",),
                       ("석탄 입고 검사 강화",), 0.7, "경험칙", "생산(소성)"),
        ),
        ("clk_fcao",))


def _generic(name: str, direction: str) -> Phenomenon:
    word = "상승" if direction == "high" else "저하"
    return Phenomenon(
        f"{name} {word}",
        "지식베이스에 상세 가설이 등록되지 않은 항목입니다. 아래 5축 기본 점검을 수행하고 결과를 지식베이스에 반영하세요.",
        tuple(Hypothesis(axis, f"{axis} 요인 점검", desc, (), verify, ("원인 확인 전까지 측정 주기 단축",),
                         ("확인된 원인을 지식베이스(knowledge.py)에 등록",), 0.5, "추정", owner)
              for axis, desc, verify, owner in [
                  ("화학", "관련 산화물·광물 조성 변화 여부", ("관련 화학 성분 추이 확인",), "품질"),
                  ("원료", "원료·연료 품질 변화 여부", ("원료 입고 분석·Lot 변경 확인",), "생산(원료)"),
                  ("공정", "운전 조건 변경 여부", ("DCS 운전 이력·설정 변경 확인",), "생산"),
                  ("설비", "설비 이상·정비 이력", ("설비 점검·정비 이력 확인",), "설비"),
                  ("시험오차", "시료 채취·분석 오차", ("재분석·표준시료 확인",), "품질(시험실)")]))


def _lab_out(name: str) -> Phenomenon:
    return Phenomenon(
        f"{name} 이탈(시험조건)",
        "KS L ISO 679 시험조건 이탈 시 해당 기간 강도 시험 결과의 유효성이 떨어진다. 결과 보류·재시험 여부를 판단해야 한다.",
        (
            Hypothesis("설비", "항온·항습 설비 이상", "양생수조 히터/칠러, 시험실 공조기 고장·설정 오류.",
                       (), ("온도 기록계·제어기 상태 확인", "센서 교정 상태 확인"), ("설비 수리·예비 설비 사용",),
                       ("자동 기록·이탈 알람 체계", "정기 교정"), 1.2, "규격", "품질(시험실)"),
            Hypothesis("시험오차", "기록 오류·센서 오차", "측정 센서 위치·교정 오차 또는 기록 누락.",
                       (Check("__isolated", "high", SAME, 1.0),), ("기준 온도계로 비교 측정",), ("센서 재교정",),
                       ("센서 이중화",), 0.6, "경험칙", "품질(시험실)"),
        ),
        ("phy_s28", "phy_s7", "phy_s3"))


def build_kb() -> dict[tuple[str, str], Phenomenon]:
    kb: dict[tuple[str, str], Phenomenon] = {
        ("phy_s28", "low"): _strength_low("28일"),
        ("phy_s7", "low"): _strength_low("7일"),
        ("phy_s3", "low"): _strength_low("3일"),
        ("phy_s1", "low"): _strength_low("1일"),
        ("pred_s28", "low"): _pred_low(),
        ("clk_fcao", "high"): _fcao_high(),
        ("clk_fcao", "low"): _fcao_low(),
        ("rm_lsf", "high"): _lsf("rm", "high"),
        ("rm_lsf", "low"): _lsf("rm", "low"),
        ("clk_lsf", "high"): _lsf("clk", "high"),
        ("clk_lsf", "low"): _lsf("clk", "low"),
        ("cem_so3", "high"): _so3("high"),
        ("cem_so3", "low"): _so3("low"),
        ("cem_blaine", "low"): _blaine_low(),
        ("cem_r45", "high"): _blaine_low(),
        ("phy_ist", "high"): _setting("high", "ist"),
        ("phy_ist", "low"): _setting("low", "ist"),
        ("phy_fst", "high"): _setting("high", "fst"),
        ("phy_fst", "low"): _setting("low", "fst"),
        ("phy_autoclave", "high"): _autoclave_high(),
        ("rm_mgo", "high"): _mgo_high("rm"),
        ("clk_mgo", "high"): _mgo_high("clk"),
        ("cem_mgo", "high"): _mgo_high("cem"),
        ("kiln_bzt", "low"): _bzt_low(),
        ("kiln_co", "high"): _co_high(),
    }
    # 클링커 C3S 저하·리터중량 저하는 소성 부족/LSF 저하 가설로 설명
    kb[("clk_c3s", "low")] = Phenomenon(
        "클링커 C₃S 저하", "28일 강도의 주 기여 광물 감소 → 강도 저하 위험.",
        (_h_underburn(lag_fcao=SAME, prior=1.1, for_strength=False),
         Hypothesis("원료", "LSF 저하", "LSF가 낮으면 C₃S 생성량이 줄어든다.",
                    (Check("clk_lsf", "low", SAME, 1.0), Check("rm_lsf", "low", RM_FOR_CLK, 0.7)),
                    ("생료·클링커 LSF 확인",), ("조합비 보정",), ("LSF 관리 정밀도 향상",), 1.0, "이론", "생산(원료)"),
         _h_isolated("클링커 XRF")),
        ("phy_s28",))
    kb[("clk_lw", "low")] = Phenomenon(
        "클링커 리터중량 저하", "소성 부족(다공질 클링커) 신호 → f-CaO↑·강도 저하 위험.",
        (_h_underburn(lag_fcao=SAME, prior=1.2, for_strength=False),
         Hypothesis("화학", "난소성 조성(LSF·SM 과다)", "LSF·SM이 높으면 같은 조건에서 소성도가 낮아진다.",
                    (Check("clk_lsf", "high", SAME, 0.8), Check("clk_sm", "high", SAME, 0.6)),
                    ("클링커 LSF·SM 확인",), ("조합비 보정",), ("조합 목표 재설정",), 0.7, "이론", "생산(원료)"),
         _h_isolated("리터중량")),
        ("clk_fcao", "phy_s28"))
    for lab in ("lab_cure_temp", "lab_temp", "lab_rh"):
        name = {"lab_cure_temp": "양생수 온도", "lab_temp": "시험실 온도", "lab_rh": "시험실 습도"}[lab]
        kb[(lab, "high")] = _lab_out(name)
        kb[(lab, "low")] = _lab_out(name)
    return kb


KB = build_kb()


def lookup(item_key: str, direction: str, item_name: str = "") -> tuple[Phenomenon, bool]:
    """(현상, 등록 여부). 미등록 항목은 5축 기본 점검 가설을 반환."""
    ph = KB.get((item_key, direction))
    if ph is not None:
        return ph, True
    return _generic(item_name or item_key, direction), False
