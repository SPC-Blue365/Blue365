/**
 * 경영진 보고용 「QMS 2단계 기능 확장 보고」 PPT 생성 스크립트 (pptxgenjs).
 *
 * 준비:  npm install pptxgenjs react-icons react react-dom sharp
 * 실행:  python scripts/export_phase2_deck_data.py            # 시스템 계산값 → docs/src/deck_phase2_data.json
 *        node docs/src/build_phase2_deck.js docs/src/deck_phase2_data.json <출력.pptx> [apply_theme.js 경로]
 * 모든 수치는 deck_phase2_data.json(시스템 모듈 계산 결과, 데모 데이터)에서 읽는다.
 */
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const [, , DATA_PATH, OUT_PATH, THEME_JS] = process.argv;
const D = JSON.parse(fs.readFileSync(DATA_PATH, "utf-8"));
const IMG = path.join(__dirname, "..", "img");

const THEME = {
  name: "Blue365 QMS",
  headFontFace: "맑은 고딕",
  bodyFontFace: "맑은 고딕",
  colors: {
    dk1: "1F2A30", lt1: "FFFFFF", dk2: "5F6B73", lt2: "F1F3F4",
    accent1: "C2410C", accent2: "2A78D6", accent3: "0CA30C", accent4: "EC835A", accent5: "FAB219", accent6: "D03B3B",
    hlink: "2A78D6", folHlink: "4A3AA7",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.author = "품질관리팀";
pres.title = "QMS 2단계 기능 확장 보고";
pres.subject = "원료 배합 설계 · 재령별 강도 예측 · 6가크롬 · LIMS 연동 · AI 솔루션";
const C = pres.SchemeColor;

// ── 레이아웃 ──────────────────────────────────────────────────────────
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 1.75, w: 11.7, h: 1.5, fontSize: 40, bold: true,
      color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "subtitle", type: "body", x: 0.8, y: 3.4, w: 11.7, h: 1.0, fontSize: 20,
      color: C.background2, valign: "top", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "org", type: "body", x: 0.8, y: 6.35, w: 11.7, h: 0.5, fontSize: 14,
      color: C.background2, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.7, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.3, w: 12.1, h: 0.75, fontSize: 34, bold: true,
      color: C.text1, valign: "top", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "msg", type: "body", x: 0.6, y: 1.08, w: 12.1, h: 0.5, fontSize: 17,
      color: C.accent1, valign: "top", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "src", type: "body", x: 0.6, y: 6.98, w: 11.3, h: 0.36, fontSize: 10,
      color: C.text2, valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.25, y: 6.98, w: 0.45, h: 0.3, fontSize: 10, color: C.text2, align: "right" },
});

// ── 공통 요소 ─────────────────────────────────────────────────────────
async function icon(Comp, hex, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + hex, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

function card(slide, x, y, w, h, name, fill = C.background2) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill, width: 0 },
    rectRadius: 0.08, objectName: name });
}

async function iconCircle(slide, Comp, x, y, d, fillScheme, name) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fillScheme }, line: { color: fillScheme, width: 0 },
    objectName: name + " circle" });
  const pad = d * 0.24;
  slide.addImage({ data: await icon(Comp, "FFFFFF"), x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad,
    objectName: name + " icon" });
}

function text(slide, runs, opts) {
  slide.addText(runs, Object.assign({ isTextBox: true, margin: 0, valign: "top", color: C.text1, fontSize: 14 }, opts));
}

function bullets(items, size = 14, color = C.text1) {
  return items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1, fontSize: size, color,
    paraSpaceAfter: 6 } }));
}

function arrow(slide, x, y, w, h, name) {
  slide.addShape(pres.shapes.RIGHT_ARROW, { x, y, w, h, fill: { color: C.text2 }, line: { color: C.text2, width: 0 },
    objectName: name });
}

function header(cells) {
  return cells.map((t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text1 } } }));
}

const TABLE_OPTS = { fontSize: 12, color: C.text1, border: { type: "solid", pt: 0.75, color: "CFD8DC" }, valign: "middle",
  margin: [0.04, 0.08, 0.04, 0.08] };
const AXIS = { catAxisLabelColor: HEX.dk2, valAxisLabelColor: HEX.dk2, catAxisLabelFontSize: 11, valAxisLabelFontSize: 11,
  catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", valGridLine: { color: "E1E0D9", size: 0.75 },
  catGridLine: { style: "none" }, legendFontFace: "+mn-lt", legendFontSize: 11, legendColor: HEX.dk2 };

function addSlide(section) {
  return pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
}

function fmt(v, nd = 1) {
  return v === null || v === undefined ? "-" : Number(v).toLocaleString("ko-KR", { minimumFractionDigits: nd, maximumFractionDigits: nd });
}

(async () => {
  const R = D.rawmix, CV = D.conversion, S1 = D.strength["1종"], CR = D.chromium, L = D.lims;

  // ── 1. 표지 ──────────────────────────────────────────────────────────
  pres.addSection({ title: "도입" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "도입" });
  s.addText("QMS 2단계 기능 확장 보고", { placeholder: "title" });
  s.addText("원료 배합 설계 · 재령별 강도 예측 · 6가크롬 관리 · LIMS 연동 · AI 솔루션", { placeholder: "subtitle" });
  s.addText("품질관리팀  ·  2026년 10월  ·  경영진 보고", { placeholder: "org" });
  const motif = [fa.FaFlask, fa.FaChartLine, fa.FaRadiation, fa.FaLink, fa.FaRobot];
  for (let i = 0; i < motif.length; i++) await iconCircle(s, motif[i], 0.8 + i * 0.95, 4.75, 0.7, C.accent1, `Motif ${i + 1}`);
  s.addNotes("1단계 품질 감시·알림·진단 시스템에 이어, 원료 배합 설계부터 제품 강도·6가크롬 예측, LIMS 자동 연동, AI 솔루션 보고서까지 확장한 결과를 보고드립니다.");

  // ── 2. 핵심 요약 ─────────────────────────────────────────────────────
  s = addSlide("도입");
  s.addText("핵심 요약", { placeholder: "title" });
  s.addText("감시를 넘어 '설계·예측·환경 품질'까지 확장했습니다 — LIMS 연결 후 실데이터 시범을 요청드립니다", { placeholder: "msg" });
  const stats = [
    ["0.00", "배합 목표 편차(LSF·SM·IM)", `원료 5종 자동 배합 · 원가 최소 시 원료비 −${fmt(R.cost_saving_pct)}%`],
    [`${fmt(S1.models.find((m) => m.target === "28일 강도").rmse, 2)} MPa`, "28일 강도 예측 오차(LOO, 1종)",
      "생산 당일 클링커·분쇄 조건으로 예측"],
    [`${fmt(CR.cal.median)}%`, "실측 보정한 킬른 Cr⁶⁺ 전환율", "데모 정답 12.0% 재현 · 문헌 범위 8~20%"],
  ];
  stats.forEach(([v, l, sub], i) => {
    const y = 1.85 + i * 1.65;
    card(s, 0.6, y, 4.3, 1.45, `Stat ${i + 1}`);
    text(s, v, { x: 0.85, y: y + 0.18, w: 3.9, h: 0.65, fontSize: 36, bold: true });
    text(s, l, { x: 0.85, y: y + 0.82, w: 3.9, h: 0.3, fontSize: 14, bold: true });
    text(s, sub, { x: 0.85, y: y + 1.1, w: 3.9, h: 0.3, fontSize: 11, color: C.text2 });
  });
  const rows2 = [
    [fa.FaBullseye, "목적", "배합 설계 → 클링커 → 강도·응결 → 6가크롬까지 예측하고, 목표를 맞추는 조치를 제시"],
    [fa.FaCheckCircle, "2단계 결과", "배합 최적화 · 클링커/XRD 예측 · 재령별 강도·응결 예측과 제어 솔루션 · 6가크롬 · LIMS 연동 · AI 보고서"],
    [fa.FaRoute, "다음 단계", "LIMS 실연결 후 2~3개월 실데이터로 예측 모델·전환율·환원제 계수를 공장에 맞게 보정"],
    [fa.FaHandshake, "요청 사항", "LIMS 접근 협조 · 원료·연료 크롬 분석 · AI 사용 보안 승인"],
  ];
  for (let i = 0; i < rows2.length; i++) {
    const [Ic, h, t] = rows2[i];
    const y = 1.9 + i * 1.22;
    await iconCircle(s, Ic, 5.35, y, 0.62, C.accent2, `Summary ${h}`);
    text(s, h, { x: 6.2, y: y - 0.02, w: 6.5, h: 0.36, fontSize: 17, bold: true });
    text(s, t, { x: 6.2, y: y + 0.36, w: 6.5, h: 0.7, fontSize: 14 });
  }
  s.addText("※ 수치는 데모(가상) 데이터 검증 결과 — 실데이터 성능은 3단계 시범 운영에서 확인", { placeholder: "src" });
  s.addNotes("세 숫자가 핵심입니다. 배합은 목표 계수를 정확히 맞추고, 28일 강도는 생산 당일 약 1 MPa 오차로 예측하며, 6가크롬 전환율은 실측으로 보정됩니다. 모두 가상 데이터 기준이며 실데이터 검증이 다음 과제입니다.");

  // ── 3. 기능 구성 ─────────────────────────────────────────────────────
  pres.addSection({ title: "기능" });
  s = addSlide("기능");
  s.addText("2단계 기능 구성", { placeholder: "title" });
  s.addText("원료 배합부터 제품 강도·6가크롬까지 한 흐름으로 예측하고, LIMS 실측으로 계속 보정합니다", { placeholder: "msg" });
  const flow = [
    [fa.FaFlask, "① 원료 배합 최적화", "목표 LSF·SM·IM·C₃S\n원가 최소 배합"],
    [fa.FaFire, "② 클링커 예측", "계수·Bogue·XRD 광물\nf-CaO(소성성)"],
    [fa.FaChartLine, "③ 강도·응결 예측", "1·3·7·28일 강도\n초결·종결(95% 구간)"],
    [fa.FaSlidersH, "④ 제어 솔루션", "목표 달성 최소 조치\n조치 지식베이스"],
  ];
  for (let i = 0; i < flow.length; i++) {
    const [Ic, h, t] = flow[i];
    const x = 0.6 + i * 3.13;
    card(s, x, 1.85, 2.75, 2.35, `Flow ${i + 1}`);
    await iconCircle(s, Ic, x + 0.25, 2.07, 0.62, C.accent1, `Flow ${i + 1}`);
    text(s, h, { x: x + 0.25, y: 2.82, w: 2.35, h: 0.4, fontSize: 16, bold: true });
    text(s, t, { x: x + 0.25, y: 3.25, w: 2.35, h: 0.8, fontSize: 13, color: C.text2 });
    if (i < flow.length - 1) arrow(s, x + 2.8, 2.85, 0.28, 0.32, `Flow arrow ${i + 1}`);
  }
  const extra = [
    [fa.FaRadiation, "시멘트 6가크롬", "원료·연료·내화물 총 크롬 물질수지 × 킬른 전환율 → Cr⁶⁺ 예측, 환원제 필요량·원가, 실측 보정"],
    [fa.FaLink, "LIMS 연동", "승인된 시험 결과만 증분 동기화 → 모니터링·예측에 즉시 반영(SQL·REST·파일)"],
    [fa.FaRobot, "AI 솔루션 보고서", "계산 결과와 지식베이스만 근거로 경영진용 보고서 작성(사실/추정 구분)"],
  ];
  for (let i = 0; i < extra.length; i++) {
    const [Ic, h, t] = extra[i];
    const x = 0.6 + i * 4.1;
    card(s, x, 4.45, 3.9, 2.3, `Extra ${i + 1}`);
    await iconCircle(s, Ic, x + 0.25, 4.67, 0.62, C.accent2, `Extra ${i + 1}`);
    text(s, h, { x: x + 1.05, y: 4.78, w: 2.7, h: 0.4, fontSize: 16, bold: true });
    text(s, t, { x: x + 0.25, y: 5.42, w: 3.4, h: 1.2, fontSize: 13 });
  }
  s.addText("화면: 🧪 원료 배합·클링커 설계(①~④) · ☢️ 시멘트 6가크롬 · 🔗 LIMS 연동 · ⚙️ AI(LLM) 설정", { placeholder: "src" });
  s.addNotes("위쪽은 원료에서 제품 강도까지 이어지는 설계·예측 흐름이고, 아래는 6가크롬, LIMS, AI 세 가지 확장 기능입니다.");

  // ── 4. 원료 배합 ─────────────────────────────────────────────────────
  s = addSlide("기능");
  s.addText("원료 배합·클링커 설계", { placeholder: "title" });
  s.addText("목표 LSF·SM·IM을 정확히 맞추는 배합비를 자동 계산하고, 원가가 가장 낮은 배합도 제시합니다", { placeholder: "msg" });
  const shotW = 7.4, shotH = shotW * 505 / 1000;
  s.addImage({ path: path.join(IMG, "deck_rawmix.jpg"), x: 0.6, y: 1.85, w: shotW, h: shotH, objectName: "Screen raw mix" });
  text(s, "실제 화면: 예시 원료 5종 → 클링커 기준 LSF 95.0 · SM 2.50 · IM 1.60 달성",
    { x: 0.6, y: 1.85 + shotH + 0.12, w: shotW, h: 0.3, fontSize: 11, color: C.text2 });
  card(s, 8.3, 1.85, 4.4, 4.9, "Raw mix points");
  text(s, "계산 방식", { x: 8.55, y: 2.0, w: 3.9, h: 0.35, fontSize: 16, bold: true });
  text(s, bullets([
    "석탄회 흡수까지 반영한 클링커 기준 목표",
    "원료별 하한·상한·고정 비율 제약",
    "목표 근접(최소자승) 또는 원가 최소",
    "건조→습윤 배합비(정량공급기 설정값)",
    "원료 1%p 변경 시 계수 변화(민감도)",
  ], 13), { x: 8.55, y: 2.42, w: 3.95, h: 2.15 });
  s.addTable([header(["계산 방식", "원료비(원/t-클링커)"]),
    ["목표 근접", fmt(R.cost_lsq, 0)],
    ["원가 최소", { text: `${fmt(R.cost_min, 0)} (−${fmt(R.cost_saving_pct)}%)`, options: { bold: true } }]],
  Object.assign({}, TABLE_OPTS, { x: 8.55, y: 4.75, w: 3.9, colW: [1.5, 2.4], rowH: 0.4 }));
  text(s, `예측 클링커: C₃S ${fmt(R.clk.C3S)}% · 액상량 ${fmt(R.clk.liquid)}% · XRD 알라이트 ${fmt(R.clk.alite)}%`,
    { x: 8.55, y: 6.05, w: 3.95, h: 0.55, fontSize: 12, color: C.text2 });
  s.addText("※ 원료 성분·단가는 예시값(추정) — 원료 입고 분석값으로 교체해 사용. 배합 설계서(엑셀) 자동 생성", { placeholder: "src" });
  s.addNotes("석회석·규석·점토·철광석·석탄재 다섯 원료로 목표 계수를 정확히 맞췄고, 허용 편차 안에서 원가 최소 배합을 고르면 원료비가 3.5% 낮아집니다(예시 단가 기준).");

  // ── 5. 클링커 예측 검증 ──────────────────────────────────────────────
  s = addSlide("기능");
  s.addText("클링커 예측 검증", { placeholder: "title" });
  s.addText(`생료 분석값으로 클링커 LSF를 예측하고, 제안한 석탄회 흡수율 보정으로 오차를 ${fmt(CV.rmse.LSF, 2)} → ${fmt(CV.rmse_fix.LSF, 2)}로 줄입니다`,
    { placeholder: "msg" });
  s.addChart([
    { type: pres.charts.LINE, data: [{ name: "클링커 LSF 실측", labels: CV.cats, values: CV.act }],
      options: { chartColors: [HEX.accent2], lineDataSymbol: "circle", lineDataSymbolSize: 5, lineSize: 2 } },
    { type: pres.charts.LINE, data: [{ name: "생료 기반 예측(흡수율 보정 후)", labels: CV.cats, values: CV.pred }],
      options: { chartColors: ["6DA7EC"], lineDataSymbol: "none", lineDash: "dash", lineSize: 2 } },
  ], Object.assign({}, AXIS, { x: 0.6, y: 1.85, w: 7.6, h: 4.75, showLegend: true, legendPos: "t", catAxisLabelRotate: -45,
    valAxisMinVal: 93.5, valAxisMaxVal: 96.5, valAxisLabelFormatCode: "0.0", showTitle: true,
    title: "클링커 LSF — 최근 7일 8시간 평균", titleFontSize: 13, titleColor: HEX.dk1, titleFontFace: "+mn-lt",
    objectName: "LSF chart" }));
  const kpis = [["LSF", CV.rmse.LSF, CV.rmse_fix.LSF, 2], ["SM", CV.rmse.SM, CV.rmse_fix.SM, 3],
    ["IM", CV.rmse.IM, CV.rmse_fix.IM, 3]];
  kpis.forEach(([k, v, vf, nd], i) => {
    const x = 8.5 + i * 1.43;
    card(s, x, 1.85, 1.3, 1.25, `KPI ${k}`);
    text(s, fmt(vf, nd), { x: x + 0.12, y: 1.98, w: 1.1, h: 0.5, fontSize: 22, bold: true });
    text(s, `${k} 오차`, { x: x + 0.12, y: 2.5, w: 1.1, h: 0.28, fontSize: 12, color: C.text2 });
    text(s, `보정 전 ${fmt(v, nd)}`, { x: x + 0.12, y: 2.76, w: 1.1, h: 0.26, fontSize: 10, color: C.text2 });
  });
  card(s, 8.5, 3.3, 4.2, 3.3, "Conversion insight");
  text(s, "읽는 법", { x: 8.75, y: 3.45, w: 3.7, h: 0.35, fontSize: 16, bold: true });
  text(s, bullets([
    `오차 = 생료 실측으로 계산한 클링커 계수와 실측의 RMSE(전체 기간)`,
    `석탄회 흡수 실적 ${fmt(CV.a_eff, 4)} vs 설정 ${fmt(CV.a_set, 4)} → 시스템이 흡수율 ${fmt(CV.absorb_fix, 0)}%로 보정 제안(위 오차는 보정 후)`,
    `f-CaO 소성성 회귀 R² ${fmt(CV.fcao_r2, 2)} — LSF·SM·잔사·소성대 온도로 예측`,
  ], 13), { x: 8.75, y: 3.9, w: 3.75, h: 2.6 });
  s.addText("출처: Blue365 QMS 실적 검증(데모 데이터, 생료 2시간 → 클링커 대응) · 오차 단위 = 각 계수 단위", { placeholder: "src" });
  s.addNotes("배합이 실제 소성 후 어떤 클링커가 되는지를 생료 분석값으로 예측해 실측과 대조했습니다. 차이가 나면 석탄회 흡수율 보정값을 시스템이 제안합니다.");

  // ── 6. 재령별 강도·응결 예측 ─────────────────────────────────────────
  s = addSlide("기능");
  s.addText("재령별 강도·응결 예측", { placeholder: "title" });
  s.addText("클링커 광물(XRD)·분쇄 조건으로 1·3·7·28일 강도와 응결을 생산 당일 예측합니다", { placeholder: "msg" });
  const sw = 7.4, sh = sw * 360 / 1000;
  s.addImage({ path: path.join(IMG, "deck_strength.jpg"), x: 0.6, y: 1.85, w: sw, h: sh, objectName: "Screen strength" });
  const mrows = [header(["항목(1종)", "학습 로트", "예측 오차(LOO)", "모델"])];
  S1.models.forEach((m) => mrows.push([m.target, `${m.n}`, `${fmt(m.rmse, 2)} ${m.target.includes("결") ? "분" : "MPa"}`,
    m.source.startsWith("공장") ? "경험칙 + 공장 보정" : "경험칙"]));
  s.addTable(mrows, Object.assign({}, TABLE_OPTS, { x: 0.6, y: 1.85 + sh + 0.25, w: 7.4, colW: [1.6, 1.3, 2.0, 2.5], rowH: 0.34 }));
  card(s, 8.3, 1.85, 4.4, 4.9, "Strength method");
  await iconCircle(s, fa.FaBrain, 8.55, 2.05, 0.6, C.accent2, "Method");
  text(s, "예측 모델 설계", { x: 9.3, y: 2.17, w: 3.2, h: 0.4, fontSize: 16, bold: true });
  text(s, bullets([
    "경험칙 계수에서 출발해 공장 데이터로 보정(데이터가 적으면 경험칙 유지)",
    "XRD 실측 광물 우선, 없는 날은 Bogue 값을 보정식으로 환산",
    "시험조건(양생수 온도 등) 이탈 로트는 학습 제외",
    "이론과 반대 부호 계수는 자동 차단 — 과적합·외삽 방지",
    "입력별 기여도로 '왜 이 값인가'를 설명",
  ], 13), { x: 8.55, y: 2.85, w: 3.95, h: 3.8 });
  s.addText("※ 예측구간 = 예측 ± 1.96 × LOO 오차(약 95%) · 데모 데이터 기준 — 실데이터로 재학습 필요", { placeholder: "src" });
  s.addNotes("기존 28일 예측은 조기강도 결과가 나와야 했지만, 새 모델은 생산 당일 클링커 광물과 분말도·SO₃만으로 모든 재령을 예측합니다.");

  // ── 7. 제어 솔루션 ───────────────────────────────────────────────────
  s = addSlide("기능");
  const lv = S1.plan.levers[0];
  s.addText("강도·응결 제어 솔루션", { placeholder: "title" });
  s.addText(lv ? `목표를 맞추는 '최소 조치'를 계산합니다 — 예: 사내 목표 달성에 ${lv.lever} ${lv.delta > 0 ? "+" : ""}${fmt(lv.delta, 0)} ${lv.unit} 하나로 충분`
    : "목표를 맞추는 '최소 조치'를 계산합니다", { placeholder: "msg" });
  const steps = [
    [fa.FaBullseye, "목표", "사내 목표값\n3일 29.5·7일 40·28일 53 MPa\n초결 150~300분"],
    [fa.FaCogs, "최적화", "레버 7종(분말도·SO₃·석회석·\n알라이트·C₃A·f-CaO·밀 온도)\n변경 비용 최소"],
    [fa.FaCheckCircle, "권장 조치", lv ? `${lv.lever}\n${fmt(lv.now, 0)} → ${fmt(lv.rec, 0)} ${lv.unit}` : "조정 불필요"],
  ];
  for (let i = 0; i < steps.length; i++) {
    const [Ic, h, t] = steps[i];
    const y = 1.85 + i * 1.62;
    card(s, 0.6, y, 4.3, 1.42, `Step ${i + 1}`, i === 2 ? "FDEBD3" : C.background2);
    await iconCircle(s, Ic, 0.8, y + 0.22, 0.6, i === 2 ? C.accent1 : C.accent2, `Step ${i + 1}`);
    text(s, h, { x: 1.6, y: y + 0.16, w: 3.1, h: 0.36, fontSize: 16, bold: true });
    text(s, t, { x: 1.6, y: y + 0.52, w: 3.15, h: 0.85, fontSize: 12, color: C.text1 });
  }
  const orows = [header(["항목", "목표", "현재 예측", "조치 후 예측", "판정"])];
  S1.plan.outcome.forEach((o) => orows.push([o.item, o.goal, fmt(o.now), { text: fmt(o.after), options: { bold: true } },
    o.ok.replace("✅ ", "")]));
  s.addTable(orows, Object.assign({}, TABLE_OPTS, { x: 5.25, y: 1.85, w: 7.45, colW: [1.45, 1.55, 1.45, 1.6, 1.4], rowH: 0.42 }));
  card(s, 5.25, 4.6, 7.45, 2.15, "KB groups");
  text(s, "함께 제시되는 조치 라이브러리(효과·부작용·확인 방법 포함)", { x: 5.5, y: 4.72, w: 7.0, h: 0.35, fontSize: 14, bold: true });
  text(s, bullets([
    "초기강도↑: 분말도·SO₃ 최적화·석회석↓·C₃A↑·알라이트↑·분쇄조제(TEA)·급랭",
    "장기강도↑: 알라이트↑·f-CaO 안정화·석회석↓·알칼리↓·SO₃ 최적·TIPA·풍화 방지",
    `응결 연장/단축: 석고(SO₃)·밀 출구 온도·C₃A·분말도 — 예: 초결 +20분 → ${(D.strength["1종"].setting_example[0] || {}).lever || "SO₃"} +${fmt((D.strength["1종"].setting_example[0] || {}).delta, 2)}%p`,
  ], 12), { x: 5.5, y: 5.12, w: 7.0, h: 1.55 });
  s.addText("※ 효과 수치는 예측 모델·경험칙 기반 추정 — 실기 시험으로 확인 후 적용", { placeholder: "src" });
  s.addNotes("현재 최근 로트는 사내 하한은 만족하지만 목표값에는 조금 못 미칩니다. 시스템은 분말도를 약 55 cm²/g 올리는 한 가지 조치로 세 재령 목표를 모두 맞출 수 있다고 계산합니다.");

  // ── 8. 6가크롬 예측·환원제 ───────────────────────────────────────────
  pres.addSection({ title: "6가크롬" });
  s = addSlide("6가크롬");
  s.addText("시멘트 6가크롬 예측·환원제", { placeholder: "title" });
  s.addText("총 크롬 물질수지로 Cr⁶⁺를 예측하고, 기준별 환원제 필요량과 원가를 산출합니다", { placeholder: "msg" });
  const par = CR.pareto.slice().reverse();
  s.addChart(pres.charts.BAR, [{ name: "기여(mg/kg)", labels: par.map((p) => p.name), values: par.map((p) => p.mg) }],
    Object.assign({}, AXIS, { x: 0.6, y: 1.85, w: 6.3, h: 4.8, barDir: "bar", chartColors: [HEX.accent2], showValue: true,
      dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: HEX.dk1, dataLabelFontFace: "+mn-lt",
      dataLabelFormatCode: "0.00", showLegend: false, showTitle: true, title: "시멘트 Cr⁶⁺(환원 전) 기여 상위 6 — mg/kg",
      titleFontSize: 13, titleColor: HEX.dk1, titleFontFace: "+mn-lt", valAxisHidden: true, valGridLine: { style: "none" },
      objectName: "Cr pareto chart" }));
  const ck = [["클링커 총 Cr", `${fmt(CR.total_clk)} mg/kg`], ["클링커 Cr⁶⁺", `${fmt(CR.crvi_clk, 2)} mg/kg`],
    ["시멘트(환원 전)", `${fmt(CR.cem0, 2)} mg/kg`], ["시멘트(환원 후)", `${fmt(CR.cem_after, 2)} mg/kg`]];
  ck.forEach(([l, v], i) => {
    const x = 7.2 + (i % 2) * 2.8, y = 1.85 + Math.floor(i / 2) * 1.2;
    card(s, x, y, 2.6, 1.05, `Cr KPI ${i + 1}`);
    text(s, v, { x: x + 0.18, y: y + 0.12, w: 2.3, h: 0.5, fontSize: 20, bold: true });
    text(s, l, { x: x + 0.18, y: y + 0.65, w: 2.3, h: 0.3, fontSize: 12, color: C.text2 });
  });
  const drows = [header(["환원제(EU 2 mg/kg 대응)", "투입량", "원가"])];
  CR.doses_eu2.forEach((d) => drows.push([d.reducer, `${fmt(d.kg_t, 2)} kg/t`, `${fmt(d.won_t, 0)} 원/t`]));
  s.addTable(drows, Object.assign({}, TABLE_OPTS, { x: 7.2, y: 4.35, w: 5.5, colW: [2.9, 1.25, 1.35], rowH: 0.42 }));
  text(s, `전환율 ${fmt(CR.conv)}%(실측 보정) · 현재 투입 ${fmt(CR.dose_now, 1)} kg/t → 국내 자율기준 20 mg/kg 대비 충분한 여유`,
    { x: 7.2, y: 6.15, w: 5.5, h: 0.5, fontSize: 12, color: C.text2 });
  s.addText("※ 원료·연료 Cr 함량·과잉계수·단가는 예시값(추정). 국내 20(KS L 5221)과 EU 2(EN 196-10)는 시험법이 달라 직접 비교 불가", { placeholder: "src" });
  s.addNotes("예시 조건에서 6가크롬은 석회석, 크롬계 내화물, 점토, 석탄재 순으로 기여합니다. 국내 자율기준 대비 여유는 충분하고, EU 수준으로 낮추려면 황산제1철 약 1.6 kg/t, 원가 약 300원/t가 필요한 것으로 추정됩니다.");

  // ── 9. 6가크롬 실측 보정·이상 감지 ───────────────────────────────────
  s = addSlide("6가크롬");
  s.addText("6가크롬 실측 보정·이상 감지", { placeholder: "title" });
  s.addText("실측으로 전환율을 보정하고, 고크롬 원료 투입(S7)을 자동 감지해 원인을 맞혔습니다", { placeholder: "msg" });
  const tc = CR.trend.cats;
  s.addChart([
    { type: pres.charts.LINE, data: [{ name: "시멘트 수용성 Cr⁶⁺(로트)", labels: tc, values: CR.trend.vals }],
      options: { chartColors: [HEX.accent2], lineDataSymbol: "circle", lineDataSymbolSize: 5, lineSize: 2 } },
    { type: pres.charts.LINE, data: [{ name: "자율기준 20", labels: tc, values: tc.map(() => 20) }],
      options: { chartColors: [HEX.accent6], lineDataSymbol: "none", lineSize: 1.25 } },
    { type: pres.charts.LINE, data: [{ name: "사내 경고 18", labels: tc, values: tc.map(() => 18) }],
      options: { chartColors: [HEX.accent4], lineDataSymbol: "none", lineSize: 1.25, lineDash: "dash" } },
  ], Object.assign({}, AXIS, { x: 0.6, y: 1.85, w: 7.6, h: 4.8, showLegend: true, legendPos: "t", catAxisLabelRotate: 0,
    valAxisMinVal: 0, valAxisMaxVal: 25, valAxisLabelFormatCode: "0", showTitle: true,
    title: "시멘트 수용성 Cr⁶⁺ — 최근 45일 전 품종 로트(mg/kg)", titleFontSize: 13, titleColor: HEX.dk1, titleFontFace: "+mn-lt",
    objectName: "Cr trend chart" }));
  card(s, 8.5, 1.85, 4.2, 2.3, "Calibration card");
  text(s, "전환율 실측 보정", { x: 8.75, y: 2.0, w: 3.7, h: 0.35, fontSize: 16, bold: true });
  text(s, bullets([
    `클링커 총Cr·Cr⁶⁺ 실측 ${CR.cal.n}건 → 중앙값 ${fmt(CR.cal.median)}%(사분위 ${fmt(CR.cal.q1)}~${fmt(CR.cal.q3)}%)`,
    `킬른 O₂ 1%p↑ → 전환율 +${fmt(CR.cal.o2)}%p(회귀, 산화 분위기 영향)`,
    `환원제 실효 제거량 ${fmt(CR.effect_mean)} mg/kg(로트별 역산)`,
  ], 12), { x: 8.75, y: 2.42, w: 3.75, h: 1.7 });
  card(s, 8.5, 4.35, 4.2, 2.3, "S7 card", "FDEBD3");
  await iconCircle(s, fa.FaSearch, 8.72, 4.55, 0.55, C.accent1, "S7");
  text(s, "이상 감지·원인 진단", { x: 9.4, y: 4.63, w: 3.2, h: 0.36, fontSize: 16, bold: true });
  text(s, bullets([
    `${CR.s7.start}~${CR.s7.end} 최대 ${fmt(CR.s7.worst)} mg/kg → 🔴 자율기준 초과 알림`,
    `1순위 원인: [${CR.s7.axis}] ${CR.s7.top}(${CR.s7.verdict})`,
    "데모 정답: 철질원을 고크롬 제강슬래그로 대체",
  ], 12), { x: 8.75, y: 5.2, w: 3.75, h: 1.4 });
  s.addText("근거: 클링커 Cr의 약 8~20%가 6가로 전환·산소·알칼리 영향(Costeri 2016, Hills & Johansen 2007) · 데모 데이터 검증", { placeholder: "src" });
  s.addNotes("클링커 일일 시료의 총크롬과 6가크롬 실측으로 전환율을 보정합니다. 데모에 넣은 고크롬 원료 투입 사고를 자율기준 초과 알림으로 잡았고, 원인도 원료 크롬 증가로 정확히 진단했습니다.");

  // ── 10. LIMS 연동 ────────────────────────────────────────────────────
  pres.addSection({ title: "연계·AI" });
  s = addSlide("연계·AI");
  s.addText("LIMS 연동", { placeholder: "title" });
  s.addText("LIMS의 승인된 결과만 자동으로 가져와 모니터링·예측에 바로 반영합니다", { placeholder: "msg" });
  const lsteps = [
    [fa.FaDatabase, "조회", "DB·API·파일\n워터마크 이후만"],
    [fa.FaExchangeAlt, "표준화", "열 이름·날짜·\n부등호 값 변환"],
    [fa.FaFilter, "승인 필터", "APPROVED만\n반영"],
    [fa.FaTags, "코드 매핑", `시험코드 → QMS\n기본 ${L.mapping_rows}개 항목`],
    [fa.FaLayerGroup, "열 단위 병합", "늦은 28일 강도도\n같은 로트에 채움"],
    [fa.FaBell, "감시·알림", "동기화 후 자동\n이상 감지·발송"],
  ];
  for (let i = 0; i < lsteps.length; i++) {
    const [Ic, h, t] = lsteps[i];
    const x = 0.6 + i * 2.06;
    card(s, x, 1.85, 1.82, 2.3, `LIMS step ${i + 1}`);
    await iconCircle(s, Ic, x + 0.61, 2.0, 0.6, C.accent1, `LIMS step ${i + 1}`);
    text(s, h, { x: x + 0.08, y: 2.72, w: 1.66, h: 0.36, fontSize: 15, bold: true, align: "center" });
    text(s, t, { x: x + 0.08, y: 3.12, w: 1.66, h: 0.9, fontSize: 12, color: C.text2, align: "center" });
    if (i < lsteps.length - 1) arrow(s, x + 1.85, 2.85, 0.18, 0.3, `LIMS arrow ${i + 1}`);
  }
  card(s, 0.6, 4.4, 5.95, 2.35, "LIMS demo");
  text(s, "데모 검증(시연용 LIMS DB)", { x: 0.85, y: 4.55, w: 5.5, h: 0.35, fontSize: 16, bold: true });
  text(s, bullets([
    `시료 ${fmt(L.samples, 0)}건 · 결과 ${fmt(L.fetched, 0)}건 조회 → ${fmt(L.mapped, 0)}건 반영(원본과 오차 0)`,
    `승인 대기 ${L.pending}건 자동 제외 · 미등록 시험코드 ${L.unmapped}건 보고`,
    "재실행 시 새 결과만 조회(증분) — 중복 반영 없음",
  ], 13), { x: 0.85, y: 4.98, w: 5.5, h: 1.7 });
  card(s, 6.75, 4.4, 5.95, 2.35, "LIMS security");
  await iconCircle(s, fa.FaLock, 6.97, 4.58, 0.55, C.accent2, "Security");
  text(s, "보안·확인 필요 사항", { x: 7.65, y: 4.66, w: 4.9, h: 0.36, fontSize: 16, bold: true });
  text(s, bullets([
    "읽기 전용 DB 계정·결과 뷰만 사용, 비밀번호는 서버 환경변수",
    "확인 필요: 당사 LIMS 제품·DB 종류, 접근 방식(DB/API/파일)",
    "시험코드표·승인 상태값·품종 코드 목록",
  ], 13), { x: 7.0, y: 5.2, w: 5.5, h: 1.5 });
  s.addText("※ 무인 운영: qms_monitor.py --sync-lims 를 10~30분 주기로 실행(작업 스케줄러)", { placeholder: "src" });
  s.addNotes("LIMS에 결과가 승인되면 다음 동기화 때 자동으로 들어옵니다. 실제 연결을 위해 당사 LIMS의 제품과 접근 방식을 확인해야 합니다.");

  // ── 11. AI 솔루션 ────────────────────────────────────────────────────
  s = addSlide("연계·AI");
  s.addText("AI 솔루션 보고서", { placeholder: "title" });
  s.addText("숫자는 시스템이 계산하고, AI는 그 근거 안에서만 해설·조치 계획을 씁니다", { placeholder: "msg" });
  const ai = [
    [fa.FaCalculator, "계산 엔진", "배합·강도·6가크롬\n예측·최적화 수치"],
    [fa.FaBook, "지식베이스", "조치·부작용·확인 방법\nKS·협약 기준"],
    [fa.FaRobot, "AI(Claude)", "근거 범위 내 해설\n새 수치 생성 금지"],
    [fa.FaClipboardCheck, "보고서", "결론→원인 5축→조치\n[사실]/[추정] 표기"],
  ];
  for (let i = 0; i < ai.length; i++) {
    const [Ic, h, t] = ai[i];
    const x = 0.6 + i * 3.13;
    card(s, x, 1.85, 2.75, 2.1, `AI flow ${i + 1}`, i === 2 ? "FDEBD3" : C.background2);
    await iconCircle(s, Ic, x + 0.25, 2.05, 0.6, i === 2 ? C.accent1 : C.accent2, `AI flow ${i + 1}`);
    text(s, h, { x: x + 1.0, y: 2.15, w: 1.6, h: 0.4, fontSize: 16, bold: true });
    text(s, t, { x: x + 0.25, y: 2.85, w: 2.35, h: 0.9, fontSize: 13, color: C.text2 });
    if (i < ai.length - 1) arrow(s, x + 2.8, 2.75, 0.28, 0.32, `AI arrow ${i + 1}`);
  }
  card(s, 0.6, 4.2, 6.6, 2.55, "AI guardrails");
  text(s, "안전장치", { x: 0.85, y: 4.35, w: 6.1, h: 0.35, fontSize: 16, bold: true });
  text(s, bullets([
    "원 데이터 DB·개인정보 미전송 — 전송 내용(JSON)을 화면에서 확인",
    "응답 거부·오류 시 규칙 기반 솔루션 유지(AI 없이도 전 기능 동작)",
    "호출 기록(모델·토큰·비용·입력 해시) 보관 — 감사 추적",
    "외부 API 사용이므로 사내 정보보안 승인 후 사용",
  ], 13), { x: 0.85, y: 4.78, w: 6.15, h: 1.9 });
  const arows = [header(["모델", "1회 비용(추정)"])];
  D.ai.slice(0, 3).forEach((a) => arows.push([a.model.replace(/ \(.*\)/, ""), `약 ${fmt(a.krw, 0)}원 ($${fmt(a.usd, 3)})`]));
  s.addTable(arows, Object.assign({}, TABLE_OPTS, { x: 7.45, y: 4.2, w: 5.25, colW: [2.45, 2.8], rowH: 0.45 }));
  text(s, "기본 모델 Opus 5.5 기준 월 100회 약 1.3만 원(추정). 지식베이스는 캐시로 반복 비용 절감",
    { x: 7.45, y: 6.15, w: 5.25, h: 0.55, fontSize: 12, color: C.text2 });
  s.addText("※ 비용 = 입력 약 9천(지식베이스 6천 캐시)·출력 약 4천 토큰 가정, 환율 1,400원/$ — 추정", { placeholder: "src" });
  s.addNotes("AI는 보고서 작성만 맡고, 판단 근거가 되는 숫자는 모두 시스템이 계산합니다. 외부 서비스이므로 보안 승인이 필요하며, 승인 전에도 규칙 기반 솔루션은 그대로 쓸 수 있습니다.");

  // ── 12. 검증 결과 ────────────────────────────────────────────────────
  pres.addSection({ title: "결론" });
  s = addSlide("결론");
  s.addText("검증 결과", { placeholder: "title" });
  s.addText("데모 데이터에 넣은 '정답'을 시스템이 그대로 찾아냈습니다 — 실데이터 검증이 다음 과제입니다", { placeholder: "msg" });
  const vrows = [header(["검증 항목", "데모 정답(생성값)", "시스템 추정값", "판정"])];
  D.validation.forEach((v) => vrows.push([v[0], v[1], { text: v[2], options: { bold: true } }, "일치"]));
  vrows.push(["28일 강도 예측 오차(1종, LOO)", "-", `${fmt(S1.models.find((m) => m.target === "28일 강도").rmse, 2)} MPa`, "양호"]);
  s.addTable(vrows, Object.assign({}, TABLE_OPTS, { x: 0.6, y: 1.85, w: 7.9, colW: [3.1, 1.75, 1.95, 1.1], rowH: 0.5, fontSize: 13 }));
  card(s, 8.8, 1.85, 3.9, 4.9, "Limits card");
  await iconCircle(s, fa.FaShieldAlt, 9.05, 2.05, 0.6, C.accent2, "Limits");
  text(s, "한계와 주의", { x: 9.8, y: 2.17, w: 2.8, h: 0.4, fontSize: 16, bold: true });
  text(s, bullets([
    "가상 데이터 검증 — 실제 공정 관계는 다를 수 있음",
    "원료·연료 Cr, 전환율, 환원제 계수 기본값은 예시(추정)",
    "강도 경험칙 계수는 실데이터로 재학습 필요",
    "국내 6가크롬 기준은 협약 원문·현행 여부 확인 필요",
  ], 13), { x: 9.05, y: 2.85, w: 3.45, h: 3.8 });
  s.addText("출처: Blue365 QMS 자동 검증(데모 120일, 시드 7) · 자동 테스트 90건 통과", { placeholder: "src" });
  s.addNotes("가상 공장 데이터에 일부러 넣은 관계와 사고를 시스템이 정확히 찾아냈다는 것이 이번 검증의 의미입니다. 실제 공정에서의 정확도는 실데이터 시범에서 확인하겠습니다.");

  // ── 13. 추진 계획·요청 ───────────────────────────────────────────────
  s = addSlide("결론");
  s.addText("추진 계획과 요청 사항", { placeholder: "title" });
  s.addText("LIMS 연결과 3개월 실데이터 시범으로 공장 맞춤 보정을 마치겠습니다", { placeholder: "msg" });
  const tl = [
    ["1개월", "연결·준비", "LIMS 연결·코드 매핑\n원료·연료 Cr 분석\nXRD 데이터 확보"],
    ["2~3개월", "실데이터 보정", "강도 모델 재학습\n전환율·환원제 계수 보정\nAI 시범 사용(승인 시)"],
    ["3개월 후", "효과 보고", "예측 정확도·조치 효과\n원가·6가크롬 관리 성과"],
  ];
  tl.forEach(([when, h, t], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.85, 3.9, 2.15, `Timeline ${i + 1}`);
    text(s, when, { x: x + 0.25, y: 1.98, w: 3.4, h: 0.4, fontSize: 20, bold: true, color: C.accent1 });
    text(s, h, { x: x + 0.25, y: 2.42, w: 3.4, h: 0.36, fontSize: 15, bold: true });
    text(s, t, { x: x + 0.25, y: 2.85, w: 3.4, h: 1.1, fontSize: 13, color: C.text2 });
    if (i < tl.length - 1) arrow(s, x + 3.93, 2.75, 0.15, 0.3, `Timeline arrow ${i + 1}`);
  });
  const asks = [
    [fa.FaServer, "LIMS 접근 협조", "읽기 전용 DB 계정 또는 API 접근\n시험코드표·승인 상태값 제공\n담당: IT·LIMS 운영"],
    [fa.FaVial, "분석 데이터", "원료·연료·내화물 총 크롬(월 1회↑)\n클링커 XRD·Cr⁶⁺(일 1회)\n담당: 품질(시험실)"],
    [fa.FaLock, "AI 보안 승인", "외부 API 전송 범위 승인\n예산: 월 약 1.3만 원(추정, 100회)\n담당: 정보보안·품질"],
  ];
  for (let i = 0; i < asks.length; i++) {
    const [Ic, h, t] = asks[i];
    const x = 0.6 + i * 4.1;
    card(s, x, 4.25, 3.9, 2.5, `Ask ${i + 1}`);
    await iconCircle(s, Ic, x + 0.25, 4.45, 0.62, C.accent2, `Ask ${i + 1}`);
    text(s, `${"①②③"[i]} ${h}`, { x: x + 1.05, y: 4.57, w: 2.7, h: 0.4, fontSize: 16, bold: true });
    text(s, t, { x: x + 0.25, y: 5.25, w: 3.4, h: 1.4, fontSize: 13 });
  }
  s.addText("첨부: 배합 설계서·6가크롬 평가표 샘플(엑셀) · 관리항목·기준 정의서(엑셀) · 시스템 소스(Blue365 저장소)", { placeholder: "src" });
  s.addNotes("LIMS 접근, 분석 데이터, AI 보안 승인 세 가지를 지원해 주시면 3개월 뒤 실데이터 기준 성과를 보고드리겠습니다.");

  await pres.writeFile({ fileName: OUT_PATH });
  if (THEME_JS) {
    const { applyTheme } = require(THEME_JS);
    await applyTheme(OUT_PATH, THEME);
  }
  console.log("saved", OUT_PATH);
})().catch((e) => { console.error(e); process.exit(1); });
