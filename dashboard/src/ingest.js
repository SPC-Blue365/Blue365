/* Blue365 QMS 대시보드 — 엑셀·CSV 구조 자동 분석 엔진 (브라우저·노드 공용, 외부 의존 없음)

   입력: 2차원 배열(aoa, 시트 내용). 출력: 구조 판별 결과(analysis) → extract() 로 공정별 표(tables) 추출.
   하는 일
     1) 제목 줄·머리글(한 줄/두 줄)·단위 줄 탐지, 병합 셀(위쪽 그룹 머리글) 채우기
     2) 가로형(시료 1행·항목 열)과 긴 형식(시험 1건=1행: 일시·지점·시험항목·결과값) 자동 판별
     3) 항목 인식: 열 이름(별칭·한글/영문·첨자) → 후보, 후보가 여럿이면 문맥(생료/클링커/시멘트)과 값의 범위로 확정
     4) 열 이름을 모르면 값의 범위로 추정(확신이 낮으면 '확인 필요'로 표시 — 조용히 틀리게 넣지 않는다)
     5) 일시·시간 열 분리, 엑셀 날짜 일련번호, 8자리 날짜, 오전/오후, '<0.1' 같은 부등호 값 처리 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.INGEST = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ── 문자 정규화 ──────────────────────────────────────────────
  const SUPER = { "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9" };
  function nkey(s) {
    if (s == null) return "";
    let t = String(s).toLowerCase();
    t = t.replace(/[₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹]/g, (c) => SUPER[c]).replace(/[μµ]/g, "u").replace(/[⁺⁻]/g, "");
    return t.replace(/[^0-9a-zㄱ-ㆎ가-힣]/g, "");
  }
  const isBlank = (v) => v == null || (typeof v === "string" && v.trim() === "");
  const isNumber = (v) => typeof v === "number" && isFinite(v);

  // ── 값 해석 ──────────────────────────────────────────────────
  // 숫자: '1,234'·'12,5'·'<0.1'·'N.D.' 처리. 반환 {v:number|null, censored:boolean}
  function parseNum(x) {
    if (isNumber(x)) return { v: x, censored: false };
    if (x == null) return { v: null, censored: false };
    let s = String(x).trim();
    if (!s || /^(n\.?d\.?|nd|n\/a|na|-+|—|불검출|미검출|해당없음|null)$/i.test(s)) return { v: null, censored: false };
    const censored = /^[<>≤≥]/.test(s);
    s = s.replace(/^[<>≤≥]\s*/, "").replace(/\s*(%|mpa|mg\/kg|ppm|cm2\/g|g\/l|분|min|℃|°c)$/i, "");
    if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) s = s.replace(/,/g, "");
    else if (/^\d+,\d{1,2}$/.test(s)) s = s.replace(",", ".");
    if (!/^[-+]?\d*\.?\d+(e[-+]?\d+)?$/i.test(s)) return { v: null, censored: false };
    const v = parseFloat(s);
    return isFinite(v) ? { v, censored } : { v: null, censored: false };
  }
  const pad = (n) => String(n).padStart(2, "0");
  function iso(y, mo, d, h, mi) {
    if (mo < 1 || mo > 12 || d < 1 || d > 31 || y < 1990 || y > 2100) return null;
    return `${y}-${pad(mo)}-${pad(d)}T${pad(h || 0)}:${pad(mi || 0)}`;
  }
  function timeOf(v) {          // 시간 열 → [h, m] | null
    if (isBlank(v)) return null;
    if (isNumber(v)) { if (v >= 0 && v < 1) { const m = Math.round(v * 1440); return [Math.floor(m / 60) % 24, m % 60]; } return null; }
    const s = String(v).trim();
    let m = s.match(/(오전|오후|am|pm)?\s*(\d{1,2})\s*[:시]\s*(\d{1,2})?/i);
    if (!m) return null;
    let h = +m[2]; const mi = m[3] ? +m[3] : 0;
    if (m[1] && /오후|pm/i.test(m[1]) && h < 12) h += 12;
    if (m[1] && /오전|am/i.test(m[1]) && h === 12) h = 0;
    return h < 24 && mi < 60 ? [h, mi] : null;
  }
  // 날짜(+시각) → 'YYYY-MM-DDTHH:MM' | null  (시간대 변환 없이 표기 그대로)
  function parseDate(v, timeV) {
    let out = null, hasTime = false;
    if (v instanceof Date && !isNaN(v)) { out = iso(v.getFullYear(), v.getMonth() + 1, v.getDate(), v.getHours(), v.getMinutes()); hasTime = v.getHours() + v.getMinutes() > 0; }
    else if (isNumber(v)) {
      if (v > 20000 && v < 80000) {                          // 엑셀 일련번호(1900 체계)
        const ms = Math.round((v - 25569) * 86400 * 1000), d = new Date(ms);
        out = iso(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes()); hasTime = v % 1 !== 0;
      } else if (Number.isInteger(v) && v >= 19900101 && v <= 21001231) {
        out = iso(Math.floor(v / 10000), Math.floor(v / 100) % 100, v % 100, 0, 0);
      }
    } else if (typeof v === "string") {
      const s = v.trim();
      let m = s.match(/^(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})(?:\s*일)?(?:[T\s]+(오전|오후|am|pm)?\s*(\d{1,2})\s*[:시]\s*(\d{1,2})?)?/i)
        || s.match(/^(\d{4})(\d{2})(\d{2})(?:\s*(\d{2}):?(\d{2}))?$/);
      if (m) {
        if (m[4] && /^\d+$/.test(m[4])) { out = iso(+m[1], +m[2], +m[3], +m[4], +m[5]); hasTime = true; }
        else {
          let h = m[5] ? +m[5] : 0; const mi = m[6] ? +m[6] : 0;
          if (m[4] && /오후|pm/i.test(m[4]) && h < 12) h += 12;
          if (m[4] && /오전|am/i.test(m[4]) && h === 12) h = 0;
          out = iso(+m[1], +m[2], +m[3], h, mi); hasTime = !!m[5];
        }
      } else if ((m = s.match(/^(\d{2})[-./](\d{1,2})[-./](\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$/))) {
        out = iso(2000 + +m[1], +m[2], +m[3], m[4] ? +m[4] : 0, m[5] ? +m[5] : 0); hasTime = !!m[4];
      }
    }
    if (out && !hasTime && timeV != null) { const t = timeOf(timeV); if (t) out = out.slice(0, 11) + pad(t[0]) + ":" + pad(t[1]); }
    return out;
  }

  // ── 단어 사전 ────────────────────────────────────────────────
  const W = (a) => new Set(a.map(nkey));
  const TS_HEAD = W(["timestamp", "일시", "시료일시", "채취일시", "시료채취일시", "시험일시", "분석일시", "측정일시", "시료채취일", "채취일", "시험일", "분석일", "측정일", "생산일", "제조일", "일자", "날짜", "date", "datetime", "sampledat", "sampledate", "samplingdate", "시각", "접수일", "접수일시", "등록일시", "결과일시"]);
  const isTsHead = (nn) => TS_HEAD.has(nn) || /(일시|일자|날짜|date|채취일|시험일|분석일|측정일|생산일|제조일|접수일|등록일)/.test(nn);
  const TIME_HEAD = W(["시간", "시각", "time", "채취시간", "시료채취시간", "분석시간", "측정시간"]);
  const PROD_HEAD = W(["product", "품종", "종류", "제품", "type", "규격", "시멘트종류", "제품명", "품목", "시멘트품종", "제품구분"]);
  const POINT_HEAD = W(["시료명", "채취지점", "시료채취지점", "채취장소", "지점", "시료종류", "시료구분", "시료", "공정", "공정명", "샘플", "samplename", "samplepoint", "sample", "location", "위치", "시료명칭", "채취위치", "sampleid"]);
  const TEST_HEAD = W(["시험항목", "항목", "검사항목", "시험명", "분석항목", "측정항목", "항목명", "시험항목명", "분석명", "test", "testname", "item", "parameter", "analyte", "분석성분", "성분", "검사명", "시험종목", "시험종류"]);
  const VALUE_HEAD = W(["결과", "결과값", "측정값", "값", "수치", "result", "value", "분석결과", "시험결과", "분석값", "측정결과", "검사결과", "데이터", "실측값"]);
  const UNIT_HEAD = W(["단위", "unit", "units"]);
  const ID_HEAD = W(["no", "번호", "순번", "seq", "id", "시료번호", "시료no", "sampleno", "lotno", "로트번호", "접수번호", "순서", "연번", "lot", "batch"]);
  const UNIT_RE = /^(%|mpa|kpa|mg\/kg|mg\/l|ppm|cm2\/g|cm²\/g|m2\/kg|g\/l|g\/㎤|분|min|h|hr|℃|°c|c|t\/h|kg\/t|kg|g|ml|μm|um|mm|㎛|n\/mm2|n\/㎟|%rh|sec|초)$/i;

  const STAGE_WORDS = [
    ["raw_meal", ["생료", "킬른피드", "kilnfeed", "rawmeal", "조합원료", "rawmix", "원료밀", "rawmill"]],
    ["clinker", ["클링커", "clinker", "clk"]],
    ["cement", ["시멘트", "cement", "opc", "포틀랜드", "완제품", "시멘트밀", "cementmill"]],
    ["xrd", ["xrd", "광물조성"]],
    ["kiln", ["킬른", "kiln", "dcs"]],
    ["physical", ["물성", "모르타르", "mortar", "압축강도", "응결"]],
  ].map(([t, ws]) => [t, ws.map(nkey)]);
  const STRIP_WORDS = STAGE_WORDS.filter(([t]) => t !== "physical").flatMap(([, ws]) => ws).sort((a, b) => b.length - a.length);

  // 항목 접미사(키에서 접두 제거) → 별칭
  const BASES = {
    cao: ["산화칼슘", "calciumoxide"], sio2: ["이산화규소", "실리카", "silica"], al2o3: ["알루미나", "산화알루미늄", "alumina"],
    fe2o3: ["산화철", "ferricoxide"], mgo: ["산화마그네슘", "마그네시아", "magnesia"], so3: ["삼산화황", "무수황산", "sulfurtrioxide"],
    k2o: ["산화칼륨"], na2o: ["산화나트륨"], loi: ["강열감량", "작열감량", "강열손실", "igloss", "ignitionloss", "ig손실", "작열손량"],
    lsf: ["석회포화도", "lsf", "ls포화도", "포화도", "limesaturation", "limesaturationfactor", "kst"],
    sm: ["규산율", "실리카율", "sm", "silicamodulus", "msm", "sr"], im: ["철률", "알루미나율", "im", "am", "aluminamodulus", "mi"],
    r90: ["r90", "90um", "90미크론", "90um체잔분", "잔사90", "90um잔사", "90um잔분"], r200: ["r200", "200um", "200미크론", "200um체잔분", "200um잔사"],
    r45: ["r45", "45um", "45미크론", "45um체잔분", "잔분45", "45um잔사", "45um잔분"],
    fcao: ["fcao", "freecao", "freelime", "자유석회", "유리석회", "에프카오", "자유산화칼슘"],
    lw: ["리터중량", "lw", "literweight", "unitweight", "용적중량", "단위용적질량"],
    c3s: ["c3s", "alite", "알라이트", "에이라이트"], c2s: ["c2s", "belite", "벨라이트"], c3a: ["c3a", "알루미네이트", "aluminate"],
    c4af: ["c4af", "페라이트", "ferrite", "브라운밀러라이트"], alite: ["알라이트", "alite", "c3s"], belite: ["벨라이트", "belite", "c2s"],
    liquid: ["액상량", "liquid", "liquidphase", "액상", "액상량1450", "액상율"], na2oeq: ["등가알칼리", "na2oeq", "알칼리당량", "naeq", "totalalkali", "전알칼리"],
    periclase: ["페리클레이스", "periclase", "유리마그네시아"],
    cr: ["총크롬", "totalcr", "전크롬", "크롬함량", "totalchromium"],
    crvi: ["6가크롬", "수용성6가크롬", "육가크롬", "cr6", "crvi", "수용성크롬", "hexavalentchromium", "수용성cr6", "6가"],
    blaine: ["분말도", "비표면적", "blaine", "브레인", "ssa", "specificsurface", "블레인"],
    ls: ["석회석혼합률", "석회석혼합량", "석회석첨가량", "limestoneaddition", "ls혼합"],
    bzt: ["소성대온도", "버닝존온도", "bzt", "burningzone", "버닝존", "소성대"], o2: ["o2", "산소", "산소농도"], co: ["co", "일산화탄소"],
    feed: ["원료투입량", "kilnfeedrate", "feedrate", "킬른투입량"], coal_rate: ["석탄투입량", "coalrate", "석탄사용량"],
    torque: ["주모터부하", "킬른부하", "kilntorque", "토크"], calc_temp: ["하소로출구온도", "하소로온도", "calcinertemp"],
    sec_air: ["2차공기온도", "2차공기", "secondaryair"], mill_feed: ["밀투입량", "시멘트밀투입량"], mill_temp: ["밀출구온도", "시멘트밀출구온도", "밀온도"],
    ist: ["초결", "초결시간", "초기응결", "initialset", "ist", "initialsettingtime", "응결시작"],
    fst: ["종결", "종결시간", "최종응결", "finalset", "fst", "finalsettingtime", "응결종료"],
    autoclave: ["오토클레이브", "팽창도", "autoclave", "안정도", "soundness", "오토클레이브팽창도"],
    s1: ["1일압축강도", "1일강도", "압축강도1일", "cs1", "1d", "강도1일", "1일재령"], s3: ["3일압축강도", "3일강도", "압축강도3일", "cs3", "3d", "강도3일", "3일재령"],
    s7: ["7일압축강도", "7일강도", "압축강도7일", "cs7", "7d", "강도7일", "7일재령"], s28: ["28일압축강도", "28일강도", "압축강도28일", "cs28", "28d", "강도28일", "28일재령"],
    temp: ["시험실온도", "실온", "labtemp", "labtemperature", "룸온도"], rh: ["상대습도", "습도", "humidity", "rh", "시험실습도", "시험실상대습도"],
    cure_temp: ["양생수온도", "양생온도", "curetemp", "curingtemp", "양생수"],
  };

  // 값의 범위(상식적인 범위, 추정). 항목 확정 보조·열 이름을 모를 때 추정용
  const RANGES = {
    rm_cao: [38, 48], rm_sio2: [10, 18], rm_al2o3: [1.5, 6], rm_fe2o3: [1, 4.5], rm_mgo: [0.3, 3.5], rm_so3: [0, 1.5], rm_k2o: [0, 1.5], rm_na2o: [0, 0.6],
    rm_lsf: [90, 105], rm_sm: [2, 3.3], rm_im: [1, 2.6], rm_r90: [3, 25], rm_r200: [0, 4], rm_loi: [32, 38],
    kiln_bzt: [1200, 1600], kiln_calc_temp: [750, 950], kiln_sec_air: [800, 1200], kiln_o2: [0, 12], kiln_co: [0, 2],
    clk_cao: [60, 70], clk_sio2: [19, 25], clk_al2o3: [3, 8], clk_fe2o3: [1.5, 6], clk_mgo: [0.5, 5.5], clk_so3: [0, 3.5], clk_k2o: [0, 2.5], clk_na2o: [0, 1],
    clk_fcao: [0, 4], clk_lw: [1000, 1600], clk_lsf: [88, 102], clk_sm: [1.8, 3.4], clk_im: [0.9, 2.8], clk_c3s: [40, 75], clk_c2s: [5, 35],
    clk_c3a: [0, 14], clk_c4af: [5, 16], clk_liquid: [18, 35], clk_na2oeq: [0, 1.6],
    xrd_alite: [45, 78], xrd_belite: [4, 30], xrd_c3a: [0, 15], xrd_c4af: [3, 18], xrd_fcao: [0, 4], xrd_periclase: [0, 5], clk_cr: [10, 400], clk_crvi: [0, 60],
    cem_blaine: [2500, 6000], cem_r45: [0, 30], cem_so3: [1, 5], cem_loi: [0, 6], cem_mgo: [0.5, 5.5], cem_ls: [0, 10], cem_mill_temp: [60, 150],
    phy_ist: [30, 400], phy_fst: [60, 700], phy_autoclave: [-0.1, 1], phy_crvi: [0, 40], phy_s1: [5, 40], phy_s3: [10, 50], phy_s7: [20, 60], phy_s28: [30, 70],
    lab_temp: [15, 28], lab_rh: [30, 100], lab_cure_temp: [15, 28],
  };

  // ── 엔진 ─────────────────────────────────────────────────────
  function create(spec) {
    const ITEM = {};
    spec.items.forEach((it) => { ITEM[it.key] = it; });
    const ALIAS = new Map();          // nkey → Set(item key)
    function addAlias(a, key) { const n = nkey(a); if (n) { if (!ALIAS.has(n)) ALIAS.set(n, new Set()); ALIAS.get(n).add(key); } }
    const itemStages = {};
    spec.items.forEach((it) => {
      const nm = nkey(it.name); itemStages[it.key] = new Set([it.table]);
      STAGE_WORDS.forEach(([t, ws]) => { if (ws.some((w) => nm.includes(w))) itemStages[it.key].add(t); });
      if (/^pred_/.test(it.key)) return;                      // 계산(예측) 항목은 불러오기 대상이 아님
      addAlias(it.name, it.key); addAlias(it.key, it.key);
      addAlias(it.name.replace(/^(생료|원료|클링커|시멘트|xrd|킬른)\s*/i, ""), it.key);
      const parts = it.key.split("_"); const suffix = parts.slice(1).join("_");
      [suffix, it.key].forEach((s) => (BASES[s] || []).forEach((a) => addAlias(a, it.key)));
    });
    const ALIAS_LONG = [...ALIAS.keys()].filter((a) => a.length >= 4).sort((a, b) => b.length - a.length);

    function stagesFrom(strs) {
      const n = nkey(strs.filter(Boolean).join(" "));
      const raw = strs.filter(Boolean).join(" ").toLowerCase();
      const set = new Set();
      STAGE_WORDS.forEach(([t, ws]) => { if (ws.some((w) => n.includes(w) || raw.includes(w))) set.add(t); });
      return set;
    }
    function stripStage(n) { let s = n; STRIP_WORDS.forEach((w) => { s = s.split(w).join(""); }); return s; }
    function lookup(n) {
      let keys = ALIAS.get(n);
      if (!keys) { const s = stripStage(n); if (s && s !== n) keys = ALIAS.get(s); }
      if (!keys) {
        const hit = ALIAS_LONG.find((a) => n.includes(a));
        if (hit) { keys = new Set(ALIAS.get(hit)); ALIAS_LONG.filter((a) => a.length === hit.length && n.includes(a)).forEach((a) => ALIAS.get(a).forEach((k) => keys.add(k))); }
      }
      return keys ? [...keys] : [];
    }
    // 라벨(들)→후보 키. ctx: 문맥 문자열(그룹 머리글·시트 이름·지점 이름 등)
    const stripUnit = (lab) => String(lab).replace(/\s*[\(\[（]\s*([^\)\]）]*)\s*[\)\]）]\s*$/, (m, u) => (UNIT_RE.test(u.replace(/\s+/g, "")) ? "" : m));
    function narrow(keys, hints) {
      if (keys.length <= 1) return keys;
      const f = keys.filter((k) => [...itemStages[k]].some((t) => hints.has(t)));
      if (f.length) return f;
      if (hints.size === 0) { const g = keys.filter((k) => ITEM[k].table !== "xrd"); if (g.length) return g; }   // 단서가 없으면 일반 분석 항목을 우선
      return keys;
    }
    function resolve(labels, ctx) {
      const hints = stagesFrom([...labels, ...(ctx || [])]);
      for (const lab of labels) {
        for (const text of [stripUnit(lab), lab]) {
          const n = nkey(text); if (!n) continue;
          const keys = narrow(lookup(n), hints);
          if (keys.length) return { keys, hints };
        }
      }
      return { keys: [], hints };
    }
    function rangeFit(key, nums) {
      const r = RANGES[key]; if (!r || nums.length < 2) return null;
      return nums.filter((v) => v >= r[0] && v <= r[1]).length / nums.length;
    }
    function bestByContent(nums, allowed) {
      const fits = Object.keys(RANGES).filter((k) => ITEM[k] && (!allowed || allowed.has(ITEM[k].table))).map((k) => [k, rangeFit(k, nums)]).filter((x) => x[1] != null).sort((a, b) => b[1] - a[1]);
      return fits;
    }
    // 항목 후보 판정: {key, conf: high|mid|low|none, why, cands}
    function decide(labels, ctx, nums) {
      const r = resolve(labels, ctx);
      const cands = r.keys;
      if (cands.length === 1) {
        const k = cands[0], f = rangeFit(k, nums);
        if (f != null && f < 0.4) return { key: k, conf: "mid", cands, why: `이름은 '${ITEM[k].name}'과 같지만 값 범위가 예상(${RANGES[k][0]}~${RANGES[k][1]})과 달라 확인 필요` };
        return { key: k, conf: "high", cands, why: "열 이름 일치" };
      }
      if (cands.length > 1) {
        const ranked = cands.map((k) => [k, rangeFit(k, nums)]).sort((a, b) => (b[1] == null ? -1 : b[1]) - (a[1] == null ? -1 : a[1]));
        const [k0, f0] = ranked[0], f1 = ranked[1][1];
        if (f0 != null && f0 >= 0.7 && (f1 == null || f1 < 0.4)) return { key: k0, conf: "high", cands, why: `이름이 같은 항목 중 값 범위로 '${ITEM[k0].name}' 확정` };
        return { key: k0, conf: "low", cands, why: "같은 이름의 항목이 여러 개(생료/클링커/시멘트 등) — 어느 것인지 확인 필요" };
      }
      if (nums.length >= 3) {
        const fits = bestByContent(nums, null);
        if (fits.length && fits[0][1] >= 0.9 && (fits.length < 2 || fits[1][1] < 0.5)) return { key: fits[0][0], conf: "mid", cands: [fits[0][0]], why: `이름을 알 수 없어 값 범위로 추정(${RANGES[fits[0][0]][0]}~${RANGES[fits[0][0]][1]})` };
        if (fits.length && fits[0][1] >= 0.9) return { key: null, conf: "none", cands: fits.filter((f) => f[1] >= 0.9).slice(0, 4).map((f) => f[0]), why: "열 이름을 알 수 없음(값 범위로 후보만 표시)" };
      }
      return { key: null, conf: "none", cands: [], why: "해당 항목 없음(무시)" };
    }

    // ── 표 구조 판별 ─────────────────────────────────────────
    const cell = (aoa, r, c) => { const row = aoa[r]; return row ? row[c] : undefined; };
    function recognized(v) {
      if (isBlank(v) || typeof v !== "string") return false;
      const n = nkey(v);
      return TS_HEAD.has(n) || TIME_HEAD.has(n) || PROD_HEAD.has(n) || POINT_HEAD.has(n) || TEST_HEAD.has(n) || VALUE_HEAD.has(n) || UNIT_HEAD.has(n) || ID_HEAD.has(n) || lookup(n).length > 0;
    }
    function rowInfo(row) {
      let text = 0, num = 0, rec = 0, nonempty = 0;
      (row || []).forEach((v) => { if (isBlank(v)) return; nonempty++; if (isNumber(v)) num++; else if (typeof v === "string") { if (parseDate(v) || parseNum(v).v != null) num++; else text++; } else num++; if (recognized(v)) rec++; });
      return { text, num, rec, nonempty };
    }
    function looksData(row) { const i = rowInfo(row); return i.nonempty >= 2 && (i.num >= 1); }
    function isUnitRow(row) {
      const vals = (row || []).filter((v) => !isBlank(v)); if (vals.length < 2) return false;
      return vals.filter((v) => UNIT_RE.test(String(v).trim().replace(/\s+/g, ""))).length / vals.length >= 0.7;
    }
    function findHeader(aoa) {
      const lim = Math.min(aoa.length, 30); let best = -1, bestScore = -1e9;
      for (let r = 0; r < lim; r++) {
        const i = rowInfo(aoa[r]); if (i.text < 2) continue;
        let s = i.rec * 3 + i.text * 0.4 - i.num * 1.5;
        let ahead = 0; for (let k = 1; k <= 4; k++) if (r + k < aoa.length && (looksData(aoa[r + k]) || isUnitRow(aoa[r + k]))) ahead++;
        s += ahead * 0.8;
        if (s > bestScore) { bestScore = s; best = r; }
      }
      return best < 0 ? 0 : best;
    }
    function groupRow(aoa, h, width) {         // 위쪽 그룹 머리글(병합 셀) → 열별 문자열
      const out = new Array(width).fill("");
      const row = aoa[h - 1]; if (h < 1 || !row) return out;
      const cells = row.map((v) => (isBlank(v) ? "" : String(v).trim()));
      const filled = cells.filter(Boolean).length; if (filled < 2 && cells.findIndex(Boolean) === 0 && rowInfo(row).text === 1) return out; // 제목 줄
      if (rowInfo(row).num > 0) return out;
      let cur = ""; for (let c = 0; c < width; c++) { if (cells[c]) cur = cells[c]; out[c] = cur; }
      return out;
    }

    // 열 통계
    function columnStats(aoa, from, c) {
      const vals = []; let n = 0, dates = 0, times = 0, nums = [], strs = new Map();
      for (let r = from; r < Math.min(aoa.length, from + 800); r++) {
        const v = cell(aoa, r, c); if (isBlank(v)) continue; n++;
        if (parseDate(v)) dates++;
        else if (timeOf(v)) times++;
        const p = parseNum(v);
        if (p.v != null) nums.push(p.v); else if (typeof v === "string") strs.set(v.trim(), (strs.get(v.trim()) || 0) + 1);
        if (vals.length < 3) vals.push(v);
      }
      return { n, dates, times, nums, strs, sample: vals };
    }
    const PRODUCT_RE = /^(1종|3종|opc|hes|보통|조강|type\s?i{1,3}|i{1,3}종|\d종)/i;
    function normProduct(s) {
      const t = String(s == null ? "" : s).trim();
      if (/1종|opc|보통|type\s?i\b/i.test(t)) return "1종";
      if (/3종|hes|조강|type\s?iii/i.test(t)) return "3종";
      return t;
    }

    function analyze(aoa, opts) {
      opts = opts || {};
      aoa = (aoa || []).map((r) => (Array.isArray(r) ? r : []));
      const width = aoa.reduce((m, r) => Math.max(m, r.length), 0);
      if (aoa.length < 2 || width < 2) return null;
      const h = opts.headerRow != null ? opts.headerRow : findHeader(aoa);
      const header = []; for (let c = 0; c < width; c++) header.push(isBlank(cell(aoa, h, c)) ? "" : String(cell(aoa, h, c)).trim());
      const group = groupRow(aoa, h, width);
      let from = h + 1, unitRow = false;
      if (isUnitRow(aoa[from])) { unitRow = true; from++; }
      const units = unitRow ? (aoa[h + 1] || []).map((v) => (isBlank(v) ? "" : String(v).trim())) : [];
      const sheetName = opts.sheetName || "";
      const stats = []; for (let c = 0; c < width; c++) stats.push(columnStats(aoa, from, c));

      const cols = header.map((hd, idx) => {
        const st = stats[idx], nn = nkey(hd);
        const col = { idx, header: hd || `(열 ${idx + 1})`, group: group[idx], role: "", key: null, conf: "none", why: "", cands: [], n: st.n, sample: st.sample.map((x) => String(x)) };
        if (st.n === 0) { col.why = "비어 있음"; return col; }
        const numFrac = st.nums.length / st.n, dateFrac = st.dates / st.n, timeFrac = st.times / st.n;
        const prodFrac = [...st.strs.entries()].filter(([s]) => PRODUCT_RE.test(s)).reduce((a, [, c]) => a + c, 0) / st.n;
        if (isTsHead(nn) && dateFrac >= 0.3) { col.role = "ts"; col.conf = "high"; col.why = "일시 열(이름)"; }
        else if (TIME_HEAD.has(nn) && timeFrac >= 0.5) { col.role = "time"; col.conf = "high"; col.why = "시간 열(이름)"; }
        else if (dateFrac >= 0.8 && !TIME_HEAD.has(nn)) { col.role = "ts"; col.conf = isTsHead(nn) ? "high" : "mid"; col.why = isTsHead(nn) ? "일시 열" : "날짜 형식의 값으로 추정"; }
        else if (timeFrac >= 0.8) { col.role = "time"; col.conf = "mid"; col.why = "시각 형식의 값으로 추정"; }
        else if (PROD_HEAD.has(nn) || prodFrac >= 0.8) { col.role = "product"; col.conf = PROD_HEAD.has(nn) ? "high" : "mid"; col.why = "품종 열"; }
        else if (UNIT_HEAD.has(nn)) { col.role = "unit"; col.conf = "high"; col.why = "단위(무시)"; }
        else if (ID_HEAD.has(nn) || /^(no|번호|순번)\.?$/i.test(hd)) { col.role = "id"; col.conf = "high"; col.why = "번호(무시)"; }
        else if (POINT_HEAD.has(nn) && numFrac < 0.5) { col.role = "point"; col.conf = "high"; col.why = "시료·지점 열"; }
        else if (TEST_HEAD.has(nn) && numFrac < 0.5) { col.role = "test"; col.conf = "high"; col.why = "시험항목 열"; }
        else if (VALUE_HEAD.has(nn) && numFrac >= 0.5) { col.role = "value"; col.conf = "high"; col.why = "결과값 열"; }
        return col;
      });

      // 사용자가 지정한 열 역할(ts/time/product/point/test/value → 열 번호, -1 = 없음)을 반영
      if (opts.roles) Object.keys(opts.roles).forEach((role) => {
        cols.forEach((c) => { if (c.role === role) { c.role = ""; c.conf = "none"; c.why = ""; } });
        const idx = opts.roles[role];
        if (idx >= 0 && cols[idx]) { cols[idx].role = role; cols[idx].key = null; cols[idx].conf = "high"; cols[idx].why = "사용자 지정"; }
      });
      // 긴 형식 판별: 시험항목 열 + 결과값 열
      const get = (role) => cols.find((c) => c.role === role);
      let test = get("test"), value = get("value");
      if (!test) {                                   // 이름이 없어도 '반복되는 글자 열이 대부분 알려진 항목 이름'이면 시험항목 열
        const cand = cols.filter((c) => !c.role && c.n > 0).map((c) => {
          const st = stats[c.idx]; const distinct = st.strs.size; const textFrac = [...st.strs.values()].reduce((a, b) => a + b, 0) / c.n;
          if (textFrac < 0.8 || distinct < 2 || distinct > 150 || distinct > c.n / 2.5) return null;
          const known = [...st.strs.keys()].filter((s) => lookup(nkey(s)).length).length / distinct;
          return known >= 0.5 ? { c, known } : null;
        }).filter(Boolean).sort((a, b) => b.known - a.known)[0];
        if (cand) { test = cand.c; test.role = "test"; test.conf = "mid"; test.why = "값이 반복되는 항목 이름들로 보여 시험항목 열로 추정"; }
      }
      if (test && !value) {
        const after = cols.filter((c) => c.idx > test.idx && !c.role && stats[c.idx].nums.length / Math.max(stats[c.idx].n, 1) >= 0.7)[0]
          || cols.filter((c) => !c.role && stats[c.idx].nums.length / Math.max(stats[c.idx].n, 1) >= 0.7)[0];
        if (after) { value = after; value.role = "value"; value.conf = "mid"; value.why = "숫자가 들어 있는 열을 결과값으로 추정"; }
      }
      let layout = test && value ? "long" : "wide";
      if (opts.layout) layout = opts.layout;
      const ts = get("ts"), time = get("time"), product = get("product"), point = get("point");
      const analysis = { sheet: sheetName, headerRow: h, dataStart: from, unitRow, units, layout, cols, width, aoa, rowsTotal: aoa.length - from, group };

      if (layout === "wide") {
        cols.forEach((c) => {
          if (c.role || c.n === 0) return;
          const st = stats[c.idx];
          if (st.nums.length / c.n < 0.5) { c.why = "숫자가 아닌 열(무시)"; return; }
          const labels = [c.header]; if (c.group) labels.push(c.group + " " + c.header);
          const d = decide(labels, [c.group, sheetName], st.nums);
          if (units[c.idx] && !c.group) { /* 단위는 참고만 */ }
          c.role = d.key ? "item" : ""; c.key = d.key; c.conf = d.conf; c.why = d.why; c.cands = d.cands;
        });
        // 이름이 같은 후보가 여럿이면, 가장 가까운(옆) 확정 열의 공정을 단서로 추정(같은 공정 열끼리 모여 있는 표가 많음). 추정이므로 '확인 필요'
        const sure = cols.filter((c) => c.role === "item" && c.key && c.conf === "high" && c.cands.length === 1);
        cols.forEach((c) => {
          if (c.role !== "item" || c.conf !== "low" || !sure.length) return;
          const near = sure.map((x) => [x, Math.abs(x.idx - c.idx) + (x.idx > c.idx ? 0.1 : 0)]).sort((p, q) => p[1] - q[1])[0][0];
          const pick = c.cands.filter((k) => ITEM[k].table === ITEM[near.key].table);
          if (pick.length === 1) { c.key = pick[0]; c.conf = "mid"; c.why = `같은 이름의 항목이 여러 개인데, 옆 열 '${near.header}'이(가) '${spec.tables[ITEM[near.key].table].label}' 공정이라 '${ITEM[pick[0]].name}'로 추정 — 확인 필요`; }
        });
      } else {
        analysis.pairs = [];
        const mk = new Map();
        for (let r = from; r < aoa.length; r++) {
          const tv = cell(aoa, r, test.idx); if (isBlank(tv)) continue;
          const pv = point ? cell(aoa, r, point.idx) : (product ? cell(aoa, r, product.idx) : "");
          const key = (isBlank(pv) ? "" : String(pv).trim()) + "\u0001" + String(tv).trim();
          if (!mk.has(key)) mk.set(key, { point: isBlank(pv) ? "" : String(pv).trim(), test: String(tv).trim(), n: 0, nums: [], sample: [] });
          const e = mk.get(key); e.n++; const p = parseNum(cell(aoa, r, value.idx));
          if (p.v != null) e.nums.push(p.v); if (e.sample.length < 3) e.sample.push(String(cell(aoa, r, value.idx)));
        }
        mk.forEach((e) => {
          const d = decide([e.test, e.point + " " + e.test], [e.point, sheetName], e.nums);
          analysis.pairs.push({ point: e.point, test: e.test, n: e.n, sample: e.sample, key: d.key, conf: d.conf, why: d.why, cands: d.cands });
        });
        analysis.pairs.sort((a, b) => b.n - a.n);
      }
      analysis.roles = { ts: ts ? ts.idx : -1, time: time ? time.idx : -1, product: product ? product.idx : -1, point: point ? point.idx : -1, test: test ? test.idx : -1, value: value ? value.idx : -1 };
      if (analysis.roles.ts < 0) {                  // 일시 열을 못 찾은 경우: 날짜 비율이 가장 높은 열
        const best = cols.filter((c) => c.n > 0).map((c) => [c, stats[c.idx].dates / c.n]).sort((a, b) => b[1] - a[1])[0];
        if (best && best[1] >= 0.5) { best[0].role = "ts"; best[0].conf = "mid"; best[0].why = "날짜가 가장 많은 열을 일시로 추정"; best[0].key = null; analysis.roles.ts = best[0].idx; }
      }
      analysis.status = statusOf(analysis);
      return analysis;
    }

    // 자동 반영 가능 여부: 일시 확정 + 항목 1개 이상 + '확인 필요(mid/low)' 없음
    function statusOf(a) {
      const issues = [];
      if (a.roles.ts < 0) issues.push("일시 열을 찾지 못했습니다");
      else if (a.cols[a.roles.ts].conf !== "high") issues.push("일시 열 추정 확인");
      let items = 0;
      if (a.layout === "wide") a.cols.forEach((c) => { if (c.role === "item" && c.key) { items++; if (c.conf !== "high") issues.push(`'${c.header}' 확인 필요`); } else if (c.conf === "none" && c.cands && c.cands.length) issues.push(`'${c.header}' 항목 후보 있음`); });
      else {
        if (a.roles.test < 0 || a.roles.value < 0) issues.push("시험항목/결과값 열을 찾지 못했습니다");
        if (a.cols[a.roles.test] && a.cols[a.roles.test].conf !== "high") issues.push("시험항목 열 추정 확인");
        if (a.cols[a.roles.value] && a.cols[a.roles.value].conf !== "high") issues.push("결과값 열 추정 확인");
        a.pairs.forEach((p) => { if (p.key) { items++; if (p.conf !== "high") issues.push(`'${p.point ? p.point + " / " : ""}${p.test}' 확인 필요`); } });
      }
      if (items === 0) issues.push("인식된 항목이 없습니다");
      return { auto: issues.length === 0, issues, items };
    }

    // ── 추출 ─────────────────────────────────────────────────
    function extract(a) {
      const rec = []; let bad = 0, read = 0, censored = 0;
      const R = a.roles, aoa = a.aoa;
      const prodOf = (r, pointText) => {
        if (R.product >= 0) { const v = cell(aoa, r, R.product); if (!isBlank(v)) return normProduct(v); }
        if (pointText) { const m = String(pointText).match(/1종|3종|opc|hes|조강|보통/i); if (m) return normProduct(m[0]); }   // 예: '시멘트(OPC)' → 1종
        return null;
      };
      for (let r = a.dataStart; r < aoa.length; r++) {
        const row = aoa[r]; if (!row || row.every(isBlank)) continue;
        const ts = R.ts >= 0 ? parseDate(cell(aoa, r, R.ts), R.time >= 0 ? cell(aoa, r, R.time) : null) : null;
        if (!ts) { bad++; continue; }
        read++;
        if (a.layout === "wide") {
          const prod = prodOf(r);
          a.cols.forEach((c) => {
            if (c.role !== "item" || !c.key) return;
            const raw = cell(aoa, r, c.idx); if (isBlank(raw)) return;
            const textual = (spec.textColumns || []).indexOf(c.key) >= 0;
            if (textual) { rec.push({ key: c.key, ts, prod, v: String(raw) }); return; }
            const p = parseNum(raw); if (p.v == null) return; if (p.censored) censored++;
            rec.push({ key: c.key, ts, prod, v: p.v });
          });
        } else {
          const tv = cell(aoa, r, R.test), pv = R.point >= 0 ? cell(aoa, r, R.point) : (R.product >= 0 ? cell(aoa, r, R.product) : "");
          if (isBlank(tv)) continue;
          const pr = a.pairs.find((x) => x.test === String(tv).trim() && x.point === (isBlank(pv) ? "" : String(pv).trim()));
          if (!pr || !pr.key) continue;
          const raw = cell(aoa, r, R.value); const p = parseNum(raw); if (p.v == null) continue; if (p.censored) censored++;
          rec.push({ key: pr.key, ts, prod: prodOf(r, isBlank(pv) ? "" : pv), v: p.v });
        }
      }
      // 공정별 표로 변환(같은 일시·품종·항목이 여러 번 나오면 마지막 값)
      const byTable = {};
      rec.forEach((x) => { const t = ITEM[x.key].table; (byTable[t] = byTable[t] || []).push(x); });
      const tables = {}, per = [];
      Object.keys(byTable).forEach((t) => {
        const list = byTable[t];
        const byProduct = spec.tables[t] ? spec.tables[t].byProduct && list.some((x) => x.prod) : false;
        const columns = [...new Set(list.map((x) => x.key))];
        const rows = new Map();
        list.forEach((x) => {
          const k = x.ts + "|" + (byProduct ? (x.prod || "-") : "");
          if (!rows.has(k)) rows.set(k, { ts: x.ts, prod: x.prod || "-", vals: {} });
          rows.get(k).vals[x.key] = x.v;
        });
        const arr = [...rows.values()].sort((p, q) => (p.ts < q.ts ? -1 : p.ts > q.ts ? 1 : 0)).map((r) => {
          const o = [r.ts]; if (byProduct) o.push(r.prod); columns.forEach((k) => o.push(r.vals[k] == null ? null : r.vals[k])); return o;
        });
        tables[t] = { byProduct, columns, rows: arr };
        per.push({ table: t, rows: arr.length, items: columns });
      });
      const ignored = a.layout === "wide"
        ? a.cols.filter((c) => c.n > 0 && !(c.role === "item" && c.key) && ["", "item"].indexOf(c.role) >= 0).map((c) => c.header)
        : a.cols.filter((c) => c.n > 0 && !c.role).map((c) => c.header);
      return { tables, summary: { layout: a.layout, headerRow: a.headerRow + 1, rowsRead: read, rowsSkipped: bad, perTable: per, ignored, censored, unitRow: a.unitRow } };
    }

    // 사용자가 열을 바꾼 뒤 역할 번호·자동 반영 상태를 다시 계산
    function refresh(a) {
      const idx = (role) => { const c = a.cols.find((x) => x.role === role); return c ? c.idx : -1; };
      a.roles = { ts: idx("ts"), time: idx("time"), product: idx("product"), point: idx("point"), test: idx("test"), value: idx("value") };
      a.status = statusOf(a); return a;
    }
    return { analyze, extract, refresh, resolve, decide, nkey, ITEM };
  }

  return { create, nkey, parseNum, parseDate, timeOf, RANGES, normalize: nkey };
});
