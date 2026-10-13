// 출하시멘트 LIMS 표 분석 모듈(dashboard/src/ship.js) 시험 — 사용: node tests/js/ship_test.js
// 실제 파일(회사 자료)은 저장소에 넣지 않으므로, 실제 구조(머리글·0=미시험·HH:MM·비고 잡음)를 흉내 낸 합성 자료로 확인한다.
const assert = require("assert");
const S = require("../../dashboard/src/ship.js");

const H = ["", "전송", "ERP LOT.NO", "LIMS LOT.NO", "검사일", "채취일", "품명", "공정구분", "분석방법", "첨가재명칭", "석회석비율", "석회석CO2", "석회석품위", "첨가재비율", "LOI", "SiO2", "Al2O3", "Fe2O3", "CaO", "MgO", "SO3(XRF)", "SO3(C/S)", "Na2O", "K2O", "Cl(XRF)", "Cl(습식)", "TA",
  "압축강도1일(MPa)", "압축강도3일(MPa)", "압축강도7일(MPa)", "압축강도28일(MPa)", "45㎛", "Blaine", "주도", "Flow", "간이Flow", "초결시간(분)", "종결시간(HH:MM)", "담당자", "비고"];
const col = (h) => H.indexOf(h);
function row(i, date, over) {
  const r = new Array(H.length).fill(0);
  Object.assign(r, { 0: i, 2: "QC" + i, 3: String(1000 + i), 4: date, 5: date, 6: "1종시멘트 벌크", 9: "플라이 애시", 10: 4, 13: 3, 14: 2.5, 16: 5.5, 19: 3.6, 20: 2.6, 21: 0, 22: 0.2, 23: 1.0, 24: 450, 25: 0, 26: 0.85, 27: 15, 28: 36, 29: 45, 30: 55, 31: 7, 32: 3700, 33: 27.5, 34: 95, 35: 0, 36: "250", 37: "05:50", 38: "", 39: "" });
  Object.entries(over || {}).forEach(([k, v]) => { r[col(k)] = v; });
  return r;
}
// 비고 잡음: 마침표·공백, '수성3' 혼용, 괄호 안 쉼표, 쉼표 없이 붙은 이름, 오타
const NOTES = ["수성3호", "수성1호", "리나호", "삼표1호", "수성3호,리나호", "수성3호.", "수성3", "리나호         .", "삼표1호(부산,저염)", "수성1호수성3호", "수서3호,수성1호", "", "수성1호,삼표1호,리나호"];
const ship = [];
for (let k = 0; k < 6; k++) ["수성3호", "수성1호", "리나호", "삼표1호"].forEach((n) => ship.push(n));   // 어휘(5회 이상) 확보
const aoa = [["품질 일일 로트"], H];
let n = 0;
const push = (d, over) => { aoa.push(row(++n, d, over)); };
ship.forEach((nm, i) => push(`2026-01-${String(1 + (i % 28)).padStart(2, "0")}`.replace(/-(\d)$/, "-0$1"), { 비고: nm }));
NOTES.forEach((nt, i) => push(`2026-02-${String(1 + i).padStart(2, "0")}`, { 비고: nt, "압축강도28일(MPa)": i === 0 ? 0 : 55 + (i % 3), "종결시간(HH:MM)": i === 1 ? "00:00" : "06:10", "Cl(습식)": 0 }));
const R = S.parse(aoa);

// ① 형식 감지
assert(S.detect(aoa) && S.detect(aoa).headerRow === 1, "머리글 줄(2행)과 형식 감지");
assert.strictEqual(S.detect([["a", "b"], [1, 2], [3, 4]]), null, "다른 표는 감지하지 않음");
assert.strictEqual(S.detect([["시료채취일시", "시료명", "시험항목", "결과값", "단위", "판정", "x", "y"], ["2026-01-01", "클링커", "f-CaO", 0.9, "%", "적합", 1, 2], ["2026-01-01", "클링커", "LOI", 0.9, "%", "적합", 1, 2]]), null, "긴 형식 LIMS 표와 혼동 없음");
// ② 항목 인식 17개, 누락 없음
assert.strictEqual(R.report.missing.length, 0, "핵심 17항목 모두 인식: " + R.report.missing);
assert.strictEqual(R.report.found.length, 17);
assert.strictEqual(R.report.found.find((f) => f.key === "so3").header, "SO3(XRF)", "SO3 는 XRF 열(C/S 열 아님)");
assert.strictEqual(R.report.found.find((f) => f.key === "r45").header, "45㎛");
assert.strictEqual(R.report.found.find((f) => f.key === "flow").header, "Flow", "Flow 는 간이Flow 가 아님");
// ③ 0 = 미시험
const r0 = R.records.find((r) => r.date === "2026-02-01");
assert.strictEqual(r0.v.s28, null, "28일 강도 0 → 결측");
assert(R.report.zeros.s28 >= 1);
assert.strictEqual(R.records.find((r) => r.date === "2026-02-03").v.s28, 55 + (2 % 3));
// ④ HH:MM → 분, 00:00 → 결측
assert.strictEqual(r0.v.fst, 370);
assert.strictEqual(R.records.find((r) => r.date === "2026-02-02").v.fst, null);
assert.strictEqual(S.hhmmToMin("05:54"), 354);
// ⑤ 선박 이름 정규화
const by = (d) => R.records.find((r) => r.date === d);
assert.deepStrictEqual(by("2026-02-06").ships, ["수성3호"], "수성3호.");
assert.deepStrictEqual(by("2026-02-07").ships, ["수성3호"], "수성3 → 수성3호");
assert.deepStrictEqual(by("2026-02-08").ships, ["리나호"], "공백·마침표");
const lowcl = by("2026-02-09");
assert.deepStrictEqual(lowcl.ships, ["삼표1호"], "괄호 안 쉼표는 나누지 않음");
assert(lowcl.lowCl && lowcl.shipNotes.join().includes("부산"), "괄호 주석 분리·저염 표기");
assert.deepStrictEqual(by("2026-02-10").ships, ["수성1호", "수성3호"], "쉼표 없이 붙은 이름 분리");
assert.strictEqual(by("2026-02-10").shipsOk, true);
assert.strictEqual(by("2026-02-11").shipsOk, false, "오타(수서3호)는 불확실 표시");
assert.strictEqual(by("2026-02-05").nShip, 2, "수성3호,리나호 = 2모선");
assert.strictEqual(by("2026-02-13").nShip, 3);
assert.strictEqual(by("2026-02-12").nShip, 0, "비고 없음");
assert(R.report.shipUnsure.some((u) => u.raw.includes("수서3호")));
// ⑥ 통계·판정
const st = S.stats([10, 11, 9, 10, 10, 11, 9, 10], { lsl: 8 });
assert(Math.abs(st.mean - 10) < 1e-9 && st.cpk > 0 && st.ucl > st.mean);
const fl = S.flags([1, 1, 1, 1, 1, 1, 1, 1, 1, 9].map((v, i) => ({ v })), { mean: 2, sd: 1, ucl: 5, lcl: -1 }, {});
assert.strictEqual(fl[9].out3, true); assert(fl.slice(0, 8).every((f) => !f.run) && !fl[0].out3);
const fl2 = S.flags(new Array(10).fill(0).map(() => ({ v: 3 })), { mean: 2, sd: 1, ucl: 5, lcl: -1 }, {});
assert.strictEqual(fl2[8].run, true, "같은 쪽 9점 연속"); assert.strictEqual(fl2[7].run, false);
// ⑦ 선박별은 1모선·확실한 행만
const bs = S.byShip(R.records, "s3");
assert(bs.every((x) => ["수성3호", "수성1호", "리나호", "삼표1호"].includes(x.ship)));
// ⑧ 병합: 같은 LOT 는 새 파일 우선, 새 날짜는 추가
const a = S.parse(aoa).records, b2 = S.parse(aoa.slice(0, 5)).records.map((r) => Object.assign({}, r, { additive: "고로슬래그" }));
const mg = S.merge(a, b2); assert.strictEqual(mg.length, a.length); assert.strictEqual(mg[0].additive, "고로슬래그");
// ⑨ 못 찾은 열은 지정으로 보완
const aoa2 = aoa.map((r, i) => (i === 1 ? r.map((h) => (h === "주도" ? "표준 컨시스턴시 수량" : h)) : r));
const R2 = S.parse(aoa2); assert(R2.report.missing.includes("cons"));
const R3 = S.parse(aoa2, { overrides: { cons: col("주도") } }); assert.strictEqual(R3.report.missing.length, 0); assert.strictEqual(R3.records[0].v.cons, 27.5);
// ⑩ 날짜 없는 줄은 건너뜀·보고
const aoa3 = aoa.concat([row(99, "합계")]); assert.strictEqual(S.parse(aoa3).report.rowsSkipped, 1);
console.log("출하시멘트 모듈 시험 통과");
