// 엑셀 구조 자동 분석 엔진(dashboard/src/ingest.js) 시험 — 사용: node tests/js/ingest_test.js <spec.json>
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const I = require("../../dashboard/src/ingest.js");
const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const E = I.create(spec);
let n = 0;
const t = (name, fn) => { try { fn(); n++; console.log("OK  ", name); } catch (e) { console.log("FAIL", name, "\n   ", e.message); process.exitCode = 1; } };
const col = (res, table, key) => { const T = res.tables[table]; const i = T.columns.indexOf(key); return T.rows.map((r) => r[(T.byProduct ? 2 : 1) + i]); };

t("첨자·기호 정규화: SiO₂ == SiO2, Cr⁶⁺ == Cr6, 90μm == 90um", () => {
  assert.strictEqual(I.nkey("SiO₂"), I.nkey("SiO2")); assert.strictEqual(I.nkey("Cr⁶⁺"), "cr6"); assert.strictEqual(I.nkey("90μm 잔사"), "90um잔사");
});

t("값 해석: 부등호·ND·천단위·쉼표소수", () => {
  assert.deepStrictEqual(I.parseNum("<0.1"), { v: 0.1, censored: true });
  assert.strictEqual(I.parseNum("N.D.").v, null); assert.strictEqual(I.parseNum("1,234").v, 1234); assert.strictEqual(I.parseNum("12,5").v, 12.5);
  assert.strictEqual(I.parseNum("3450 cm2/g").v, 3450); assert.strictEqual(I.parseNum("abc").v, null);
});

t("날짜 해석: 일련번호·8자리·오전/오후·한글·시간열 결합", () => {
  assert.strictEqual(I.parseDate(46296.5), "2026-10-01T12:00");
  assert.strictEqual(I.parseDate(20261015), "2026-10-15T00:00");
  assert.strictEqual(I.parseDate("2026.10.15 오후 3:20"), "2026-10-15T15:20");
  assert.strictEqual(I.parseDate("2026년 10월 15일"), "2026-10-15T00:00");
  assert.strictEqual(I.parseDate("2026-10-15", "08:30"), "2026-10-15T08:30");
  assert.strictEqual(I.parseDate("26-10-15 8:05"), "2026-10-15T08:05");
  assert.strictEqual(I.parseDate("hello"), null);
});

t("① 가로형·키 머리글(템플릿)", () => {
  const a = E.analyze([["timestamp", "clk_fcao", "clk_lsf"], ["2026-10-01 08:00", 0.9, 95.1], ["2026-10-01 16:00", 1.1, 94.6]]);
  assert.strictEqual(a.layout, "wide"); assert.ok(a.status.auto, a.status.issues.join()); const r = E.extract(a);
  assert.deepStrictEqual(col(r, "clinker", "clk_fcao"), [0.9, 1.1]);
});

t("② 제목 2줄 + 두 줄 머리글(그룹) + 단위 줄 + 날짜/시간 분리 + 합계 줄", () => {
  const aoa = [
    ["○○시멘트 품질시험 성적서"], ["출력일: 2026-11-21"],
    ["", "", "클링커", "", "", "시멘트", ""],
    ["시료채취일", "시간", "CaO", "f-CaO", "LSF", "SO3", "분말도"],
    ["", "", "%", "%", "", "%", "cm2/g"],
    ["2026-11-01", "08:00", 65.2, 0.9, 95.1, 2.55, 3450],
    ["2026-11-01", "16:00", 64.8, 1.2, 94.5, 2.61, 3480],
    ["2026-11-02", "08:00", 65.0, 1.0, 95.3, 2.58, 3470],
    ["평균", "", 65.0, 1.03, 94.97, 2.58, 3466],
  ];
  const a = E.analyze(aoa); assert.strictEqual(a.headerRow, 3); assert.ok(a.unitRow); assert.strictEqual(a.layout, "wide");
  const keys = a.cols.filter((c) => c.key).map((c) => c.key);
  assert.deepStrictEqual(keys, ["clk_cao", "clk_fcao", "clk_lsf", "cem_so3", "cem_blaine"]);
  assert.ok(a.status.auto, a.status.issues.join());
  const r = E.extract(a);
  assert.strictEqual(r.summary.rowsRead, 3); assert.strictEqual(r.summary.rowsSkipped, 1);        // '평균' 줄 제외
  assert.deepStrictEqual(col(r, "clinker", "clk_cao"), [65.2, 64.8, 65.0]);
  assert.deepStrictEqual(col(r, "cement", "cem_so3"), [2.55, 2.61, 2.58]);
  assert.strictEqual(r.tables.clinker.rows[1][0], "2026-11-01T16:00");
});

t("③ 같은 이름 CaO 가 값 범위로 생료/클링커 구분", () => {
  const raw = E.analyze([["일시", "CaO", "SiO2"], ["2026-11-01 08:00", 43.9, 14.1], ["2026-11-01 09:00", 44.2, 14.0], ["2026-11-01 10:00", 44.0, 14.2]]);
  assert.deepStrictEqual(raw.cols.filter((c) => c.key).map((c) => c.key), ["rm_cao", "rm_sio2"]); assert.ok(raw.status.auto);
  const clk = E.analyze([["일시", "CaO", "SiO2"], ["2026-11-01 08:00", 65.1, 21.6], ["2026-11-01 09:00", 64.8, 21.7], ["2026-11-01 10:00", 65.3, 21.5]]);
  assert.deepStrictEqual(clk.cols.filter((c) => c.key).map((c) => c.key), ["clk_cao", "clk_sio2"]);
});

t("④ 긴 형식(시험 1건=1행): 지점별 같은 시험명이 서로 다른 공정으로", () => {
  const rows = [["시료채취일시", "시료명", "시험항목", "결과값", "단위", "판정"]];
  const days = ["2026-11-01 08:00", "2026-11-01 16:00", "2026-11-02 08:00"];
  days.forEach((d, i) => {
    rows.push([d, "생료", "CaO", 43.8 + i * 0.1, "%", "적합"]); rows.push([d, "클링커", "CaO", 65.0 + i * 0.1, "%", "적합"]);
    rows.push([d, "클링커", "f-CaO", 0.9 + i * 0.1, "%", "적합"]); rows.push([d, "시멘트(OPC)", "Blaine", 3440 + i * 10, "cm2/g", "적합"]);
    rows.push([d, "시멘트(OPC)", "SO3", 2.5, "%", "적합"]);
  });
  rows.push(["2026-11-03 08:00", "시멘트(OPC)", "28일 압축강도", 51.2, "MPa", "적합"]); rows.push(["2026-11-03 08:00", "시멘트(HES)", "28일 압축강도", 58.0, "MPa", "적합"]);
  rows.push(["2026-11-03 08:00", "시멘트(OPC)", "6가크롬", "<0.5", "mg/kg", "적합"]);
  const a = E.analyze(rows); assert.strictEqual(a.layout, "long"); assert.ok(a.status.auto, a.status.issues.join());
  const map = Object.fromEntries(a.pairs.map((p) => [p.point + "/" + p.test, p.key]));
  assert.strictEqual(map["생료/CaO"], "rm_cao"); assert.strictEqual(map["클링커/CaO"], "clk_cao"); assert.strictEqual(map["클링커/f-CaO"], "clk_fcao");
  assert.strictEqual(map["시멘트(OPC)/Blaine"], "cem_blaine"); assert.strictEqual(map["시멘트(OPC)/28일 압축강도"], "phy_s28"); assert.strictEqual(map["시멘트(OPC)/6가크롬"], "phy_crvi");
  const r = E.extract(a);
  assert.deepStrictEqual(col(r, "raw_meal", "rm_cao"), [43.8, 43.9, 44.0]); assert.deepStrictEqual(col(r, "clinker", "clk_fcao"), [0.9, 1.0, 1.1]);
  const phys = r.tables.physical; assert.ok(phys.byProduct); const prods = phys.rows.map((x) => x[1]).sort(); assert.deepStrictEqual(prods, ["1종", "3종"]);   // 같은 일시·품종의 28일강도와 6가크롬은 한 행
  assert.strictEqual(r.summary.censored, 1);
});

t("⑤ 열 이름을 전혀 모를 때: 값 범위로 '추정(확인 필요)' 제안, 자동 반영은 안 함", () => {
  const a = E.analyze([["T", "X1", "X2", "X3"], ["2026-11-01 08:00", 0.9, 95.1, 3450], ["2026-11-01 16:00", 1.1, 94.6, 3480], ["2026-11-02 08:00", 0.8, 95.6, 3510], ["2026-11-02 16:00", 1.0, 95.2, 3440]]);
  const k = Object.fromEntries(a.cols.map((c) => [c.header, c]));
  assert.strictEqual(k.X3.key, "cem_blaine"); assert.strictEqual(k.X3.conf, "mid");
  assert.strictEqual(a.status.auto, false);                         // 추정이라 확인 필요
});

t("⑥ 엑셀 일련번호 날짜·8자리 날짜·번호 열 무시·텍스트 열 무시", () => {
  const a = E.analyze([["No", "분석일자", "시료번호", "자유석회", "판정", "비고"], [1, 46296, "A-01", 0.9, "OK", "재시험"], [2, 46297, "A-02", 1.2, "OK", ""], [3, 46298, "A-03", "<0.5", "OK", ""]]);
  assert.ok(a.status.auto, a.status.issues.join()); const r = E.extract(a);
  assert.deepStrictEqual(col(r, "clinker", "clk_fcao"), [0.9, 1.2, 0.5]);
  assert.ok(r.summary.ignored.indexOf("비고") >= 0 || r.summary.ignored.indexOf("판정") >= 0);
});

t("⑦ 관련 없는 표는 항목 0개로 판정(조용히 거짓 반영 안 함)", () => {
  const a = E.analyze([["이름", "부서", "연락처"], ["홍길동", "품질", "010"], ["김철수", "생산", "011"]]);
  assert.ok(!a || a.status.items === 0);
});

t("⑧ 한글 이름 + 가로형 다항목(압축강도·응결·6가크롬)과 품종 열", () => {
  const a = E.analyze([["일시", "품종", "3일 압축강도(MPa)", "28일 압축강도(MPa)", "초결(분)", "수용성 6가크롬(mg/kg)"],
    ["2026-11-01", "OPC", 29.5, 52.1, 220, 6.5], ["2026-11-01", "HES", 36.0, 58.2, 190, 8.1], ["2026-11-02", "OPC", 30.1, 51.8, 225, 5.9]]);
  assert.ok(a.status.auto, a.status.issues.join()); assert.deepStrictEqual(a.cols.filter((c) => c.key).map((c) => c.key), ["phy_s3", "phy_s28", "phy_ist", "phy_crvi"]);
  const r = E.extract(a); assert.ok(r.tables.physical.byProduct); assert.deepStrictEqual(r.tables.physical.rows.map((x) => x[1]), ["1종", "3종", "1종"]);
});

t("⑨ 영문 머리글·약어(Free CaO, Blaine, 1D/3D/7D/28D)", () => {
  const a = E.analyze([["Sampling Date", "Free CaO (%)", "LSF", "Blaine (cm2/g)", "SO3 (%)"], ["2026-11-01 08:00", 0.9, 95.1, 3450, 2.55], ["2026-11-01 16:00", 1.0, 95.0, 3460, 2.6]]);
  const m = Object.fromEntries(a.cols.filter((c) => c.key).map((c) => [c.header, c.key]));
  assert.strictEqual(m["Free CaO (%)"], "clk_fcao"); assert.strictEqual(m["Blaine (cm2/g)"], "cem_blaine"); assert.strictEqual(m["SO3 (%)"], "cem_so3");   // 같은 시트에 Blaine(시멘트)이 있어 추정
  assert.strictEqual(a.cols.find((c) => c.header === "SO3 (%)").conf, "mid"); assert.strictEqual(a.status.auto, false);   // 추정이므로 확인 요청
  const b = E.analyze([["일시", "1D", "3D", "7D", "28D"], ["2026-11-01", 18.2, 29.5, 40.1, 52.0], ["2026-11-02", 18.5, 30.0, 40.5, 52.4]]);
  assert.deepStrictEqual(b.cols.filter((c) => c.key).map((c) => c.key), ["phy_s1", "phy_s3", "phy_s7", "phy_s28"]);
});

t("⑩ XRD 그룹 머리글 아래 Alite/Belite → xrd 표, 같은 C3A 가 클링커(Bogue)와 구분", () => {
  const a = E.analyze([["", "XRD", "", "", "클링커(Bogue)"], ["일시", "Alite", "Belite", "C3A", "C3A"],
    ["2026-11-01", 62.5, 16.1, 7.2, 8.0], ["2026-11-02", 63.0, 15.8, 7.0, 8.2], ["2026-11-03", 62.1, 16.5, 7.4, 7.9]]);
  assert.deepStrictEqual(a.cols.filter((c) => c.key).map((c) => c.key), ["xrd_alite", "xrd_belite", "xrd_c3a", "clk_c3a"]);
});

t("⑪ 줄바꿈이 든 머리글, 빈 줄 섞임, 같은 일시 중복(마지막 값 사용)", () => {
  const a = E.analyze([["일시", "28일\n압축강도\n(MPa)", "비고"], ["2026-11-01", 51.0, "a"], [], ["2026-11-01", 52.0, "재시험"], [null, null, null], ["2026-11-02", 50.5, ""]]);
  assert.ok(a.status.auto, a.status.issues.join()); const r = E.extract(a);
  assert.deepStrictEqual(col(r, "physical", "phy_s28"), [52.0, 50.5]);
});

t("⑫ 결과 열이 문자('3,450' 단위 붙음)여도 숫자로, 승인 대기 행은 값이 비어 건너뜀", () => {
  const a = E.analyze([["일시", "시멘트 분말도", "28일 압축강도"], ["2026-11-01", "3,450", "51.2 MPa"], ["2026-11-02", "3,470", ""], ["2026-11-03", "", "52.0 MPa"]]);
  assert.ok(a.status.auto, a.status.issues.join()); const r = E.extract(a);
  assert.deepStrictEqual(col(r, "cement", "cem_blaine"), [3450, 3470]); assert.deepStrictEqual(col(r, "physical", "phy_s28"), [51.2, 52.0]);   // 값이 없는 행은 만들지 않음
});

t("⑬ 요약 정보: 읽은 행·건너뛴 행·무시한 열", () => {
  const a = E.analyze([["일시", "자유석회", "시험자", "판정"], ["2026-11-01", 0.9, "홍", "적합"], ["합계", 0.9, "", ""]]);
  const r = E.extract(a); assert.strictEqual(r.summary.rowsRead, 1); assert.strictEqual(r.summary.rowsSkipped, 1);
  assert.ok(r.summary.ignored.indexOf("시험자") >= 0 && r.summary.ignored.indexOf("판정") >= 0);
});

console.log(`\n${n} passed`);
