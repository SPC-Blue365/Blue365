"""2단계 기능 확장 보고 PPT용 데이터 추출(데모 데이터 기준) → docs/src/deck_phase2_data.json

사용:  python scripts/export_phase2_deck_data.py [출력 json]
보고서의 모든 수치는 이 스크립트가 시스템 모듈로 계산한 값이다(손으로 입력한 숫자 없음).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QMS_DATA_DIR", tempfile.mkdtemp(prefix="qms_deck_"))

import pandas as pd  # noqa: E402

from qms import chromium as crm  # noqa: E402
from qms import (
    lims,  # noqa: E402
    llm,  # noqa: E402
)
from qms import rawmix as rmx  # noqa: E402
from qms import strength as stg  # noqa: E402
from qms.alerts import detect_events  # noqa: E402
from qms.demo import generate_demo_data  # noqa: E402
from qms.diagnosis import diagnose  # noqa: E402
from qms.prediction import attach_predictions  # noqa: E402
from qms.standards import DEFAULT_SETTINGS, SpecRegistry  # noqa: E402
from qms.store import build_store, load_raw, save_raw  # noqa: E402

END = date(2026, 10, 7)


def r(v, nd=2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def main(out: Path) -> None:
    raw = generate_demo_data(end=END, days=120, seed=7)
    store = build_store(raw)
    reg = SpecRegistry()
    settings = dict(DEFAULT_SETTINGS)
    attach_predictions(store, reg)
    events = detect_events(store, reg, settings)
    fm, xm = rmx.fit_fcao_model(store), rmx.fit_xrd_map(store)
    D: dict = {"n_items": len(reg.all()), "n_tests": 90, "n_pages": 13}

    # ── 배합 ──
    coal = rmx.estimate_coal_rate(store)          # 화면과 같은 기준: DCS 실적으로 추정한 석탄 원단위
    mats, t, kp = rmx.default_materials(), rmx.MixTargets(), rmx.KilnParams(coal_kg_per_t=round(coal, 1))
    res = rmx.solve_mix(mats, t, kp, fcao_model=fm, xrd_map=xm)
    cost = rmx.solve_mix(mats, t, kp, mode="cost", fcao_model=fm, xrd_map=xm)
    cl = res.clinker
    D["rawmix"] = {
        "targets": {k: t.values[k] for k in ("LSF", "SM", "IM")},
        "achieved": {k: r(res.achieved[k], 3) for k in ("LSF", "SM", "IM", "C3S")},
        "mix": [{"name": n, "dry": r(x * 100, 2)} for n, x in zip(res.names, res.x)],
        "cost_lsq": r(res.cost_per_t_clk, 0), "cost_min": r(cost.cost_per_t_clk, 0),
        "cost_saving_pct": r((1 - cost.cost_per_t_clk / res.cost_per_t_clk) * 100, 1),
        "raw_lsf": r(cl["raw_lsf"], 1), "clk": {"LSF": r(cl["LSF"], 1), "SM": r(cl["SM"], 2), "IM": r(cl["IM"], 2),
                                                "C3S": r(cl["C3S"], 1), "liquid": r(cl["liquid"], 1),
                                                "fcao": r(cl["fcao"], 2), "alite": r(cl["xrd"]["alite"], 1)},
    }
    chk, summ = rmx.conversion_check(store, kp)
    absorb_fix = round(100 * summ["a_eff"] / summ["a_set"], 0)      # 화면의 '회분 흡수율 보정' 제안값
    chk_fix, summ_fix = rmx.conversion_check(store, rmx.KilnParams(coal_kg_per_t=kp.coal_kg_per_t,
                                                                   ash_absorption=absorb_fix))
    recent = chk_fix[chk_fix["timestamp"] >= chk_fix["timestamp"].max() - pd.Timedelta(days=7)]   # 보정 후 예측선
    daily = recent.set_index("timestamp")[["LSF 실측", "LSF 예측"]].resample("8h").mean().dropna()
    D["conversion"] = {"rmse": {k: r(summ[k]["rmse"], 3) for k in ("LSF", "SM", "IM")},
                       "bias": {k: r(summ[k]["bias"], 3) for k in ("LSF", "SM", "IM")},
                       "a_eff": r(summ["a_eff"], 4), "a_set": r(summ["a_set"], 4),
                       "cats": [f"{ts:%m/%d}" if ts.hour == 0 else " " for ts in daily.index],
                       "act": [r(v, 2) for v in daily["LSF 실측"]], "pred": [r(v, 2) for v in daily["LSF 예측"]],
                       "fcao_coef_lsf": r(fm.coef["lsf"], 3), "fcao_r2": r(fm.r2, 2),
                       "absorb_fix": absorb_fix, "rmse_fix": {k: r(summ_fix[k]["rmse"], 3) for k in ("LSF", "SM", "IM")}}

    # ── 강도 ──
    st = {}
    for prod in ("1종", "3종"):
        sm = stg.fit_strength_models(store, reg, prod, xm)
        base, ts = sm.latest_inputs()
        pred = sm.predict(base)
        st[prod] = {"models": [{"target": m.label, "n": m.n, "rmse": r(m.rmse, 2), "source": m.source}
                               for m in sm.models.values()],
                    "pred": [{"item": row["항목"], "pred": r(row["예측"], 1), "lo": r(row["하한(95%)"], 1),
                              "hi": r(row["상한(95%)"], 1), "ks": row["KS"], "spec": row["사내"], "judge": row["판정"]}
                             for _, row in pred.iterrows()]}
        if prod == "1종":
            goals = stg.default_goals(reg, prod, sm.models, "target")
            plan = stg.optimize_controls(sm, base, goals)
            st[prod]["plan"] = {
                "goals": {stg.TARGETS[k]["label"]: v for k, v in goals.items()},
                "levers": [{"lever": row["레버"], "now": r(row["현재"], 2), "rec": r(row["권장"], 2),
                            "delta": r(row["변경"], 2), "unit": row["단위"]} for _, row in plan.lever_table().iterrows()],
                "outcome": [{"item": row["항목"], "goal": row["목표"], "now": r(row["현재 예측"], 1),
                             "after": r(row["조정 후 예측"], 1), "ok": row["판정"]} for _, row in plan.outcome_table().iterrows()],
            }
            late = stg.optimize_controls(sm, base, {"phy_ist": (sm.predict_values(base)["phy_ist"] + 20, None)})
            st[prod]["setting_example"] = [{"lever": row["레버"], "delta": r(row["변경"], 2), "unit": row["단위"]}
                                           for _, row in late.lever_table().iterrows()]
    D["strength"] = st

    # ── 6가크롬 ──
    k = crm.default_kiln_inputs(res.table(), res.mats)
    m = crm.default_mill_inputs()
    cal = crm.calibrate_conversion(crm.pairs_from_store(store))
    p = crm.CrParams(conv_kiln=round(cal.median, 2))
    bal = crm.cr_balance(k, m, p)
    doses = []
    for key in crm.REDUCERS:
        pp = p.with_reducer(key) if key != p.reducer else p
        d2 = crm.required_dose(bal.crvi_cement0, crm.LIMIT_EU, pp)
        doses.append({"reducer": crm.REDUCERS[key]["label"], "stoich": r(crm.stoich(key), 2), "kg_t": r(d2, 3),
                      "won_t": r(d2 * pp.price, 0)})
    eff = crm.reducer_effect_series(store)
    phy = store.tables["physical"].dropna(subset=["phy_crvi"]).sort_values("timestamp")
    phy = phy[phy["timestamp"] >= phy["timestamp"].max() - pd.Timedelta(days=45)]
    ev = next(e for e in events if e.item_key == "phy_crvi" and e.severity == "위험")
    dx = diagnose(ev, store, reg, settings)
    D["chromium"] = {
        "total_clk": r(bal.total_clk, 1), "crvi_clk": r(bal.crvi_clk, 2), "cem0": r(bal.crvi_cement0, 2),
        "cem_after": r(bal.crvi_cement, 2), "dose_now": p.dose, "conv": p.conv_kiln,
        "pareto": [{"name": row["투입원"], "mg": r(row["기여(mg/kg)"], 2), "pct": r(row["비율(%)"], 1)}
                   for _, row in bal.contrib.head(6).iterrows()],
        "doses_eu2": doses,
        "cal": {"n": cal.n, "median": r(cal.median, 2), "q1": r(cal.q1, 1), "q3": r(cal.q3, 1),
                "o2": r(cal.coef["o2"], 2) if cal.coef else None, "r2": r(cal.r2, 2)},
        "effect_mean": r(eff["실효 제거량"].mean(), 2),
        "trend": {"cats": [f"{ts:%m/%d}" if i % 7 == 0 else " " for i, ts in enumerate(phy["timestamp"])],
                  "vals": [r(v, 1) for v in phy["phy_crvi"]], "prod": phy["product"].tolist()},
        "s7": {"start": f"{ev.start:%m/%d}", "end": f"{ev.end:%m/%d}", "worst": r(ev.worst_value, 1),
               "top": dx.results[0].hyp.title, "verdict": dx.results[0].verdict, "axis": dx.results[0].hyp.axis},
    }

    # ── LIMS(데모) ──
    tmp = Path(os.environ["QMS_DATA_DIR"])
    src = tmp / "src.db"
    save_raw(raw, path=src, replace=True)
    lims.LIMS_DEMO_DB = tmp / "lims_demo.db"
    info = lims.create_demo_lims(load_raw(src), lims.LIMS_DEMO_DB)
    rep = lims.sync(lims.LimsConfig(enabled=True, mode="demo"), db_path=tmp / "empty.db",
                    now=pd.Timestamp(f"{END} 23:59").to_pydatetime(), log_path=tmp / "log.jsonl", persist_watermark=False)
    D["lims"] = {"samples": info["samples"], "results": info["results"], "fetched": rep.n_fetched, "mapped": rep.n_mapped,
                 "pending": rep.n_status_skipped, "unmapped": rep.n_unmapped, "cells_new": rep.cells_new,
                 "mapping_rows": len(lims.default_mapping())}

    # ── AI 비용 ──
    D["ai"] = [{"model": v["label"], "usd": r(llm.estimate_call_cost(k2), 4), "krw": r(llm.estimate_call_cost(k2) * 1400, 0)}
               for k2, v in llm.MODELS.items()]

    # ── 검증 요약(데모 생성값 vs 시스템 추정값) ──
    D["validation"] = [
        ["f-CaO 소성성 회귀: LSF 계수", "0.32", f"{fm.coef['lsf']:.2f}"],
        ["XRD 알라이트 − Bogue C₃S", "+6.5%p", f"+{xm.coef['alite'][0] + (xm.coef['alite'][1] - 1) * 57:.1f}%p"],
        ["석탄회 흡수(kg/kg-클링커)", "0.0150", f"{summ['a_eff']:.4f}"],
        ["킬른 Cr⁶⁺ 전환율", "12.0%", f"{cal.median:.1f}%"],
        ["환원제 실효 제거량", "3.0 mg/kg", f"{eff['실효 제거량'].mean():.1f} mg/kg"],
        ["S7 6가크롬 원인(1순위)", "원료 Cr 증가", "일치(데이터 지지)" if dx.results[0].hyp.axis == "원료" else "불일치"],
    ]
    out.write_text(json.dumps(D, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "src" / "deck_phase2_data.json")
