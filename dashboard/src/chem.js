/* Blue365 QMS 대시보드 — 시멘트 화학·배합·SPC·6가크롬 계산 (qms/chemistry.py, rawmix.py, chromium.py 이식)
   근거: Lea & Parker(LSF·액상량), ASTM C150 Bogue, 물질수지. 설치형 앱(Python)과 같은 식을 사용한다. */
(function (global) {
  "use strict";
  const num = (v) => (v === null || v === undefined || v === "" || isNaN(+v)) ? NaN : +v;
  const div = (a, b) => (b === 0 || !isFinite(b)) ? NaN : a / b;
  const clip = (v, lo, hi) => Math.min(hi === null ? Infinity : hi, Math.max(lo === null ? -Infinity : lo, v));

  // ── 모듈러스 ──
  function lsf(cao, sio2, al2o3, fe2o3, so3 = 0, gypsum = false) {
    const c = gypsum ? cao - 0.7 * so3 : cao;
    return 100 * div(c, 2.8 * sio2 + 1.18 * al2o3 + 0.65 * fe2o3);
  }
  const silicaModulus = (sio2, al2o3, fe2o3) => div(sio2, al2o3 + fe2o3);
  const ironModulus = (al2o3, fe2o3) => div(al2o3, fe2o3);
  const na2oEq = (na2o, k2o) => na2o + 0.658 * k2o;
  const burnabilityIndex = (c3s, c3a, c4af) => div(c3s, c3a + c4af);

  // ── Bogue(ASTM C150) ──
  function bogue(cao, sio2, al2o3, fe2o3, so3 = 0, fcao = 0) {
    const caoEff = cao - fcao;
    const af = div(al2o3, fe2o3);
    const normal = !(af < 0.64);           // A/F ≥ 0.64 (NaN도 normal로 처리)
    let c3s = normal
      ? 4.071 * caoEff - 7.600 * sio2 - 6.718 * al2o3 - 1.430 * fe2o3 - 2.852 * so3
      : 4.071 * caoEff - 7.600 * sio2 - 4.479 * al2o3 - 2.859 * fe2o3 - 2.852 * so3;
    c3s = Math.max(c3s, 0);
    const c2s = Math.max(2.867 * sio2 - 0.7544 * c3s, 0);
    const c3a = normal ? Math.max(2.650 * al2o3 - 1.692 * fe2o3, 0) : 0;
    const c4af = normal ? 3.043 * fe2o3 : 2.100 * al2o3 + 1.702 * fe2o3;
    return { C3S: c3s, C2S: c2s, C3A: c3a, C4AF: c4af };
  }

  // ── 1450℃ 액상량(Lea & Parker) ──
  function liquidPhase1450(al2o3, fe2o3, mgo = 0, k2o = 0, na2o = 0) {
    const af = div(al2o3, fe2o3);
    const base = !(af < 1.38) ? 3.00 * al2o3 + 2.25 * fe2o3 : 8.20 * al2o3 - 5.22 * fe2o3;
    return base + Math.min(mgo, 2.0) + k2o + na2o;
  }

  // 산화물 → 전체 지표(화학 계산기)
  function moduliFromOxides(ox) {
    const g = (k) => num(ox[k]) || 0;
    const [cao, sio2, al2o3, fe2o3, so3, mgo, k2o, na2o, fcao] =
      ["CaO", "SiO2", "Al2O3", "Fe2O3", "SO3", "MgO", "K2O", "Na2O", "fcao"].map(g);
    const b = bogue(cao, sio2, al2o3, fe2o3, so3, fcao);
    return {
      LSF: lsf(cao, sio2, al2o3, fe2o3), SM: silicaModulus(sio2, al2o3, fe2o3),
      IM: ironModulus(al2o3, fe2o3), ...b,
      liquid: liquidPhase1450(al2o3, fe2o3, mgo, k2o, na2o), na2oeq: na2oEq(na2o, k2o),
      BI: burnabilityIndex(b.C3S, b.C3A, b.C4AF),
    };
  }

  // ── 배합 → 생료 → 클링커 (수동 forward 계산) ──
  const OXIDES = ["SiO2", "Al2O3", "Fe2O3", "CaO", "MgO", "SO3", "K2O", "Na2O"];
  const ASH_DEFAULT = { SiO2: 55.0, Al2O3: 25.0, Fe2O3: 7.0, CaO: 5.0, MgO: 1.5, K2O: 1.0, Na2O: 0.4 };

  function kilnA(kp) {
    return (kp.coal_kg_per_t / 1000) * (kp.coal_ash / 100) * (kp.ash_absorption / 100);
  }

  // mats: [{name, category, use, SiO2.., LOI, H2O, Cr, ...}], xPct: 사용 원료의 건조 배합비(%)
  function predictClinker(mats, xPct, kp, fcao) {
    const used = mats.filter((m) => m.use);
    const x = xPct.map((v) => (num(v) || 0) / 100);
    const s = x.reduce((a, b) => a + b, 0) || 1;
    const xn = x.map((v) => v / s);                       // 합계 1로 정규화
    const raw = {};
    OXIDES.forEach((o) => { raw[o] = used.reduce((acc, m, i) => acc + xn[i] * (num(m[o]) || 0), 0); });
    raw.LOI = used.reduce((acc, m, i) => acc + xn[i] * (num(m.LOI) || 0), 0);
    const D = 1 - raw.LOI / 100;
    const a = kilnA(kp), ash = kp.ash || ASH_DEFAULT;
    const clk = {};
    ["SiO2", "Al2O3", "Fe2O3", "CaO", "MgO"].forEach((o) => { clk[o] = (1 - a) * raw[o] / D + a * (ash[o] || 0); });
    clk.K2O = (kp.k2o_retention / 100) * ((1 - a) * raw.K2O / D + a * (ash.K2O || 0));
    clk.Na2O = (kp.na2o_retention / 100) * ((1 - a) * raw.Na2O / D + a * (ash.Na2O || 0));
    clk.SO3 = (kp.so3_retention / 100) * ((1 - a) * raw.SO3 / D + kp.coal_kg_per_t * kp.coal_s * 0.0025);
    const L = lsf(clk.CaO, clk.SiO2, clk.Al2O3, clk.Fe2O3);
    const SM = silicaModulus(clk.SiO2, clk.Al2O3, clk.Fe2O3);
    const IM = ironModulus(clk.Al2O3, clk.Fe2O3);
    const fc = (fcao === undefined || fcao === null || isNaN(fcao)) ? (kp.fcao || 1.0) : fcao;
    const b = bogue(clk.CaO, clk.SiO2, clk.Al2O3, clk.Fe2O3, clk.SO3, fc);
    const crClk = used.reduce((acc, m, i) => acc + xn[i] * (num(m.Cr) || 0), 0) * (1 - a) / D; // 원료 총 Cr → 클링커(근사)
    return {
      raw, clinker: clk, x: xn, names: used.map((m) => m.name), a, D,
      rawLsf: lsf(raw.CaO, raw.SiO2, raw.Al2O3, raw.Fe2O3),
      rawSm: silicaModulus(raw.SiO2, raw.Al2O3, raw.Fe2O3), rawIm: ironModulus(raw.Al2O3, raw.Fe2O3),
      LSF: L, SM, IM, fcao: fc, ...b,
      liquid: liquidPhase1450(clk.Al2O3, clk.Fe2O3, clk.MgO, clk.K2O, clk.Na2O),
      na2oeq: na2oEq(clk.Na2O, clk.K2O), BI: burnabilityIndex(b.C3S, b.C3A, b.C4AF),
      kilnFactor: (1 - a) / D, crClinker: crClk,
    };
  }

  // ── SPC ──
  function mean(a) { const v = a.filter((x) => isFinite(x)); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : NaN; }
  function std(a) {  // 표본 표준편차(ddof=1)
    const v = a.filter((x) => isFinite(x)); if (v.length < 2) return NaN;
    const m = mean(v); return Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / (v.length - 1));
  }
  function spcStats(values, lsl, usl) {
    const v = values.filter((x) => isFinite(x));
    const m = mean(v), sd = std(v);
    const out = { n: v.length, mean: m, std: sd, ucl: m + 3 * sd, lcl: m - 3 * sd, cp: NaN, cpk: NaN };
    if (isFinite(sd) && sd > 0 && (lsl !== null || usl !== null)) {
      if (lsl !== null && usl !== null) out.cp = (usl - lsl) / (6 * sd);
      const cpu = usl !== null ? (usl - m) / (3 * sd) : Infinity;
      const cpl = lsl !== null ? (m - lsl) / (3 * sd) : Infinity;
      out.cpk = Math.min(cpu, cpl);
    }
    return out;
  }

  // ── 6가크롬 ──
  const M_CR = 51.996;
  const REDUCERS = {
    "FeSO4·7H2O": { label: "황산제1철 7수화물(FeSO₄·7H₂O)", molar_mass: 278.01, mol_per_cr: 3.0, purity: 90.0, excess: 10.0, price: 200.0 },
    "FeSO4·H2O": { label: "황산제1철 1수화물(FeSO₄·H₂O)", molar_mass: 169.92, mol_per_cr: 3.0, purity: 88.0, excess: 10.0, price: 300.0 },
    "SnSO4": { label: "황산제1주석(SnSO₄)", molar_mass: 214.77, mol_per_cr: 1.5, purity: 97.0, excess: 3.0, price: 30000.0 },
  };
  const LIMIT_KR = 20.0, LIMIT_EU = 2.0;
  const stoich = (key) => REDUCERS[key].mol_per_cr * REDUCERS[key].molar_mass / M_CR;   // g 환원제 / g Cr⁶⁺
  // retention: 저장(월 열화)·고온 투입에 따른 실효계수(1 = 신품·저온, FeSO₄ 밀 투입은 통상 0.6 전후)
  function capacityPerKg(key, purity, excess, retention = 1.0) {   // 1 kg/t 투입 시 제거 Cr⁶⁺(mg/kg)
    return 1000 * (purity / 100) * retention / (stoich(key) * Math.max(excess, 1e-9));
  }
  function requiredDose(crvi0, target, key, purity, excess, retention = 1.0) {
    const cap = capacityPerKg(key, purity, excess, retention);
    return cap > 0 ? Math.max(crvi0 - target, 0) / cap : Infinity;
  }
  const afterReducer = (crvi0, dose, key, purity, excess, retention = 1.0) =>
    Math.max(crvi0 - dose * capacityPerKg(key, purity, excess, retention), 0);

  // inputs: [{name, amount(kg/t-clk), cr(mg/kg), retention(%)}] → 클링커 총 Cr(mg/kg)
  function clinkerTotalCr(inputs) {
    return inputs.reduce((acc, r) => acc + (num(r.amount) || 0) * (num(r.cr) || 0) * ((num(r.retention) ?? 100) / 100) / 1000, 0);
  }

  global.CHEM = {
    num, div, clip, OXIDES, ASH_DEFAULT,
    lsf, silicaModulus, ironModulus, na2oEq, burnabilityIndex, bogue, liquidPhase1450, moduliFromOxides,
    kilnA, predictClinker, mean, std, spcStats,
    REDUCERS, LIMIT_KR, LIMIT_EU, stoich, capacityPerKg, requiredDose, afterReducer, clinkerTotalCr,
  };
})(this);
