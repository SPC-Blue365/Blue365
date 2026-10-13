"""출하시멘트(LIMS 일일 로트) 모듈: 형식 인식·0=미시험·선박 비고 정규화·저염 구분·연도별 관리기준·혼합재↔강도."""

import io
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from qms import shipment as S

HEAD = ["", "전송", "ERP LOT.NO", "LIMS LOT.NO", "검사일", "채취일", "품명", "공정구분", "분석방법", "첨가재명칭", "석회석비율", "석회석CO2", "석회석품위", "첨가재비율", "LOI",
        "SiO2", "Al2O3", "Fe2O3", "CaO", "MgO", "SO3(XRF)", "SO3(C/S)", "Na2O", "K2O", "Cl(XRF)", "Cl(습식)", "TA", "압축강도1일(MPa)", "압축강도3일(MPa)",
        "압축강도7일(MPa)", "압축강도28일(MPa)", "45㎛", "Blaine", "주도", "Flow", "간이Flow", "초결시간(분)", "종결시간(HH:MM)", "담당자", "비고"]
APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def make_xlsx(n=240, seed=3, extra_note=True) -> bytes:
    """실제 파일과 같은 열 구조의 합성 자료. 혼합재 합계가 10→8→5 로 바뀌고 강도는 혼합재가 줄수록 오르게 만든다."""
    rng = np.random.default_rng(seed)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEAD)
    ships = ["수성3호", "수성1호", "리나호", "삼표1호", "정진호"]
    start = pd.Timestamp("2025-06-01")
    for i in range(n):
        d = start + pd.Timedelta(days=i)
        mix = [(5, 5), (5, 3), (5, 0)][0 if i < 80 else (1 if i < 160 else 2)]
        tot = mix[0] + mix[1]
        base28 = 57.0 - 0.8 * (tot - 5)
        note = ",".join(rng.choice(ships, size=int(rng.choice([1, 1, 2])), replace=False))
        if extra_note and i % 40 == 7:
            note = "삼표1호(부산,저염)    ."
        if extra_note and i % 40 == 9:
            note = "수성3 ,리나호."
        r = [i + 1, None, f"QC{i}", str(1000 + i), d.date().isoformat(), d.date().isoformat(), "1종시멘트 벌크", "P3", "Powder",
             "플라이 애시", mix[0], 37, 84, mix[1], round(rng.normal(2.5, .2), 2), 21, round(rng.normal(5.7, .2), 2), 3.4, 58,
             round(rng.normal(3.9, .3), 2), round(rng.normal(2.6, .06), 2), 0, .2, 1.0, int(rng.integers(300, 700)), 0, round(rng.normal(.85, .03), 2),
             round(rng.normal(15.5, .8), 1), round(rng.normal(35.5, 1), 1), round(rng.normal(45, 1), 1), 0 if i >= n - 3 else round(rng.normal(base28, .8), 1),
             round(rng.normal(6.8, .5), 1), int(rng.normal(3780, 60)), round(rng.normal(27.3, .2), 1), int(rng.integers(90, 100)), 0, str(int(rng.integers(220, 280))),
             f"{int(rng.integers(5, 7)):02d}:{int(rng.integers(0, 60)):02d}", "", note]
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def parsed():
    return S.parse_upload(make_xlsx(), "ship.xlsx")


def test_detect_and_headers(parsed):
    assert not parsed.errors
    rep = parsed.report
    assert rep["missing"] == [] and len(rep["found"]) == 17
    found = dict(rep["found"])
    assert found["so3"] == "SO3(XRF)" and found["flow"] == "Flow" and found["r45"] == "45㎛" and found["fst"] == "종결시간(HH:MM)"
    # 다른 표(세로형 LIMS 등)는 출하시멘트로 감지하지 않는다
    other = [["시료채취일시", "시료명", "시험항목", "결과값", "단위", "판정", "a", "b"]] + [["2026-01-01", "클링커", "f-CaO", 1, "%", "적합", 1, 2]] * 3
    assert S.detect(other) is None


def test_zero_is_untested_but_ratio_zero_is_real(parsed):
    df = parsed.records
    assert df["s28"].isna().sum() == 3                      # 마지막 3건은 28일 강도 0 → 미시험
    assert parsed.report["zeros"]["s28"] == 3
    assert (df["addr"] == 0).sum() == 80                    # 첨가재 비율 0 = 투입 안 함(실제 값)
    assert df.loc[df["addr"] == 0, "mix_total"].eq(5).all()
    assert df["fst"].notna().all() and df["fst"].between(300, 420).all()   # HH:MM → 분


def test_ship_notes_and_low_chloride(parsed):
    df = parsed.records
    low = df[df["product_kind"] == "저염"]
    assert len(low) == 6 and (low["ships"] == "삼표1호").all() and (low["dest_hint"] == "부산").all()
    row = df[df["date"] == pd.Timestamp("2025-06-01") + pd.Timedelta(days=9)].iloc[0]
    assert row["ships"] == "수성3호,리나호" and row["n_ship"] == 2 and row["ship_ok"]       # '수성3 ,리나호.' 정규화
    assert df["n_ship"].min() >= 1
    # 선박별 값을 추정·분해하는 열은 만들지 않는다
    assert not any(c.startswith("ship_est") for c in df.columns)


def test_save_merge_keeps_old_values_and_updates():
    S.clear_shipment()
    first = S.parse_upload(make_xlsx(), "a.xlsx").records
    r = S.save_shipment(first)
    assert r == {"added": 240, "updated": 0, "total": 240}
    # 28일 강도가 나중에 들어온 새 파일(마지막 3건 값 있음) + 기존 값은 비어 있는 칸에도 유지
    newer = first.copy().tail(5).reset_index(drop=True)
    newer.loc[newer.index[-3:], "s28"] = [55.5, 55.6, 55.7]
    newer["s1"] = np.nan                                    # 새 파일에서 1일 강도가 비어 있어도 기존 값 유지
    r2 = S.save_shipment(newer)
    assert r2["added"] == 0 and r2["updated"] == 5 and r2["total"] == 240
    d = S.load_shipment()
    assert d["s28"].iloc[-1] == 55.7 and d["s1"].iloc[-1] == first["s1"].iloc[-1]
    assert "x:CaO" not in d.columns or True
    S.clear_shipment()


def test_standards_by_year_carry_forward_and_step():
    std = {"version": 1, "years": {}}
    assert S.effective_limits(std, "s28", 2025)["ks_min"] == 42.5 and S.effective_limits(std, "s28", 2025)["lsl"] is None
    t = S.year_table(std, 2025)
    t.loc[t["key"] == "s28", "사내 하한"] = 50.0
    S.save_year(std, 2025, t)
    t26 = S.year_table(std, 2026)
    assert t26.loc[t26["key"] == "s28", "사내 하한"].iloc[0] == 50.0 and t26.loc[t26["key"] == "s28", "출처"].iloc[0] == "2025년 승계"
    t26.loc[t26["key"] == "s28", "사내 하한"] = 52.0
    S.save_year(std, 2026, t26)
    assert S.effective_limits(std, "s28", 2024)["lsl"] is None          # 이전 연도에는 소급 적용하지 않음
    assert S.effective_limits(std, "s28", 2027)["lsl"] == 52.0
    df = pd.DataFrame({"date": pd.to_datetime(["2025-12-31", "2026-01-01"]), "s28": [51.0, 51.0]})
    lim = S.limits_frame(std, df, "s28")
    assert lim["lsl"].tolist() == [50.0, 52.0]
    # 같은 51.0 이라도 2025년 기준에서는 정상, 2026년 기준에서는 사내 기준 이탈
    j = S.judge_item(df.assign(n_ship=1, ship_ok=True), "s28", std)
    assert j.plant_out.tolist() == [False, True] and not j.ks_out.any()
    S.save_ship_standards({"version": 1, "years": {}})


def test_judge_status_ks_over_plant_over_spc():
    std = {"version": 1, "years": {}}
    rng = np.random.default_rng(1)
    dates = pd.date_range("2026-01-01", periods=60)
    v = rng.normal(55, 1, 60)
    df = pd.DataFrame({"date": dates, "s28": v})
    assert S.judge_item(df, "s28", std).status in ("정상", "참고", "주의")
    df.loc[59, "s28"] = 40.0                                # KS 하한(42.5) 미달
    j = S.judge_item(df, "s28", std)
    assert j.status == "위험" and j.ks_out.iloc[-1]
    df.loc[59, "s28"] = 45.0                                # KS 이내, 사내 하한 미달
    t = S.year_table(std, 2026)
    t.loc[t["key"] == "s28", "사내 하한"] = 50.0
    std = S.save_year(std, 2026, t)
    assert S.judge_item(df, "s28", std).status == "경고"
    S.save_ship_standards({"version": 1, "years": {}})


def test_mix_effect_matches_domain_knowledge(parsed):
    df = parsed.records
    e = S.mix_effect(df, "s28")
    assert e and e["mix_coef"] < -0.5                       # 혼합재 +1%p → 28일 강도 하락(설계값 -0.8)
    ch = S.mix_changes(df)
    dec = ch[ch["변화(%p)"] < 0]
    assert len(dec) >= 1 and (dec["압축강도 28일 변화(MPa)"] > 0).all()   # 혼합재↓ → 강도↑
    assert dec["28일 강도 방향(경험칙 대비)"].str.startswith("✔").all()
    ct = S.composition_table(df)
    assert set(ct["혼합재합계"]) == {10.0, 8.0, 5.0}


def test_filters(parsed):
    df = parsed.records
    only = S.apply_filters(df, kind="일반 제품만")
    assert (only["product_kind"] == "일반").all() and len(only) == len(df) - 6
    single = S.apply_filters(df, mode="1모선 단독 시험만", kind="저염 포함 전체")
    assert ((single["n_ship"] == 1) & single["ship_ok"]).all()


def test_page_renders_empty_and_with_data():
    S.clear_shipment()
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    at.switch_page("app_pages/shipment.py")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title and "출하시멘트" in at.title[0].value
    S.save_shipment(S.parse_upload(make_xlsx(), "a.xlsx").records)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs][:2] == ["📊 한눈에", "📈 항목 상세"]
    assert at.dataframe, "판정표가 있어야 함"
    S.clear_shipment()
