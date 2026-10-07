/**
 * 경영진 보고용 「시멘트 통합 품질관리 시스템 구축 계획」 PPT 생성 스크립트 (pptxgenjs).
 *
 * 준비:  npm install pptxgenjs react-icons react react-dom sharp
 * 실행:  node docs/src/build_plan_deck.js docs/src/deck_data.json <출력.pptx> [apply_theme.js 경로]
 *   deck_data.json : 시스템 검증 결과(시나리오별 진단, 모델 정확도, 차트 데이터) — QMS에서 추출
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
pres.title = "시멘트 통합 품질관리 시스템 구축 계획";
pres.subject = "QMS 1단계 구현 결과 및 추진 계획";
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

// 상태 칩: ● + 라벨 (색만으로 의미 전달 금지)
function statusChip(slide, x, y, label, dotScheme, w = 1.15) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.38, fill: { color: C.background1 },
    line: { color: "CFD8DC", width: 0.75 }, rectRadius: 0.19, objectName: "Status " + label });
  text(slide, [{ text: "● ", options: { color: dotScheme, bold: true } }, { text: label, options: { bold: true } }],
    { x, y, w, h: 0.38, fontSize: 13, align: "center", valign: "middle" });
}

function header(cells) {
  return cells.map((t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text1 } } }));
}

const TABLE_OPTS = { fontSize: 12, color: C.text1, border: { type: "solid", pt: 0.75, color: "CFD8DC" }, valign: "middle",
  margin: [0.04, 0.08, 0.04, 0.08] };

function addSlide(section) {
  return pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
}

(async () => {
  // ── 1. 표지 ──────────────────────────────────────────────────────────
  pres.addSection({ title: "도입" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "도입" });
  s.addText("시멘트 통합 품질관리 시스템 구축 계획", { placeholder: "title" });
  s.addText("모니터링 · 알림 · 원인 진단 · 솔루션을 하나로 — 1단계 구현 결과와 추진 계획", { placeholder: "subtitle" });
  s.addText("품질관리팀  ·  2026년 10월  ·  경영진 보고", { placeholder: "org" });
  const motif = [fa.FaChartLine, fa.FaBell, fa.FaStethoscope, fa.FaChartArea, fa.FaFileAlt];
  for (let i = 0; i < motif.length; i++) await iconCircle(s, motif[i], 0.8 + i * 0.95, 4.75, 0.7, C.accent1, `Motif ${i + 1}`);
  s.addNotes("시멘트 공정 전반의 품질 데이터를 한 곳에서 감시하고, 기준 이탈 시 자동 알림과 원인·대책까지 제시하는 시스템의 1단계 결과와 향후 계획을 보고드립니다.");

  // ── 2. 핵심 요약 ─────────────────────────────────────────────────────
  s = addSlide("도입");
  s.addText("핵심 요약", { placeholder: "title" });
  s.addText("1단계 시스템 구현을 마쳤으며, 실데이터 시범 운영 승인을 요청드립니다", { placeholder: "msg" });
  const nCases = D.cases.length;
  const nOk = D.cases.filter((c) => c.ok).length; // 1순위 진단이 주입 원인과 일치한 사례 수
  const stats = [
    [`${nOk} / ${nCases}`, "데모 이상 사례 원인 진단 일치", "가상 데이터 6개 시나리오 · 8개 알림 사례"],
    ["3·7일", "28일 강도 미달 조기 경보 시점", "28일 결과 전, 조기강도·분말도 기반 예측"],
    [`${D.n_items}개`, "자동 감시 관리항목", "생료 → 소성 → 클링커 → 분쇄 → 제품 · 시험조건"],
  ];
  stats.forEach(([v, l, sub], i) => {
    const y = 1.85 + i * 1.65;
    card(s, 0.6, y, 4.3, 1.45, `Stat ${i + 1}`);
    text(s, v, { x: 0.85, y: y + 0.18, w: 3.9, h: 0.65, fontSize: 36, bold: true });
    text(s, l, { x: 0.85, y: y + 0.82, w: 3.9, h: 0.3, fontSize: 14, bold: true });
    text(s, sub, { x: 0.85, y: y + 1.1, w: 3.9, h: 0.3, fontSize: 11, color: C.text2 });
  });
  const rows2 = [
    [fa.FaBullseye, "목적", "품질 데이터를 한곳에서 감시하고, 기준 이탈을 자동으로 알리며, 원인과 대책까지 제시"],
    [fa.FaCheckCircle, "1단계 결과", "웹 대시보드 10개 화면 · 3단계 판정(KS·사내·SPC) · 5축 원인 진단 · 28일 예측 · 보고서 자동 생성"],
    [fa.FaRoute, "다음 단계", "실데이터 2~3개월 시범 운영으로 관리기준·예측 모델을 공장에 맞게 보정"],
    [fa.FaHandshake, "요청 사항", "시범 운영 승인 · 데이터 연계 협조(IT·계장) · 공정별 담당자 지정"],
  ];
  for (let i = 0; i < rows2.length; i++) {
    const [Ic, h, t] = rows2[i];
    const y = 1.9 + i * 1.22;
    await iconCircle(s, Ic, 5.35, y, 0.62, C.accent2, `Summary ${h}`);
    text(s, h, { x: 6.2, y: y - 0.02, w: 6.5, h: 0.36, fontSize: 17, bold: true });
    text(s, t, { x: 6.2, y: y + 0.36, w: 6.5, h: 0.7, fontSize: 14, color: C.text1 });
  }
  s.addText("※ 수치는 데모(가상) 데이터 검증 결과 — 실데이터 성능은 2단계 시범 운영에서 확인", { placeholder: "src" });
  s.addNotes("핵심은 세 가지입니다. 첫째, 가상 공장 데이터에 넣은 이상 6종을 모두 감지하고 원인을 맞혔습니다. 둘째, 28일 강도를 3·7일 시점에 미리 예측합니다. 셋째, 58개 항목을 자동 감시합니다. 실데이터 검증은 다음 단계 과제입니다.");

  // ── 3. 추진 배경 ─────────────────────────────────────────────────────
  s = addSlide("도입");
  s.addText("추진 배경", { placeholder: "title" });
  s.addText("품질 이상을 '사후 확인'에서 '사전 감지·근거 기반 진단'으로 바꿔야 합니다", { placeholder: "msg" });
  const bg = [
    [fa.FaDatabase, "데이터가 흩어져 있음", "XRF·DCS·물성 시험 데이터가 시스템·엑셀별로 분산되어, 생료부터 제품까지 잇는 원인 분석이 어렵습니다."],
    [fa.FaClock, "28일 강도는 사후 확인", "결과가 생산 28일 뒤에 나와 이미 출하된 뒤 이상을 알게 됩니다. 조기 경보가 필요합니다."],
    [fa.FaUserTie, "대응이 경험에 의존", "원인 판단 근거와 조치 이력이 표준화되지 않아 담당자에 따라 대응 품질에 편차가 생깁니다."],
    [fa.FaFileAlt, "반복되는 수작업 보고", "보고서·회의 자료를 매번 수작업으로 집계하고 작성합니다."],
  ];
  for (let i = 0; i < bg.length; i++) {
    const [Ic, h, t] = bg[i];
    const x = 0.6 + (i % 2) * 6.15, y = 1.85 + Math.floor(i / 2) * 2.5;
    card(s, x, y, 5.95, 2.3, `Issue ${i + 1}`);
    await iconCircle(s, Ic, x + 0.3, y + 0.32, 0.72, C.accent1, `Issue ${i + 1}`);
    text(s, h, { x: x + 1.25, y: y + 0.35, w: 4.45, h: 0.42, fontSize: 19, bold: true });
    text(s, t, { x: x + 1.25, y: y + 0.88, w: 4.45, h: 1.25, fontSize: 14 });
  }
  s.addText("※ 일반적인 시멘트 공장 품질관리 과제(추정) — 당사 현황 진단 결과로 보완 필요", { placeholder: "src" });
  s.addNotes("네 가지는 시멘트 공장에서 흔한 과제를 정리한 것입니다. 당사 현황과 다른 부분은 보완하겠습니다.");

  // ── 4. 시스템 구성 ───────────────────────────────────────────────────
  pres.addSection({ title: "시스템" });
  s = addSlide("시스템");
  s.addText("시스템 구성", { placeholder: "title" });
  s.addText("흩어진 데이터를 모아 감시 → 알림 → 진단 → 보고까지 자동으로 연결합니다", { placeholder: "msg" });
  text(s, "입력 데이터", { x: 0.6, y: 1.8, w: 2.9, h: 0.35, fontSize: 15, bold: true });
  ["생료 XRF·잔사", "킬른 DCS 운전값", "클링커 XRF·f-CaO", "시멘트 밀·분말도", "물성·강도(LIMS)"].forEach((t, i) => {
    card(s, 0.6, 2.25 + i * 0.86, 2.9, 0.68, `Source ${i + 1}`);
    text(s, t, { x: 0.75, y: 2.25 + i * 0.86, w: 2.6, h: 0.68, fontSize: 14, valign: "middle" });
  });
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 3.62, y: 3.9, w: 0.5, h: 0.45, fill: { color: C.text2 }, line: { color: C.text2, width: 0 },
    objectName: "Arrow in" });
  card(s, 4.25, 1.8, 5.35, 4.95, "QMS core");
  text(s, "통합 품질관리 시스템(QMS)", { x: 4.5, y: 1.95, w: 4.9, h: 0.38, fontSize: 16, bold: true });
  const fns = [
    [fa.FaChartLine, "① 모니터링", "58개 항목 추세 · 공정별 상태판"],
    [fa.FaBell, "② 판정·알림", "KS · 사내기준 · SPC 3단계"],
    [fa.FaStethoscope, "③ 원인 진단", "5축 가설 + 데이터 근거 점수"],
    [fa.FaChartArea, "④ 조기 예측", "28일 강도 회귀 예측"],
    [fa.FaFileAlt, "⑤ 보고", "PPT · 엑셀 자동 생성"],
  ];
  for (let i = 0; i < fns.length; i++) {
    const [Ic, h, t] = fns[i];
    const y = 2.45 + i * 0.84;
    await iconCircle(s, Ic, 4.5, y, 0.56, C.accent2, `Function ${i + 1}`);
    text(s, h, { x: 5.2, y: y + 0.0, w: 4.2, h: 0.3, fontSize: 15, bold: true });
    text(s, t, { x: 5.2, y: y + 0.3, w: 4.2, h: 0.3, fontSize: 13, color: C.text2 });
  }
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 9.73, y: 3.9, w: 0.5, h: 0.45, fill: { color: C.text2 }, line: { color: C.text2, width: 0 },
    objectName: "Arrow out" });
  text(s, "활용", { x: 10.35, y: 1.8, w: 2.35, h: 0.35, fontSize: 15, bold: true });
  [["품질팀", "분석·판정"], ["생산팀", "원료·소성·분쇄"], ["설비팀", "점검·정비"], ["경영진", "현황·의사결정"]].forEach(([a, b], i) => {
    card(s, 10.35, 2.25 + i * 1.08, 2.35, 0.88, `User ${i + 1}`);
    text(s, [{ text: a, options: { bold: true, breakLine: true, fontSize: 15 } }, { text: b, options: { fontSize: 12, color: C.text2 } }],
      { x: 10.5, y: 2.25 + i * 1.08, w: 2.1, h: 0.88, valign: "middle" });
  });
  s.addText("알림 채널: 대시보드 · 이메일 · 메신저(웹훅) / 실행 환경: 사내 PC·서버(Python·Streamlit 오픈소스)", { placeholder: "src" });
  s.addNotes("왼쪽의 공정 데이터를 모아, 가운데 다섯 기능이 순서대로 처리하고, 오른쪽 사용자에게 필요한 형태로 전달합니다.");

  // ── 5. 3단계 판정 기준 ───────────────────────────────────────────────
  s = addSlide("시스템");
  s.addText("3단계 판정 기준과 알림", { placeholder: "title" });
  s.addText("규격을 벗어나기 전에 이상 징후를 잡도록 세 단계로 판정합니다", { placeholder: "msg" });
  const tiers = [
    ["위험", C.accent6, "KS L 5201 규격 이탈", "예) 시멘트 SO₃ 3.5% 초과(1종), 28일 강도 42.5 MPa 미만", "즉시 출하 판정 · 공장장 보고"],
    ["경고", C.accent4, "사내 관리기준 이탈", "예) f-CaO 1.8% 초과, 분말도 3,250 미만, 양생수 온도 이탈", "당일 원인 조사"],
    ["주의", C.accent5, "SPC 판정규칙 위반(규격 이내)", "예) 생료 LSF 8시간 평균이 9회 연속 중심선 위(평균 이동)", "3일 내 점검"],
  ];
  tiers.forEach(([lab, col, h, ex, act], i) => {
    const y = 1.85 + i * 1.65;
    card(s, 0.6, y, 7.75, 1.45, `Tier ${lab}`);
    statusChip(s, 0.85, y + 0.22, lab, col);
    text(s, h, { x: 2.25, y: y + 0.2, w: 5.9, h: 0.4, fontSize: 18, bold: true });
    text(s, ex, { x: 2.25, y: y + 0.65, w: 5.9, h: 0.35, fontSize: 13, color: C.text2 });
    text(s, "→ " + act, { x: 2.25, y: y + 1.0, w: 5.9, h: 0.35, fontSize: 14, bold: true, color: C.text1 });
  });
  card(s, 8.65, 1.85, 4.05, 4.95, "Fatigue card");
  text(s, "알림 피로도 관리", { x: 8.9, y: 2.05, w: 3.6, h: 0.4, fontSize: 17, bold: true });
  text(s, bullets(["이어지는 위반점은 1건의 이벤트로 묶음", "규격 이탈과 겹친 SPC 패턴은 '동반 패턴'으로 기록",
    "1~2시간 간격 데이터는 8시간 평균으로 SPC 판정", "예측값 경보는 최고 '경고'로 제한"], 14), { x: 8.9, y: 2.55, w: 3.6, h: 2.6 });
  text(s, [{ text: "데모 4개월 결과", options: { bold: true, breakLine: true, fontSize: 13 } },
    { text: `위험 ${D.sev["위험"] || 0} · 경고 ${D.sev["경고"] || 0} · 주의 ${D.sev["주의"] || 0}건 (하루 약 1건)`, options: { fontSize: 13 } }],
    { x: 8.9, y: 5.65, w: 3.6, h: 0.9 });
  s.addText("근거: KS L 5201 포틀랜드 시멘트(e나라표준인증·한국시멘트협회 요약) · 사내 기준 초기값은 경험칙(추정) → 정의서로 확정 예정", { placeholder: "src" });
  s.addNotes("빨강·주황·노랑 색과 함께 '위험·경고·주의' 글자를 항상 같이 표시합니다. 경고 이상만 메일·메신저로 보내 알림 피로를 줄였습니다.");

  // ── 6. 원인 진단 방식 ────────────────────────────────────────────────
  s = addSlide("시스템");
  s.addText("원인 진단 방식", { placeholder: "title" });
  s.addText("모든 이상을 같은 5단계 틀로 분석하고, 데이터 근거로 원인 순위를 정합니다", { placeholder: "msg" });
  const steps = [["현상 정의·정량화", "기간 · 이탈 점수 · 기준 대비 편차(σ)"], ["원인 가설 우선순위", "화학 · 원료 · 공정 · 설비 · 시험오차 5축"],
    ["확인 방법", "검증할 데이터 · 시험 항목 제시"], ["단기 조치 vs 근본 대책", "확산 방지와 재발 방지를 구분"],
    ["KS · 관리기준 평가", "규격 적합 여부 · 여유 · 출하 판단"]];
  steps.forEach(([h, t], i) => {
    const y = 1.88 + i * 0.98;
    s.addShape(pres.shapes.OVAL, { x: 0.6, y, w: 0.62, h: 0.62, fill: { color: C.accent1 }, line: { color: C.accent1, width: 0 },
      objectName: `Step ${i + 1}` });
    text(s, String(i + 1), { x: 0.6, y, w: 0.62, h: 0.62, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle" });
    text(s, h, { x: 1.42, y: y - 0.02, w: 4.8, h: 0.35, fontSize: 17, bold: true });
    text(s, t, { x: 1.42, y: y + 0.33, w: 4.8, h: 0.3, fontSize: 13, color: C.text2 });
  });
  card(s, 6.6, 1.85, 6.1, 4.95, "Scoring card");
  text(s, "근거 점수 산출", { x: 6.85, y: 2.02, w: 5.6, h: 0.38, fontSize: 17, bold: true });
  text(s, "관련 데이터의 변화(이벤트 구간 vs 직전 14일)를 효과크기(σ)로 계산 → 근거 점수 0~100",
    { x: 6.85, y: 2.45, w: 5.6, h: 0.65, fontSize: 14 });
  const axes = [[fa.FaFlask, "화학"], [fa.FaMountain, "원료"], [fa.FaFire, "공정"], [fa.FaCogs, "설비"], [fa.FaVial, "시험오차"]];
  for (let i = 0; i < axes.length; i++) {
    const x = 6.95 + i * 1.12;
    await iconCircle(s, axes[i][0], x, 3.25, 0.62, C.accent2, `Axis ${axes[i][1]}`);
    text(s, axes[i][1], { x: x - 0.25, y: 3.92, w: 1.12, h: 0.3, fontSize: 13, align: "center", bold: true });
  }
  text(s, "판정 표기 — 사실과 추정을 구분", { x: 6.85, y: 4.45, w: 5.6, h: 0.35, fontSize: 15, bold: true });
  text(s, bullets(["데이터 지지: 예상 변화가 측정 데이터로 확인됨(사실)", "데이터 없음: 측정값이 없어 경험칙으로 제시(추정)",
    "반증: 예상 변화가 데이터에 나타나지 않음"], 13), { x: 6.85, y: 4.85, w: 5.6, h: 1.2 });
  text(s, `지식베이스: ${D.n_kb}개 현상 · ${D.n_hyp}개 원인 가설(확인 방법·조치 포함)`,
    { x: 6.85, y: 6.15, w: 5.6, h: 0.4, fontSize: 13, color: C.text2 });
  s.addText("※ 지식베이스의 정량 경험칙(예: 분말도 100 cm²/g 당 강도 변화)은 공장 데이터로 검증 후 보정", { placeholder: "src" });
  s.addNotes("가설마다 어떤 데이터가 어느 방향으로 변해야 하는지 정의해 두고, 실제 데이터를 비교해 점수를 매깁니다. 측정 데이터가 없는 설비 원인은 '추정'으로 표시합니다.");

  // ── 7. 진단 예시 ─────────────────────────────────────────────────────
  s = addSlide("시스템");
  s.addText("진단 예시: 28일 강도 저하", { placeholder: "title" });
  s.addText("데이터가 '소성 부족'을 1순위 원인으로 특정했습니다 (데모 시나리오 S1)", { placeholder: "msg" });
  const S1 = D.s1;
  card(s, 0.6, 1.85, 4.0, 4.95, "Phenomenon card");
  text(s, "① 현상", { x: 0.85, y: 2.02, w: 3.5, h: 0.38, fontSize: 17, bold: true });
  text(s, bullets([`28일 강도(1종) ${S1.n}로트 연속 중심선 아래(평균 이동)`, `평균 ${S1.mean} MPa — 직전 ${S1.base} 대비 ${S1.delta} MPa (${S1.eff}σ)`,
    `최소 ${S1.worst} MPa`], 14), { x: 0.85, y: 2.48, w: 3.5, h: 1.9 });
  text(s, "⑤ KS·사내기준 평가", { x: 0.85, y: 4.45, w: 3.5, h: 0.38, fontSize: 17, bold: true });
  text(s, bullets([`KS 42.5 MPa: ${S1.ks}`, `사내 48 MPa: ${S1.sp} → 규격 이탈 전 조기 대응 단계`], 14), { x: 0.85, y: 4.9, w: 3.5, h: 1.6 });
  const vfill = { "데이터 지지": "DCEFD8", "부분 확인": "EAF5E6" };
  const trows = [header(["순위", "축", "원인 가설", "판정", "핵심 데이터 근거"])];
  S1.rows.slice(0, 5).forEach((r, i) => {
    const evShort = r.ev.split(";")[0].replace("클링커 ", "").replace("(파이로미터)", "");
    trows.push([String(i + 1), r.axis, r.title.replace(/\(.*\)/, ""),
      { text: r.verdict, options: { fill: { color: vfill[r.verdict] || "FFFFFF" } } }, r.short || evShort]);
  });
  s.addTable(trows, Object.assign({}, TABLE_OPTS, { x: 4.9, y: 1.85, w: 7.8, colW: [0.55, 0.85, 2.15, 1.3, 2.95], rowH: 0.46,
    fontSize: 12 }));
  card(s, 4.9, 5.0, 3.8, 1.8, "Short-term card");
  text(s, "④ 단기 조치", { x: 5.1, y: 5.1, w: 3.4, h: 0.35, fontSize: 15, bold: true });
  text(s, bullets(S1.st.slice(0, 2).map((t) => t.replace(/\(.*?\)/g, "")), 13), { x: 5.1, y: 5.5, w: 3.45, h: 1.25 });
  card(s, 8.9, 5.0, 3.8, 1.8, "Root-cause card");
  text(s, "④ 근본 대책", { x: 9.1, y: 5.1, w: 3.4, h: 0.35, fontSize: 15, bold: true });
  text(s, bullets(S1.rc.slice(0, 2), 13), { x: 9.1, y: 5.5, w: 3.45, h: 1.25 });
  s.addText("데모 시나리오 S1(석탄 발열량 저하를 주입) 결과 · 근거 수치는 시스템 자동 산출값", { placeholder: "src" });
  s.addNotes("2차 공기 온도 저하(냉각기 가설)는 소성 부족과 함께 나타나는 동반 증상일 수 있어, 현장 확인으로 구분합니다. 이처럼 데이터가 지지하는 가설과 아닌 가설을 나눠 확인 순서를 제시합니다.");

  // ── 8. 28일 강도 조기 예측 ───────────────────────────────────────────
  s = addSlide("시스템");
  s.addText("28일 강도 조기 예측", { placeholder: "title" });
  s.addText("28일 결과를 기다리지 않고 3·7일 시점에 미달 위험을 미리 경보합니다", { placeholder: "msg" });
  const cats = D.chart.cats;
  const flat = (v) => cats.map(() => v);
  const common = { lineSize: 2, lineDataSymbolSize: 6 };
  s.addChart([
    { type: pres.charts.LINE, data: [{ name: "28일 실측", labels: cats, values: D.chart.act }],
      options: Object.assign({ chartColors: [HEX.accent2], lineDataSymbol: "circle" }, common) },
    { type: pres.charts.LINE, data: [{ name: "28일 예측(미도래)", labels: cats, values: D.chart.pred }],
      options: Object.assign({ chartColors: ["6DA7EC"], lineDataSymbol: "circle", lineDash: "dash" }, common) },
    { type: pres.charts.LINE, data: [{ name: "사내 하한 48", labels: cats, values: flat(48) }],
      options: { chartColors: [HEX.accent4], lineDataSymbol: "none", lineSize: 1.25, lineDash: "dash" } },
    { type: pres.charts.LINE, data: [{ name: "KS 하한 42.5", labels: cats, values: flat(42.5) }],
      options: { chartColors: [HEX.accent6], lineDataSymbol: "none", lineSize: 1.25 } },
  ], { x: 0.6, y: 1.8, w: 7.9, h: 5.0, showLegend: true, legendPos: "b", legendFontSize: 11, legendFontFace: "+mn-lt",
    legendColor: HEX.dk2, valAxisMinVal: 40, valAxisMaxVal: 58, valAxisMajorUnit: 2, valAxisLabelFontSize: 11,
    catAxisLabelFontSize: 10, valAxisLabelColor: HEX.dk2, catAxisLabelColor: HEX.dk2, valAxisLabelFontFace: "+mn-lt",
    catAxisLabelFontFace: "+mn-lt", catAxisLabelFrequency: 5, valGridLine: { color: "E3E7EA", size: 0.75 },
    catGridLine: { style: "none" }, displayBlanksAs: "gap", showValAxisTitle: true, valAxisTitle: "MPa",
    valAxisTitleFontSize: 11, valAxisTitleColor: HEX.dk2, valAxisTitleFontFace: "+mn-lt", objectName: "Strength chart" });
  card(s, 8.8, 1.85, 3.9, 2.55, "Model card");
  text(s, "예측 모델 정확도(1종)", { x: 9.0, y: 1.98, w: 3.5, h: 0.35, fontSize: 15, bold: true });
  s.addTable([header(["입력", "R²", "오차(RMSE)"]),
    ["7일 강도", D.m7.r2.toFixed(2), `${D.m7.rmse.toFixed(2)} MPa`], ["3일 강도+화학", D.m3.r2.toFixed(2), `${D.m3.rmse.toFixed(2)} MPa`],
    ["화학·분말도", D.mc.r2.toFixed(2), `${D.mc.rmse.toFixed(2)} MPa`]],
    Object.assign({}, TABLE_OPTS, { x: 9.0, y: 2.42, w: 3.5, colW: [1.6, 0.7, 1.2], rowH: 0.42, fontSize: 12 }));
  card(s, 8.8, 4.6, 3.9, 2.2, "Callout card");
  text(s, [{ text: "조기 경보 사례(S3)", options: { bold: true, breakLine: true, fontSize: 15 } },
    { text: "분말도가 떨어진 4개 로트를 3일 강도 시점에 '46.2~46.7 MPa(사내 48 미달)'로 경보 → 28일 결과 전에 조치 가능",
      options: { fontSize: 13 } }], { x: 9.0, y: 4.75, w: 3.5, h: 1.95 });
  s.addText(`데모 데이터 학습 결과(약 ${D.m7.n}로트, 오차=LOO 기준) — 예측값은 추정치이며 실측으로 확정. 실데이터로 재학습 필요`, { placeholder: "src" });
  s.addNotes("오차가 약 1.1~1.2 MPa이므로 예측값 ±2.3 MPa(약 95%) 범위로 봐야 합니다. 실데이터가 쌓이면 자동 재학습합니다.");

  // ── 9. 구현 화면 ─────────────────────────────────────────────────────
  pres.addSection({ title: "검증" });
  s = addSlide("검증");
  s.addText("1단계 구현 결과", { placeholder: "title" });
  s.addText("웹 대시보드 10개 화면을 구현했습니다 — 사내 PC에서 바로 실행", { placeholder: "msg" });
  const shotW = 5.95, shotH = shotW * 1111 / 1600;
  s.addImage({ path: path.join(IMG, "screen_overview.jpg"), x: 0.6, y: 1.8, w: shotW, h: shotH, objectName: "Screen overview" });
  s.addImage({ path: path.join(IMG, "screen_diagnosis.jpg"), x: 6.75, y: 1.8, w: shotW, h: shotH, objectName: "Screen diagnosis" });
  text(s, [{ text: "종합 현황  ", options: { bold: true } }, { text: "위험·경고·주의 건수, 공정별 상태 신호등, 28일 강도 추이" }],
    { x: 0.6, y: 1.9 + shotH, w: shotW, h: 0.5, fontSize: 13 });
  text(s, [{ text: "원인 진단  ", options: { bold: true } }, { text: "5축 원인 순위·근거 점수, 조치, KS 평가, PPT 자동 생성" }],
    { x: 6.75, y: 1.9 + shotH, w: shotW, h: 0.5, fontSize: 13 });
  s.addText("화면: 종합 현황 · 공정 모니터링 · SPC·공정능력 · 알림 센터 · 원인 진단 · 28일 강도 예측 · 화학 계산기 · 보고서 · 데이터 관리 · 기준·알림 설정", { placeholder: "src" });
  s.addNotes("실제 구현 화면입니다(데모 데이터). 엑셀 템플릿으로 실데이터를 올리면 바로 같은 화면으로 볼 수 있습니다.");

  // ── 10. 검증 결과 ────────────────────────────────────────────────────
  s = addSlide("검증");
  s.addText("검증 결과 (데모 데이터)", { placeholder: "title" });
  s.addText("이상 시나리오 6종을 모두 감지했고, 1순위 진단이 주입한 원인과 일치했습니다", { placeholder: "msg" });
  const sevCol = { "위험": HEX.accent6, "경고": HEX.accent4, "주의": HEX.accent5 };
  const vrows = [header(["시나리오", "주입한 원인", "시스템 알림(심각도)", "1순위 진단", "판정"])];
  const shortEv = (t) => t.replace("[1종] ", "").replace("클링커 자유석회(f-CaO)", "f-CaO").replace("사내 관리기준", "사내기준")
    .replace("중심선 한쪽 연속 9점(평균 이동)", "9연속 평균 이동").replace("28일 강도(예측)", "28일 예측")
    .replace("오토클레이브 팽창도", "오토클레이브 팽창").replace("(예측)", "").replace("압축강도", "강도");
  const shortTop = (t) => t.replace(/\(.*?\)/g, "").replace("28일 강도 시험 조건 이탈·시험 오차", "시험 조건 이탈")
    .replace("분말도 저하·입도분포 조대화", "분말도 저하");
  D.cases.forEach((c) => {
    vrows.push([c.code, c.injected, { text: [{ text: "● ", options: { color: sevCol[c.severity], bold: true } },
      { text: `${c.severity}  ${shortEv(c.event)}` }] },
      shortTop(c.top), { text: c.verdict, options: { fill: { color: vfill[c.verdict] || "ECEFF1" } } }]);
  });
  s.addTable(vrows, Object.assign({}, TABLE_OPTS, { x: 0.6, y: 1.8, w: 12.1, colW: [0.95, 2.75, 3.85, 2.75, 1.8], rowH: 0.42,
    fontSize: 12 }));
  card(s, 0.6, 6.0, 5.95, 0.82, "Note S4");
  text(s, "S4(석고 공급기 이상): 측정 데이터가 없는 설비 원인 → '데이터 없음(추정)'으로 표시하고 현장 확인을 지시",
    { x: 0.8, y: 6.04, w: 5.6, h: 0.74, fontSize: 12, valign: "middle" });
  card(s, 6.75, 6.0, 5.95, 0.82, "Note tests");
  text(s, "자동 테스트 55건 통과 — 계산식(Bogue·LSF), 판정규칙, 알림 묶음, 원인 진단, 예측, 보고서, 10개 화면",
    { x: 6.95, y: 6.04, w: 5.6, h: 0.74, fontSize: 12, valign: "middle" });
  s.addText("가상 공장 데이터(120일, 생료·클링커·시멘트 2시간, 킬른 1시간, 물성 1일) 기준 — 실제 성능은 2단계 시범 운영에서 검증", { placeholder: "src" });
  s.addNotes("가상 데이터라는 한계가 있지만, 원인이 다른 여섯 가지 이상을 서로 구분해 맞혔다는 점이 의미가 있습니다. 데이터가 없는 원인은 추정으로 정직하게 표시합니다.");

  // ── 11. 로드맵 ───────────────────────────────────────────────────────
  pres.addSection({ title: "추진 계획" });
  s = addSlide("추진 계획");
  s.addText("단계별 추진 계획", { placeholder: "title" });
  s.addText("2단계 실데이터 시범 운영(2~3개월)으로 기준과 모델을 공장에 맞춥니다", { placeholder: "msg" });
  const phases = [
    ["1단계 MVP", "2026년 10월", C.accent3, "완료", ["모니터링·알림·진단·예측·보고", "엑셀 업로드·데모 데이터", "관리기준 정의서·계획서"]],
    ["2단계 실데이터 시범", "2~3개월(추정)", C.accent2, "다음", ["실데이터 3개월 적재", "사내 기준·SPC 기준기간 확정", "예측 모델 재학습", "메일·메신저 알림 연결", "LIMS·DCS 파일 자동 반영"]],
    ["3단계 고도화", "3~6개월(추정)", C.text2, "계획", ["조치 이력 → 지식베이스 학습", "입도분포·XRD 반영 예측", "원료 조합 최적화", "AI 보조 분석(자연어 질의)"]],
    ["4단계 확산", "추후", C.text2, "계획", ["DB·OPC-UA 실시간 연계", "모바일 알림", "타 공정·타 공장 확산"]],
  ];
  phases.forEach(([h, per, col, chip, items], i) => {
    const x = 0.6 + i * 3.1;
    card(s, x, 1.85, 2.85, 4.95, `Phase ${i + 1}`);
    statusChip(s, x + 0.2, 2.05, chip, col, 1.0);
    text(s, h, { x: x + 0.2, y: 2.6, w: 2.5, h: 0.45, fontSize: 17, bold: true });
    text(s, per, { x: x + 0.2, y: 3.05, w: 2.5, h: 0.35, fontSize: 14, color: C.accent1, bold: true });
    text(s, bullets(items, 13), { x: x + 0.2, y: 3.55, w: 2.5, h: 3.1 });
    if (i < phases.length - 1) {
      s.addShape(pres.shapes.RIGHT_ARROW, { x: x + 2.88, y: 4.1, w: 0.19, h: 0.3, fill: { color: C.text2 }, line: { color: C.text2, width: 0 },
        objectName: `Phase arrow ${i + 1}` });
    }
  });
  s.addText("기간은 일반적인 시범 구축 경험에 따른 추정치 — 데이터 연계 범위에 따라 달라질 수 있음", { placeholder: "src" });
  s.addNotes("2단계가 핵심입니다. 실데이터로 사내 기준과 예측 모델을 보정해야 실제 운영 신뢰성을 확보할 수 있습니다.");

  // ── 12. 기대 효과 ────────────────────────────────────────────────────
  s = addSlide("추진 계획");
  s.addText("기대 효과", { placeholder: "title" });
  s.addText("이상을 더 일찍 알고, 같은 기준으로 대응하며, 근거와 기록이 남습니다", { placeholder: "msg" });
  const erows = [header(["구분", "현재(일반적 현황, 추정)", "도입 후"]),
    ["이상 인지 시점", "28일 강도 결과 확인 후", "3·7일 강도 시점 예측 경보 + 공정 지표 상시 감시"],
    ["원인 분석", "담당자 경험 중심", "5축 가설 + 데이터 근거 점수 + 확인 방법 제시"],
    ["판정 기준", "문서·개인 파일에 분산", "KS + 사내 기준을 시스템에서 단일 관리"],
    ["보고", "수작업 집계·작성", "버튼 한 번으로 PPT·엑셀 생성"],
    ["지식 축적", "개인 노하우", "지식베이스·조치 이력으로 축적"]];
  s.addTable(erows, Object.assign({}, TABLE_OPTS, { x: 0.6, y: 1.85, w: 7.9, colW: [1.7, 2.6, 3.6], rowH: 0.62, fontSize: 13 }));
  card(s, 8.8, 1.85, 3.9, 4.95, "Measurement card");
  await iconCircle(s, fa.FaChartBar, 9.05, 2.05, 0.62, C.accent2, "Measure");
  text(s, "정량 효과는 시범 운영으로 측정", { x: 9.05, y: 2.8, w: 3.45, h: 0.75, fontSize: 16, bold: true });
  text(s, "품질 클레임 감소율·시간 절감 같은 수치는 지금은 근거 데이터가 없어 제시하지 않습니다. 2단계에서 아래 지표를 실측해 보고드리겠습니다.",
    { x: 9.05, y: 3.6, w: 3.45, h: 1.45, fontSize: 13 });
  text(s, bullets(["조기 경보 건수·리드타임", "이상 대응 소요 시간", "보고서 작성 시간"], 13), { x: 9.05, y: 5.15, w: 3.45, h: 1.5 });
  s.addText("※ '현재' 열은 일반적인 공장 현황(추정) — 당사 현황 확인 후 보완", { placeholder: "src" });
  s.addNotes("근거 없는 숫자를 드리지 않기 위해 정량 효과는 시범 운영에서 측정하겠습니다.");

  // ── 13. 결정 요청 ────────────────────────────────────────────────────
  s = addSlide("추진 계획");
  s.addText("결정 요청 사항", { placeholder: "title" });
  s.addText("시범 운영 착수를 위해 세 가지를 요청드립니다", { placeholder: "msg" });
  const asks = [
    [fa.FaCheckCircle, "시범 운영 승인", "2단계 실데이터 시범 운영 — 기간 2~3개월(추정), 대상 1종·3종 전 공정"],
    [fa.FaServer, "데이터 연계 협조", "LIMS·DCS 데이터 내보내기, 사내 메일(SMTP)·메신저 연결 — IT·계장 담당"],
    [fa.FaUsers, "담당자 지정·기준 확정", "원료·소성·분쇄·설비 담당 지정, 정의서 기반 사내 관리기준 확정 회의"],
  ];
  for (let i = 0; i < asks.length; i++) {
    const [Ic, h, t] = asks[i];
    const x = 0.6 + i * 4.1;
    card(s, x, 1.85, 3.9, 2.9, `Ask ${i + 1}`);
    await iconCircle(s, Ic, x + 0.3, 2.1, 0.7, C.accent1, `Ask ${i + 1}`);
    text(s, `${"①②③"[i]} ${h}`, { x: x + 0.3, y: 2.95, w: 3.3, h: 0.45, fontSize: 18, bold: true });
    text(s, t, { x: x + 0.3, y: 3.45, w: 3.3, h: 1.2, fontSize: 14 });
  }
  card(s, 0.6, 4.95, 6.0, 1.85, "Resources card");
  text(s, "소요 자원(추정)", { x: 0.85, y: 5.05, w: 5.5, h: 0.35, fontSize: 15, bold: true });
  text(s, bullets(["소프트웨어 비용 0원(오픈소스 Python·Streamlit)", "사내 PC 또는 서버 1대", "품질 담당 1명 주관 + 관련 부서 협조"], 13),
    { x: 0.85, y: 5.45, w: 5.5, h: 1.3 });
  card(s, 6.8, 4.95, 5.9, 1.85, "Risk card");
  text(s, "리스크와 대응", { x: 7.05, y: 5.05, w: 5.4, h: 0.35, fontSize: 15, bold: true });
  text(s, bullets(["데이터 품질 → 업로드 검증·이상값 표시", "과다 알림 → 3단계 등급·이벤트 묶음", "기준 미확정 → 정의서로 확정 후 반영"], 13),
    { x: 7.05, y: 5.45, w: 5.4, h: 1.3 });
  s.addText("첨부: QMS 관리항목·기준 정의서(엑셀) · 시스템 소스(Blue365 저장소)", { placeholder: "src" });
  s.addNotes("승인해 주시면 다음 달부터 실데이터 적재를 시작하고, 3개월 뒤 정량 효과와 함께 결과를 보고드리겠습니다.");

  await pres.writeFile({ fileName: OUT_PATH });
  if (THEME_JS) {
    const { applyTheme } = require(THEME_JS);
    await applyTheme(OUT_PATH, THEME);
  }
  console.log("saved", OUT_PATH);
})().catch((e) => { console.error(e); process.exit(1); });
