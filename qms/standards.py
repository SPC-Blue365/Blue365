"""관리항목 정의 · KS 규격 · 사내 관리기준.

3단계 기준 체계
---------------
1) KS 규격 한계 (ks_min / ks_max) — 법정·인증 품질기준. 이탈 시 '위험'
2) 사내 관리기준 (lsl / usl / target) — 공장이 정한 규격 여유를 둔 기준. 이탈 시 '경고'
3) 통계적 관리한계 (UCL / LCL, 판정규칙) — 공정 불안정 조기 감지. 위반 시 '주의'

KS 규격값 출처 (2026-10 웹 검색으로 확인, 원문 대조 권장)
- KS L 5201 포틀랜드 시멘트 (e나라표준인증 https://standard.go.kr, 한국시멘트협회 KS 규격 요약
  http://www.cement.or.kr/tech_2014/standard.asp?sm=3_6_1)
  · 압축강도 1종: 3일 12.5 / 7일 22.5 / 28일 42.5 MPa 이상
  · 압축강도 3종: 1일 10.0 / 3일 20.0 / 7일 32.5 / 28일 47.5 MPa 이상
  · 분말도(비표면적) 1종 2,800, 3종 3,300 cm²/g 이상
  · 응결시간(비카) 초결 60분 이상, 종결 10시간 이하
  · 안정도(오토클레이브 팽창도) 0.8% 이하
  · MgO 5.0% 이하, SO3 1종 3.5% / 3종 4.5% 이하, 강열감량 5.0% 이하(2016 개정 3.0→5.0%)
- 강도 시험조건: KS L ISO 679 (ISO 679) — 시험실 20±2 ℃·상대습도 50% 이상, 양생수 20±1 ℃
  (ISO 679 규정값을 적용, KS L ISO 679 원문 대조 권장)

사내 관리기준의 기본값은 업계 경험칙에 근거한 '초기값'이다. 반드시 공장 실제 기준으로 교체해야 한다
(⚙️ 관리기준 설정 화면에서 수정 → data/standards_user.json 에 저장).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

# 데이터 폴더(환경변수 QMS_DATA_DIR 로 변경 가능 — 테스트·다중 공장 운영용)
DATA_DIR = Path(os.environ.get("QMS_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
USER_STANDARDS_PATH = DATA_DIR / "standards_user.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

KS_L5201 = "KS L 5201 포틀랜드 시멘트"
KS_ISO679 = "KS L ISO 679 강도 시험방법(ISO 679 시험조건)"
EMPIRICAL = "경험칙 초기값 — 공장 기준으로 교체 필요"

PRODUCTS: dict[str, str] = {
    "1종": "보통 포틀랜드 시멘트 (KS L 5201 1종)",
    "3종": "조강 포틀랜드 시멘트 (KS L 5201 3종)",
}

STAGES: list[str] = ["원료(생료)", "소성(킬른)", "클링커", "시멘트(분쇄)", "제품 물성", "시험 조건"]

# 데이터 테이블 정의. spc_resample: SPC 판정규칙을 적용할 집계 단위.
# 2시간·1시간 데이터는 자기상관이 커서 원 데이터에 런(run) 규칙을 적용하면 허위 경보가 많으므로
# 8시간(근무조) 평균에 적용한다. 규격·관리기준 이탈은 개별값 기준으로 판정한다.
TABLES: dict[str, dict] = {
    "raw_meal": {"label": "생료(킬른 피드)", "freq": "2시간", "by_product": False, "spc_resample": "8h", "merge_gap": "12h"},
    "kiln": {"label": "킬른 운전(DCS)", "freq": "1시간", "by_product": False, "spc_resample": "8h", "merge_gap": "12h"},
    "clinker": {"label": "클링커", "freq": "2시간", "by_product": False, "spc_resample": "8h", "merge_gap": "12h"},
    "cement": {"label": "시멘트(밀 출구)", "freq": "2시간", "by_product": True, "spc_resample": "8h", "merge_gap": "12h"},
    "physical": {"label": "물성·강도(로트)", "freq": "1일", "by_product": True, "spc_resample": None, "merge_gap": "3D"},
}

QC_RULES = ("R1", "R2", "R3", "R5", "R6")  # 시험실 분석 항목에 적용 가능한 판정규칙
DCS_RULES = ("R1",)              # 자기상관이 큰 DCS 연속 데이터는 R1만 기본 적용


@dataclass(frozen=True)
class Limits:
    """품종별 기준값. None 은 '해당 없음'."""
    lsl: float | None = None
    usl: float | None = None
    target: float | None = None
    ks_min: float | None = None
    ks_max: float | None = None


@dataclass
class ItemSpec:
    key: str
    name: str
    stage: str
    table: str
    unit: str
    decimals: int = 2
    limits: dict[str, Limits] = field(default_factory=dict)  # "*" = 전 품종 공통
    ks_ref: str = ""
    basis: str = EMPIRICAL
    rules: tuple[str, ...] = ()        # 적용 SPC 판정규칙 (빈 튜플 = SPC 미적용)
    key_item: bool = False             # 핵심관리항목(대시보드 상시 표시)
    ks_is_method: bool = False         # 시험조건 기준(이탈 시 '경고', 결과 신뢰성 문제)
    prediction: bool = False           # 예측값(심각도 한 단계 하향)
    description: str = ""

    def limits_for(self, product: str | None = None) -> Limits:
        if product and product in self.limits:
            return self.limits[product]
        return self.limits.get("*", Limits())

    def label(self) -> str:
        return f"{self.name} ({self.unit})" if self.unit else self.name


def _L(**kw) -> Limits:
    return Limits(**kw)


def _default_items() -> list[ItemSpec]:
    items: list[ItemSpec] = []
    add = items.append

    # ── 원료(생료 / 킬른 피드) ─────────────────────────────────────────────
    for key, name in [("rm_cao", "생료 CaO"), ("rm_sio2", "생료 SiO₂"), ("rm_al2o3", "생료 Al₂O₃"),
                      ("rm_fe2o3", "생료 Fe₂O₃"), ("rm_so3", "생료 SO₃"), ("rm_k2o", "생료 K₂O"),
                      ("rm_na2o", "생료 Na₂O")]:
        add(ItemSpec(key, name, "원료(생료)", "raw_meal", "%", 2, basis="모니터링 항목(기준 미설정)"))
    add(ItemSpec("rm_mgo", "생료 MgO", "원료(생료)", "raw_meal", "%", 2,
                 {"*": _L(usl=2.5)}, rules=("R1",),
                 description="석회석 내 백운석(돌로마이트) 혼입 지표. 클링커 MgO≈생료×1.55"))
    add(ItemSpec("rm_lsf", "생료 LSF", "원료(생료)", "raw_meal", "", 1,
                 {"*": _L(lsl=97.0, usl=101.0, target=99.0)}, rules=QC_RULES, key_item=True,
                 description="석탄회 흡수로 클링커 LSF는 생료보다 약 3~4 낮아짐(공장별 상이)"))
    add(ItemSpec("rm_sm", "생료 SM", "원료(생료)", "raw_meal", "", 2,
                 {"*": _L(lsl=2.35, usl=2.75, target=2.55)}, rules=QC_RULES, key_item=True))
    add(ItemSpec("rm_im", "생료 IM", "원료(생료)", "raw_meal", "", 2,
                 {"*": _L(lsl=1.40, usl=1.80, target=1.58)}, rules=QC_RULES))
    add(ItemSpec("rm_r90", "생료 90μm 잔사", "원료(생료)", "raw_meal", "%", 1,
                 {"*": _L(usl=16.0, target=13.0)}, rules=QC_RULES, key_item=True,
                 description="조대 석영·방해석 입자 → 소성성 저하, f-CaO 상승"))
    add(ItemSpec("rm_r200", "생료 200μm 잔사", "원료(생료)", "raw_meal", "%", 2,
                 {"*": _L(usl=1.5, target=1.0)}, rules=("R1",)))

    # ── 소성(킬른 DCS) ────────────────────────────────────────────────────
    add(ItemSpec("kiln_feed", "원료 투입량", "소성(킬른)", "kiln", "t/h", 1, basis="운전 변수(기준 미설정)"))
    add(ItemSpec("coal_rate", "석탄 투입량", "소성(킬른)", "kiln", "t/h", 2, basis="운전 변수(기준 미설정)"))
    add(ItemSpec("kiln_bzt", "소성대 온도(파이로미터)", "소성(킬른)", "kiln", "℃", 0,
                 {"*": _L(lsl=1380, usl=1470, target=1420)}, rules=DCS_RULES, key_item=True,
                 description="측정 위치·방사율 설정에 따라 절대값이 공장마다 다름"))
    add(ItemSpec("kiln_o2", "킬른 입구 O₂", "소성(킬른)", "kiln", "%", 2,
                 {"*": _L(lsl=2.0, usl=4.5, target=3.0)}, rules=DCS_RULES))
    add(ItemSpec("kiln_co", "킬른 입구 CO", "소성(킬른)", "kiln", "%", 3,
                 {"*": _L(usl=0.30, target=0.05)}, key_item=True,
                 description="환원 분위기 지표. 클링커 품질 저하·SO₃ 휘발·EP CO 트립 위험"))
    add(ItemSpec("kiln_torque", "킬른 주모터 부하", "소성(킬른)", "kiln", "%", 1,
                 basis="운전 변수(기준 미설정)", description="소성 상태·코팅 상태의 간접 지표"))
    add(ItemSpec("kiln_calc_temp", "하소로 출구 온도", "소성(킬른)", "kiln", "℃", 0,
                 {"*": _L(lsl=855, usl=895, target=875)}, rules=DCS_RULES))
    add(ItemSpec("kiln_sec_air", "2차 공기 온도", "소성(킬른)", "kiln", "℃", 0,
                 {"*": _L(lsl=950, target=1050)}, rules=DCS_RULES))

    # ── 클링커 ────────────────────────────────────────────────────────────
    for key, name in [("clk_cao", "클링커 CaO"), ("clk_sio2", "클링커 SiO₂"), ("clk_al2o3", "클링커 Al₂O₃"),
                      ("clk_fe2o3", "클링커 Fe₂O₃"), ("clk_so3", "클링커 SO₃"), ("clk_k2o", "클링커 K₂O"),
                      ("clk_na2o", "클링커 Na₂O"), ("clk_c2s", "클링커 C₂S"), ("clk_c4af", "클링커 C₄AF")]:
        add(ItemSpec(key, name, "클링커", "clinker", "%", 2, basis="모니터링 항목(기준 미설정)"))
    add(ItemSpec("clk_mgo", "클링커 MgO", "클링커", "clinker", "%", 2, {"*": _L(usl=4.5)},
                 rules=("R1",), description="KS 시멘트 MgO 5.0% 이하 대응. 페리클레이스 → 안정도 불량"))
    add(ItemSpec("clk_fcao", "클링커 자유석회(f-CaO)", "클링커", "clinker", "%", 2,
                 {"*": _L(lsl=0.4, usl=1.8, target=1.0)}, rules=QC_RULES, key_item=True,
                 description="소성 상태의 핵심 지표. 과고=소성 부족/LSF 과다, 과저=과소성(연료 낭비)"))
    add(ItemSpec("clk_lw", "클링커 리터중량", "클링커", "clinker", "g/L", 0,
                 {"*": _L(lsl=1200, usl=1400, target=1300)}, rules=("R1",),
                 description="소성도 지표(측정 입도·방법에 따라 절대값 상이)"))
    add(ItemSpec("clk_lsf", "클링커 LSF", "클링커", "clinker", "", 1,
                 {"*": _L(lsl=93.0, usl=97.5, target=95.0)}, rules=QC_RULES, key_item=True))
    add(ItemSpec("clk_sm", "클링커 SM", "클링커", "clinker", "", 2,
                 {"*": _L(lsl=2.30, usl=2.70, target=2.50)}, rules=QC_RULES))
    add(ItemSpec("clk_im", "클링커 IM", "클링커", "clinker", "", 2,
                 {"*": _L(lsl=1.40, usl=1.80, target=1.60)}, rules=QC_RULES))
    add(ItemSpec("clk_c3s", "클링커 C₃S(Bogue)", "클링커", "clinker", "%", 1,
                 {"*": _L(lsl=53.0, usl=63.0, target=57.5)}, rules=QC_RULES, key_item=True,
                 description="28일 강도의 주 기여 광물. Bogue 계산값은 XRD 실측과 차이가 있음"))
    add(ItemSpec("clk_c3a", "클링커 C₃A(Bogue)", "클링커", "clinker", "%", 1, {"*": _L(usl=10.5)},
                 rules=("R1",), description="초기 수화·응결·황산염 저항성에 영향"))
    add(ItemSpec("clk_liquid", "액상량(1450℃)", "클링커", "clinker", "%", 1,
                 {"*": _L(lsl=24.0, usl=29.0, target=26.5)}, rules=("R1",)))
    add(ItemSpec("clk_na2oeq", "클링커 등가알칼리", "클링커", "clinker", "%", 2, {"*": _L(usl=0.90)},
                 rules=("R1",)))

    # ── 시멘트(분쇄, 품종별) ─────────────────────────────────────────────
    add(ItemSpec("cem_blaine", "시멘트 분말도(Blaine)", "시멘트(분쇄)", "cement", "cm²/g", 0,
                 {"1종": _L(lsl=3250, usl=3700, target=3450, ks_min=2800),
                  "3종": _L(lsl=4350, usl=4850, target=4600, ks_min=3300)},
                 ks_ref=KS_L5201, rules=QC_RULES, key_item=True))
    add(ItemSpec("cem_r45", "시멘트 45μm 잔사", "시멘트(분쇄)", "cement", "%", 1,
                 {"1종": _L(usl=12.0, target=9.5), "3종": _L(usl=5.0, target=3.0)}, rules=("R1",)))
    add(ItemSpec("cem_so3", "시멘트 SO₃", "시멘트(분쇄)", "cement", "%", 2,
                 {"1종": _L(lsl=2.30, usl=3.00, target=2.60, ks_max=3.5),
                  "3종": _L(lsl=2.90, usl=3.60, target=3.20, ks_max=4.5)},
                 ks_ref=KS_L5201, rules=QC_RULES, key_item=True,
                 description="석고 최적 SO₃ 이탈 시 강도·응결 변동"))
    add(ItemSpec("cem_loi", "시멘트 강열감량", "시멘트(분쇄)", "cement", "%", 2,
                 {"1종": _L(usl=3.80, target=2.80, ks_max=5.0), "3종": _L(usl=3.00, target=2.00, ks_max=5.0)},
                 ks_ref=KS_L5201 + " (2016 개정 5.0%)", rules=("R1",)))
    add(ItemSpec("cem_mgo", "시멘트 MgO", "시멘트(분쇄)", "cement", "%", 2,
                 {"*": _L(usl=4.50, ks_max=5.0)}, ks_ref=KS_L5201, rules=("R1",)))
    add(ItemSpec("cem_mill_feed", "시멘트밀 투입량", "시멘트(분쇄)", "cement", "t/h", 1,
                 basis="운전 변수(기준 미설정)"))
    add(ItemSpec("cem_mill_temp", "시멘트밀 출구 온도", "시멘트(분쇄)", "cement", "℃", 0,
                 {"*": _L(lsl=90, usl=120, target=105)}, rules=DCS_RULES,
                 description="과고 시 이수석고 탈수(반수석고화) → 위응결 위험"))

    # ── 제품 물성(로트, 품종별) ──────────────────────────────────────────
    add(ItemSpec("phy_ist", "초결 시간", "제품 물성", "physical", "분", 0,
                 {"1종": _L(lsl=150, usl=300, target=220, ks_min=60),
                  "3종": _L(lsl=120, usl=260, target=180, ks_min=60)},
                 ks_ref=KS_L5201 + " (비카 초결 60분 이상)", rules=("R1",)))
    add(ItemSpec("phy_fst", "종결 시간", "제품 물성", "physical", "분", 0,
                 {"1종": _L(usl=420, target=300, ks_max=600), "3종": _L(usl=380, target=260, ks_max=600)},
                 ks_ref=KS_L5201 + " (종결 10시간 이하)", rules=("R1",)))
    add(ItemSpec("phy_autoclave", "오토클레이브 팽창도", "제품 물성", "physical", "%", 2,
                 {"*": _L(usl=0.30, target=0.10, ks_max=0.80)}, ks_ref=KS_L5201 + " (안정도)", rules=("R1",)))
    add(ItemSpec("phy_s1", "1일 압축강도", "제품 물성", "physical", "MPa", 1,
                 {"3종": _L(lsl=16.0, target=20.0, ks_min=10.0)}, ks_ref=KS_L5201, rules=QC_RULES))
    add(ItemSpec("phy_s3", "3일 압축강도", "제품 물성", "physical", "MPa", 1,
                 {"1종": _L(lsl=25.0, target=29.5, ks_min=12.5), "3종": _L(lsl=32.0, target=37.0, ks_min=20.0)},
                 ks_ref=KS_L5201, rules=QC_RULES, key_item=True))
    add(ItemSpec("phy_s7", "7일 압축강도", "제품 물성", "physical", "MPa", 1,
                 {"1종": _L(lsl=36.0, target=40.0, ks_min=22.5), "3종": _L(lsl=42.0, target=46.0, ks_min=32.5)},
                 ks_ref=KS_L5201, rules=QC_RULES, key_item=True))
    add(ItemSpec("phy_s28", "28일 압축강도", "제품 물성", "physical", "MPa", 1,
                 {"1종": _L(lsl=48.0, target=53.0, ks_min=42.5), "3종": _L(lsl=54.0, target=59.0, ks_min=47.5)},
                 ks_ref=KS_L5201, rules=QC_RULES, key_item=True))
    add(ItemSpec("pred_s28", "28일 강도(예측)", "제품 물성", "physical", "MPa", 1,
                 {"1종": _L(lsl=48.0, target=53.0, ks_min=42.5), "3종": _L(lsl=54.0, target=59.0, ks_min=47.5)},
                 ks_ref=KS_L5201 + " (예측값 — 실측 확인 필요)", prediction=True, key_item=True,
                 description="조기 강도·화학 성분으로 회귀 예측. 28일 결과 전 조기 경보용"))

    # ── 시험 조건(강도 시험 유효성) ──────────────────────────────────────
    add(ItemSpec("lab_temp", "시험실 온도", "시험 조건", "physical", "℃", 1,
                 {"*": _L(ks_min=18.0, ks_max=22.0, target=20.0)}, ks_ref=KS_ISO679 + " 20±2℃",
                 ks_is_method=True))
    add(ItemSpec("lab_rh", "시험실 상대습도", "시험 조건", "physical", "%", 0,
                 {"*": _L(ks_min=50.0)}, ks_ref=KS_ISO679 + " 50% 이상", ks_is_method=True))
    add(ItemSpec("lab_cure_temp", "양생수 온도", "시험 조건", "physical", "℃", 1,
                 {"*": _L(ks_min=19.0, ks_max=21.0, target=20.0)}, ks_ref=KS_ISO679 + " 20±1℃",
                 ks_is_method=True))
    return items


DEFAULT_ITEMS: list[ItemSpec] = _default_items()


class SpecRegistry:
    """관리항목 레지스트리. 기본값 + 사용자 수정값(JSON)을 합쳐서 제공한다."""

    def __init__(self, items: list[ItemSpec] | None = None, overrides: dict | None = None):
        base = items if items is not None else _default_items()
        self._items: dict[str, ItemSpec] = {i.key: replace(i, limits=dict(i.limits)) for i in base}
        if overrides:
            self.apply_overrides(overrides)

    # 조회 ---------------------------------------------------------------
    def __getitem__(self, key: str) -> ItemSpec:
        return self._items[key]

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def get(self, key: str) -> ItemSpec | None:
        return self._items.get(key)

    def all(self) -> list[ItemSpec]:
        return list(self._items.values())

    def by_table(self, table: str) -> list[ItemSpec]:
        return [i for i in self._items.values() if i.table == table]

    def by_stage(self, stage: str) -> list[ItemSpec]:
        return [i for i in self._items.values() if i.stage == stage]

    def key_items(self) -> list[ItemSpec]:
        return [i for i in self._items.values() if i.key_item]

    def products_for(self, key: str) -> list[str | None]:
        """해당 항목을 평가할 품종 목록. 품종 구분이 없는 테이블은 [None]."""
        item = self._items[key]
        if not TABLES[item.table]["by_product"]:
            return [None]
        specific = [p for p in item.limits if p != "*"]
        return specific if specific else list(PRODUCTS)

    # 수정 ---------------------------------------------------------------
    def apply_overrides(self, overrides: dict) -> None:
        """overrides 형식: {item_key: {product_or_*: {lsl, usl, target}}}. KS 값은 수정 불가."""
        for key, per_product in overrides.items():
            item = self._items.get(key)
            if item is None:
                continue
            for product, vals in per_product.items():
                cur = item.limits.get(product, item.limits.get("*", Limits()))
                item.limits[product] = replace(
                    cur, **{k: _num_or_none(v) for k, v in vals.items() if k in ("lsl", "usl", "target")})

    def overrides_vs_default(self) -> dict:
        """기본값과 다른 사내 기준만 추출(저장용)."""
        defaults = {i.key: i for i in _default_items()}
        out: dict = {}
        for key, item in self._items.items():
            d = defaults.get(key)
            for product, lim in item.limits.items():
                dl = d.limits.get(product, d.limits.get("*", Limits())) if d else Limits()
                diff = {k: getattr(lim, k) for k in ("lsl", "usl", "target") if getattr(lim, k) != getattr(dl, k)}
                if diff:
                    out.setdefault(key, {})[product] = diff
        return out


def _num_or_none(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN → None


def load_registry(path: Path = USER_STANDARDS_PATH) -> SpecRegistry:
    overrides = {}
    if path.exists():
        try:
            overrides = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            overrides = {}
    return SpecRegistry(overrides=overrides)


def save_registry(reg: SpecRegistry, path: Path = USER_STANDARDS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reg.overrides_vs_default(), ensure_ascii=False, indent=2), encoding="utf-8")


# ── 시스템 설정(SPC·알림) ───────────────────────────────────────────────
DEFAULT_SETTINGS: dict = {
    "baseline_days": 30,        # SPC 기준기간: 데이터 시작일부터 N일 (안정 구간으로 지정)
    "baseline_start": None,     # 직접 지정 시 'YYYY-MM-DD'
    "baseline_end": None,
    "enabled_rules": ["R1", "R2", "R3"],  # 전역 활성 규칙(항목별 허용 규칙과 교집합 적용)
    "run_length": 9,            # R2: 중심선 한쪽 연속 점 수
    "trend_length": 6,          # R3: 연속 증가/감소 점 수
    "notify_min_severity": "경고",
    "evidence_baseline_days": 14,  # 원인 진단 시 비교 기준(이벤트 직전 N일)
}


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if path.exists():
        try:
            settings.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def save_settings(settings: dict, path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
