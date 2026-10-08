"""AI 보고서 입력(JSON) 구성 — 계산 결과 요약만 담는다(원 데이터·개인정보 제외)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .chromium import (
    LIMIT_EU,
    LIMIT_EU_TEXT,
    LIMIT_KR,
    LIMIT_KR_TEXT,
    REDUCERS,
    ConvCalibration,
    CrBalance,
    reducer_retention,
    required_dose,
)
from .strength import FEATURE_INFO, INPUT_KEYS, TARGETS, ControlPlan, StrengthModels


def _r(v, nd=3):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if not np.isfinite(f) else round(f, nd)


def strength_context(product: str, sm: StrengthModels, inputs: dict, source: str, pred: pd.DataFrame,
                     plan: ControlPlan | None, goals: dict) -> dict:
    ctx = {
        "task": f"{product} 시멘트 재령별 강도·응결 예측과 제어 솔루션",
        "product": product,
        "input_source": source,
        "inputs": {FEATURE_INFO[k][0] + f" ({FEATURE_INFO[k][1]})": _r(inputs.get(k)) for k in INPUT_KEYS},
        "predictions": [{"item": r["항목"], "unit": r["단위"], "pred": _r(r["예측"], 2), "lo95": _r(r["하한(95%)"], 2),
                         "hi95": _r(r["상한(95%)"], 2), "KS": r["KS"], "plant_spec": r["사내"], "judgement": r["판정"]}
                        for _, r in pred.iterrows()],
        "goals": {TARGETS[t]["label"]: {"min": lo, "max": hi} for t, (lo, hi) in goals.items()},
        "models": {TARGETS[t]["label"]: {"source": m.source, "lots": m.n, "loo_rmse": _r(m.rmse, 2),
                                         "fixed_by_physics": list(m.fixed), "excluded_invalid_tests": m.n_excluded}
                   for t, m in sm.models.items()},
        "standards": {"KS L 5201 압축강도(MPa)": "1종 3일 12.5·7일 22.5·28일 42.5 이상 / 3종 1일 10.0·3일 20.0·7일 32.5·28일 47.5 이상",
                      "KS L 5201 응결": "초결 60분 이상, 종결 10시간 이하"},
    }
    m28 = sm.models.get("phy_s28")
    if m28 is not None:
        contrib = m28.contributions({**inputs, "so3dev2": (inputs.get("so3", np.nan) - sm.so3_opt) ** 2})
        ctx["drivers_28d_vs_typical_MPa"] = {FEATURE_INFO[k][0]: _r(v, 2) for k, v in
                                             sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:6]}
    if plan is not None:
        lt = plan.lever_table()
        ctx["optimizer"] = {
            "recommended_changes": [{"lever": r["레버"], "current": _r(r["현재"]), "recommended": _r(r["권장"]),
                                     "change": _r(r["변경"]), "unit": r["단위"], "how": r["실행 방법"]}
                                    for _, r in lt.iterrows()],
            "outcome": [{"item": r["항목"], "goal": r["목표"], "pred_now": _r(r["현재 예측"], 2),
                         "pred_after": _r(r["조정 후 예측"], 2), "status": r["판정"]}
                        for _, r in plan.outcome_table().iterrows()],
            "single_lever_alternatives": [{"goal_item": r["목표 항목"], "lever": r["레버"], "needed_change": _r(r["필요 변경"], 2),
                                           "unit": r["단위"], "within_range": r["조정 범위 내"]}
                                          for _, r in plan.single_lever.iterrows()] if len(plan.single_lever) else [],
            "messages": plan.messages,
            "note": "예측 모델 기반 추정 — 효과 수치는 실기 시험으로 확인 필요",
        }
    return ctx


def chromium_context(bal: CrBalance, tor: pd.DataFrame | None, cal: ConvCalibration | None,
                     measured_recent: dict | None = None) -> dict:
    p = bal.params
    ctx = {
        "task": "시멘트 수용성 6가크롬 예측과 저감 솔루션",
        "balance": {
            "clinker_total_cr_mg_kg": _r(bal.total_clk, 1), "kiln_conversion_pct": _r(p.conv_kiln, 2),
            "clinker_crvi_mg_kg": _r(bal.crvi_clk, 2), "clinker_fraction_pct": _r(bal.clinker_fraction * 100, 1),
            "cement_crvi_before_reducer_mg_kg": _r(bal.crvi_cement0, 2),
            "cement_crvi_after_current_reducer_mg_kg": _r(bal.crvi_cement, 2),
        },
        "kiln_sources": [{"source": r["name"], "group": r["group"], "amount_kg_per_t_clk": _r(r["amount"], 1),
                          "total_cr_mg_kg": _r(r["cr"], 1), "contribution_mg_kg_clk": _r(r["contribution"], 2),
                          "share_pct": _r(r["share"], 1)} for _, r in bal.kiln.sort_values("contribution", ascending=False).iterrows()],
        "cement_crvi_pareto": [{"source": r["투입원"], "mg_kg": _r(r["기여(mg/kg)"], 2), "share_pct": _r(r["비율(%)"], 1)}
                               for _, r in bal.contrib.head(8).iterrows()],
        "reducer": {"type": REDUCERS[p.reducer]["label"], "purity_pct": p.purity, "field_excess_factor": p.excess,
                    "monthly_loss_pct": p.loss_month, "storage_months": p.months,
                    "dosing_point": "밀 출구 이후(저온)" if p.after_mill else f"밀 투입(약 {p.mill_temp:g} ℃)",
                    "retention_pct": _r(reducer_retention(p) * 100, 1), "current_dose_kg_t": p.dose,
                    "required_dose_kg_t": {f"사내 목표 {p.target:g}": _r(required_dose(bal.crvi_cement0, p.target, p), 3),
                                           f"국내 {LIMIT_KR:g}": _r(required_dose(bal.crvi_cement0, LIMIT_KR, p), 3),
                                           f"EU {LIMIT_EU:g}": _r(required_dose(bal.crvi_cement0, LIMIT_EU, p), 3)},
                    "price_won_per_kg": p.price},
        "standards": {"국내": LIMIT_KR_TEXT, "EU": LIMIT_EU_TEXT, "주의": "시험법이 달라 수치 직접 비교 불가",
                      "사내 경고": "18 mg/kg(사내 관리기준, 예시)"},
        "literature": "클링커 Cr의 약 8~20%가 6가로 전환(Costeri 2016; Lizarraga 2003, Hills & Johansen 2007 인용). "
                      "산소·알칼리가 주 영향 인자.",
        "assumption_note": "원료·연료 크롬 함량·전환율·과잉계수·열화율 기본값은 예시(추정) — 실측 보정 필요",
    }
    if tor is not None and len(tor):
        ctx["sensitivity_cement_crvi"] = [{"input": r["입력"], "low": _r(r["낮음"], 2), "high": _r(r["높음"], 2)}
                                          for _, r in tor.sort_values("영향폭", ascending=False).head(6).iterrows()]
    if cal is not None:
        ctx["calibration"] = {"n_pairs": cal.n, "median_conversion_pct": _r(cal.median, 2), "q1": _r(cal.q1, 2),
                              "q3": _r(cal.q3, 2), "regression": cal.coef, "r2": _r(cal.r2, 3)}
    if measured_recent:
        ctx["recent_measurements"] = measured_recent
    return ctx


def rawmix_context(res, targets, kp) -> dict:
    cl = res.clinker
    return {
        "task": "원료 배합 설계 결과 검토(클링커 계수 예측)",
        "mode": res.mode, "feasible": res.feasible, "messages": res.messages, "active_bounds": res.active_bounds,
        "targets": {k: {"value": targets.values[k], "enabled": bool(targets.enabled.get(k))} for k in targets.values},
        "target_basis": "클링커 기준(석탄회 흡수 반영)" if targets.basis == "clinker" else "생료 기준",
        "mix": [{"material": r["원료"], "category": r["구분"], "dry_pct": _r(r["건조 배합비(%)"], 2),
                 "wet_pct": _r(r["습윤 배합비(%)"], 2)} for _, r in res.table().iterrows()],
        "raw_meal": {"LSF": _r(cl["raw_lsf"], 2), "SM": _r(cl["raw_sm"], 3), "IM": _r(cl["raw_im"], 3),
                     "LOI_pct": _r(cl["raw"]["LOI"], 2)},
        "clinker_pred": {"LSF": _r(cl["LSF"], 2), "SM": _r(cl["SM"], 3), "IM": _r(cl["IM"], 3), "C3S_bogue": _r(cl["C3S"], 1),
                         "C2S_bogue": _r(cl["C2S"], 1), "C3A_bogue": _r(cl["C3A"], 1), "C4AF_bogue": _r(cl["C4AF"], 1),
                         "liquid_1450C": _r(cl["liquid"], 1), "Na2Oeq": _r(cl["na2oeq"], 2), "fCaO_pred": _r(cl["fcao"], 2),
                         "xrd_pred": {k: _r(v, 1) for k, v in cl["xrd"].items()}},
        "kiln_params": {"coal_kg_per_t": kp.coal_kg_per_t, "ash_pct": kp.coal_ash, "ash_absorption_pct": kp.ash_absorption},
        "cost_won_per_t_clinker": _r(res.cost_per_t_clk, 0),
    }
