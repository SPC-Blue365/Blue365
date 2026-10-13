/* Blue365 QMS 대시보드 — 출하시멘트(LIMS 일일 로트 표) 분석 모듈 (브라우저·노드 공용, 외부 의존 없음)

   대상 파일 구조(실제 LIMS 내보내기에서 확인): 머리글 1줄, 1행 = 채취일 1건(그날 출하분의 대표 시험 결과),
   첨가재명칭·석회석비율·첨가재비율·화학성분(XRF)·강도(1/3/7/28일)·분말도·주도·Flow·응결시간, 비고 = 그날 출항한 선박명.
   · 값 0 은 '미시험'(예: 28일 강도는 아직 시험 전) → 결측으로 처리하고 건수를 보고한다.
   · 종결시간은 'HH:MM' 문자열 → 분으로 환산. 초결시간은 숫자 문자열.
   · 비고: 선박명이 쉼표로 나열됨(괄호 안 쉼표·마침표·공백 잡음 있음, '수성3'/'수성3호' 혼용) → 이름 정규화.
     선박 1척 = 그 배만 단독 시험한 값, 2척 이상 = 그날 출항한 배들의 평균값. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./ingest.js"));
  else root.SHIP = factory(root.INGEST);
})(typeof self !== "undefined" ? self : this, function (INGEST) {
  "use strict";

  // 기준값 초기값: KS L 5201(포틀랜드 시멘트) 참고 — ※ 원문을 이 환경에서 확인하지 못한 값이므로 '추정·원문 확인 필요'. 화면에서 수정 가능.
  const KS_NOTE = "KS L 5201 참고값(추정·원문 확인 필요)";
  const ITEMS = [
    { key: "ls", name: "석회석 비율", unit: "%", dec: 1, setting: true, zeroOk: true, group: "배합 구성", aliases: ["석회석비율", "석회석혼합률", "석회석혼합비율", "석회석배합률"] },
    { key: "addr", name: "첨가재 비율", unit: "%", dec: 1, setting: true, zeroOk: true, group: "배합 구성", aliases: ["첨가재비율", "혼화재비율", "혼합재비율", "첨가재혼합률"] },
    { key: "loi", name: "LOI(강열감량)", unit: "%", dec: 2, group: "화학성분", aliases: ["loi", "강열감량", "강열감량loi"], lim: { usl: 5.0, src: KS_NOTE } },
    { key: "al2o3", name: "Al₂O₃", unit: "%", dec: 2, group: "화학성분", aliases: ["al2o3", "알루미나", "산화알루미늄"] },
    { key: "mgo", name: "MgO", unit: "%", dec: 2, group: "화학성분", aliases: ["mgo", "산화마그네슘"], lim: { usl: 5.0, src: KS_NOTE } },
    { key: "so3", name: "SO₃(XRF)", unit: "%", dec: 2, group: "화학성분", aliases: ["so3xrf", "xrfso3", "so3"], lim: { usl: 3.5, src: KS_NOTE } },
    { key: "cl", name: "Cl(XRF)", unit: "ppm", dec: 0, group: "화학성분", aliases: ["clxrf", "xrfcl", "염소xrf", "염화물xrf", "cl"], tip: "파일에 단위 표기가 없음 — 값 규모(100~1000)로 ppm(mg/kg) 추정" },
    { key: "ta", name: "TA(총알칼리)", unit: "%", dec: 2, group: "화학성분", aliases: ["ta", "총알칼리", "전알칼리", "na2oeq", "등가알칼리"], tip: "Na₂O+0.658·K₂O 와 일치함을 실제 파일로 확인(최대 차이 0.012)" },
    { key: "s1", name: "압축강도 1일", unit: "MPa", dec: 1, group: "강도", aliases: ["압축강도1일mpa", "압축강도1일", "1일압축강도", "1일강도", "강도1일"] },
    { key: "s3", name: "압축강도 3일", unit: "MPa", dec: 1, group: "강도", aliases: ["압축강도3일mpa", "압축강도3일", "3일압축강도", "3일강도", "강도3일"], lim: { lsl: 12.5, src: KS_NOTE } },
    { key: "s7", name: "압축강도 7일", unit: "MPa", dec: 1, group: "강도", aliases: ["압축강도7일mpa", "압축강도7일", "7일압축강도", "7일강도", "강도7일"], lim: { lsl: 22.5, src: KS_NOTE } },
    { key: "s28", name: "압축강도 28일", unit: "MPa", dec: 1, group: "강도", aliases: ["압축강도28일mpa", "압축강도28일", "28일압축강도", "28일강도", "강도28일"], lim: { lsl: 42.5, src: KS_NOTE } },
    { key: "r45", name: "45㎛ 잔사", unit: "%", dec: 1, group: "분말도·물성", aliases: ["45um", "45um잔사", "45um체잔분", "r45", "45마이크로"], tip: "단위 표기 없음 — 잔사율(%)로 추정" },
    { key: "blaine", name: "Blaine 분말도", unit: "cm²/g", dec: 0, group: "분말도·물성", aliases: ["blaine", "분말도blaine", "분말도", "블레인"], lim: { lsl: 2800, src: KS_NOTE } },
    { key: "cons", name: "주도(표준주도)", unit: "%", dec: 1, group: "분말도·물성", aliases: ["주도", "표준주도", "정상주도", "표준주도수량"], tip: "물 사용량(%)으로 추정" },
    { key: "flow", name: "Flow", unit: "", dec: 0, group: "분말도·물성", aliases: ["flow", "플로우", "모르타르flow"], tip: "단위 표기 없음" },
    { key: "fst", name: "종결시간", unit: "분", dec: 0, group: "분말도·물성", aliases: ["종결시간hhmm", "종결시간", "종결", "finalset"], hhmm: true, lim: { usl: 600, src: KS_NOTE } },
  ];
  const BY = {}; ITEMS.forEach((it) => { BY[it.key] = it; });
  const ROLE_ALIASES = {
    date: ["채취일", "시료채취일", "채취일자", "시료채취일시", "채취일시"],
    additive: ["첨가재명칭", "첨가재", "첨가재명", "혼화재명칭", "혼합재명칭"],
    ships: ["비고", "선박", "선박명", "모선", "출항선박"],
    lot: ["limslotno", "erplotno", "lotno", "로트번호"],
  };

  // 머리글 정규화: NFKC(㎛→μm, 아래첨자 숫자→숫자) · 소문자 · 영숫자/한글만 · μ→u
  function norm(s) {
    if (s == null) return "";
    let t = String(s).normalize("NFKC").toLowerCase().replace(/[μµ]/g, "u");
    return t.replace(/[^0-9a-zㄱ-ㆎ가-힣]/g, "");
  }
  const isBlank = (v) => v == null || (typeof v === "string" && v.trim() === "");

  function matchHeaders(headers, overrides) {
    const idx = {}; const used = new Set();
    const nh = headers.map(norm);
    const take = (key, aliases) => {
      if (overrides && overrides[key] != null && overrides[key] >= 0) { idx[key] = overrides[key]; used.add(overrides[key]); return; }
      for (const a of aliases) {                            // 앞쪽 별칭일수록 우선(더 구체적)
        const i = nh.findIndex((h, j) => h === a && !used.has(j));
        if (i >= 0) { idx[key] = i; used.add(i); return; }
      }
    };
    for (const r in ROLE_ALIASES) take(r, ROLE_ALIASES[r]);
    ITEMS.forEach((it) => take(it.key, it.aliases));
    return idx;
  }

  // 시트(aoa)가 이 형식인가? 머리글 줄과 인식된 열을 돌려준다(아니면 null)
  function detect(aoa) {
    if (!aoa || aoa.length < 3) return null;
    let best = null;
    for (let r = 0; r < Math.min(aoa.length, 40); r++) {
      const row = aoa[r] || []; if (row.filter((c) => !isBlank(c)).length < 8) continue;
      const idx = matchHeaders(row.map((c) => (c == null ? "" : c)));
      const core = ITEMS.filter((it) => idx[it.key] != null).length;
      const score = core + (idx.date != null ? 3 : 0) + (idx.additive != null ? 2 : 0) + (idx.ships != null ? 1 : 0);
      if (!best || score > best.score) best = { headerRow: r, idx, score, core };
    }
    if (!best) return null;
    const hasStrength = ["s1", "s3", "s7", "s28"].some((k) => best.idx[k] != null);
    if (best.idx.date != null && best.core >= 8 && (hasStrength || best.idx.additive != null)) return best;
    return null;
  }

  // ── 비고 → 선박 목록 ──
  // 괄호 밖의 , ， 、 / ; 줄바꿈에서만 나눈다. 괄호 안 내용은 주석(부산·저염 등)으로 분리.
  function splitShipText(text) {
    const out = []; let depth = 0, cur = "";
    for (const ch of String(text)) {
      if (ch === "(" || ch === "（") depth++;
      if (ch === ")" || ch === "）") depth = Math.max(0, depth - 1);
      if (depth === 0 && /[,，、/;\n]/.test(ch)) { out.push(cur); cur = ""; } else cur += ch;
    }
    out.push(cur);
    return out;
  }
  function cleanShip(tok) {
    const notes = [];
    let s = tok.replace(/[(（]([^)）]*)[)）]?/g, (_, n) => { if (n.trim()) notes.push(n.replace(/[\s.]+/g, " ").trim()); return ""; });
    s = s.replace(/[)）]/g, "").replace(/[\s.·]+/g, "");
    return { name: s, notes };
  }
  function parseShipsRaw(text) {
    if (isBlank(text)) return [];
    return splitShipText(text).map(cleanShip).filter((x) => x.name);
  }
  function canonShip(name, vocab) {
    if (/호$/.test(name)) return name;
    if (vocab.has(name + "호")) return name + "호";
    if (/^[가-힣]+\d+$/.test(name)) return name + "호";
    return name;
  }

  // ── 값 해석 ──
  function numOf(v) { const r = INGEST.parseNum(v); return r.v; }
  function hhmmToMin(v) {
    if (isBlank(v)) return null;
    if (typeof v === "number") return v > 0 && v < 1 ? Math.round(v * 1440) : (v > 0 ? v : null);
    const m = String(v).trim().match(/^(\d{1,3})\s*[:시]\s*(\d{1,2})/);
    if (m) { const t = +m[1] * 60 + +m[2]; return t > 0 ? t : null; }
    const n = numOf(v); return n && n > 0 ? n : null;
  }

  // ── 파싱 ──
  // 반환: { records, items, report }.  opts.overrides: {항목키: 열 번호} (자동 인식 못 한 열을 사용자가 지정)
  function parse(aoa, opts) {
    opts = opts || {};
    const det = detect(aoa);
    const headerRow = opts.headerRow != null ? opts.headerRow : (det ? det.headerRow : -1);
    if (headerRow < 0) return null;
    const headers = (aoa[headerRow] || []).map((c) => (c == null ? "" : String(c).trim()));
    const idx = matchHeaders(headers, opts.overrides);
    if (idx.date == null) return { error: "채취일(날짜) 열을 찾지 못했습니다.", headers, idx, headerRow };
    const body = aoa.slice(headerRow + 1);
    const used = new Set(Object.values(idx));
    const zeros = {}; const raw = [];
    let skipped = 0, dup = 0;
    // 추가 항목(사용자가 고르면 볼 수 있는 기타 숫자 열): 값이 거의 숫자이고 0 이 아닌 값이 10건 이상
    const extras = [];
    headers.forEach((h, j) => {
      if (!h || used.has(j) || j === 0) return;
      let nn = 0, nz = 0, nonblank = 0;
      for (const r of body) { const v = r[j]; if (isBlank(v)) continue; nonblank++; const x = numOf(v); if (x != null) { nn++; if (x !== 0) nz++; } }
      if (nonblank && nn / nonblank >= 0.9 && nz >= 10) extras.push({ key: "x:" + h, name: h, unit: "", dec: 2, group: "기타 항목(파일의 다른 열)", col: j, extra: true });
    });
    const items = ITEMS.filter((it) => idx[it.key] != null).map((it) => Object.assign({}, it, { col: idx[it.key] })).concat(extras);
    for (const row of body) {
      if (!row || row.every(isBlank)) continue;
      const d = INGEST.parseDate(row[idx.date]);
      if (!d) { skipped++; continue; }
      const rec = { date: d.slice(0, 10), v: {}, ships: [], shipNotes: [], additive: "", lot: "" };
      if (idx.additive != null && !isBlank(row[idx.additive])) rec.additive = String(row[idx.additive]).trim();
      if (idx.lot != null && !isBlank(row[idx.lot])) rec.lot = String(row[idx.lot]).trim();
      for (const it of items) {
        const x = row[it.col]; let v;
        if (it.hhmm) v = hhmmToMin(x); else v = numOf(x);
        if (v != null && !(v > 0 || (it.zeroOk && v === 0))) { zeros[it.key] = (zeros[it.key] || 0) + 1; v = null; }   // 비율의 0 은 ‘투입 안 함’(실제 값)   // 0·음수 = 미시험
        rec.v[it.key] = v;
      }
      rec._ships = idx.ships != null ? parseShipsRaw(row[idx.ships]) : [];
      rec.shipRaw = idx.ships != null && !isBlank(row[idx.ships]) ? String(row[idx.ships]).replace(/\s+/g, " ").trim() : "";
      raw.push(rec);
    }
    // 선박명 정규화: 공백·마침표 제거, 괄호 주석 분리, ‘수성3’→‘수성3호’, 쉼표 없이 붙여 쓴 이름은 자주 나오는 선박명(5회 이상)으로 분리
    const vocab = new Set(); raw.forEach((r) => r._ships.forEach((s) => { if (/호$/.test(s.name)) vocab.add(s.name); }));
    const cnt = {}; raw.forEach((r) => r._ships.forEach((s) => { const n = canonShip(s.name, vocab); cnt[n] = (cnt[n] || 0) + 1; }));
    const known = new Set(Object.keys(cnt).filter((n) => /호$/.test(n) && cnt[n] >= 5));
    const forms = []; known.forEach((n) => { forms.push([n, n]); forms.push([n.replace(/호$/, ""), n]); });
    forms.sort((p, q) => q[0].length - p[0].length);
    const memoAll = (tok) => {
      const memo = new Map();
      const go = (i) => { if (i === tok.length) return []; if (memo.has(i)) return memo.get(i); let res = null;
        for (const [f, n] of forms) if (tok.startsWith(f, i)) { const rest = go(i + f.length); if (rest) { res = [n].concat(rest); break; } }
        memo.set(i, res); return res; };
      return go(0);
    };
    const partial = (tok) => {
      const names = []; let i = 0, left = "";
      while (i < tok.length) { const hit = forms.find(([f]) => tok.startsWith(f, i)); if (hit) { names.push(hit[1]); i += hit[0].length; } else { left += tok[i]; i++; } }
      return { names, left };
    };
    const shipCount = {}; const unsure = []; const unknownNames = {};
    raw.forEach((r) => {
      const seen = []; const notes = []; let ok = true; const add = (n) => { if (!seen.includes(n)) seen.push(n); };
      r._ships.forEach((s) => {
        s.notes.forEach((x) => notes.push(x));
        const n = canonShip(s.name, vocab);
        if (known.has(n)) { add(n); return; }
        const full = memoAll(s.name);
        if (full) { full.forEach(add); return; }
        const pt = partial(s.name);
        ok = false;
        if (pt.names.length) pt.names.forEach(add); else { add(n); unknownNames[n] = (unknownNames[n] || 0) + 1; }
      });
      r.ships = seen; r.shipNotes = [...new Set(notes)]; r.nShip = seen.length; r.shipsOk = ok && seen.length > 0;
      r.lowCl = r.shipNotes.some((x) => /저염/.test(x));
      if (!r.shipsOk && r.shipRaw) unsure.push({ date: r.date, raw: r.shipRaw });
      r.ships.forEach((n) => { shipCount[n] = (shipCount[n] || 0) + 1; });
      delete r._ships;
    });
    // 같은 날짜(+LOT) 중복 → 나중 행이 우선
    const map = new Map();
    raw.forEach((r) => { const k = r.lot || r.date; if (map.has(k)) dup++; map.set(k, r); });
    const records = [...map.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    const missing = ITEMS.filter((it) => idx[it.key] == null).map((it) => it.key);
    const dates = records.map((r) => r.date);
    return {
      records, items,
      report: {
        headerRow, rowsRead: records.length, rowsSkipped: skipped, duplicates: dup,
        period: dates.length ? [dates[0], dates[dates.length - 1]] : null,
        found: ITEMS.filter((it) => idx[it.key] != null).map((it) => ({ key: it.key, header: headers[idx[it.key]] })),
        missing, zeros, shipsFound: idx.ships != null, shipCount, nShips: Object.keys(shipCount).length, shipUnsure: unsure, unknownNames,
        extras: extras.map((e) => e.name), headers, idx,
      },
    };
  }

  // 기존 기록과 새 기록 병합(같은 LOT/날짜는 새 파일이 우선)
  function merge(oldRecs, newRecs) {
    const map = new Map();
    (oldRecs || []).forEach((r) => map.set(r.lot || r.date, r));
    newRecs.forEach((r) => map.set(r.lot || r.date, r));
    return [...map.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  }

  // ── 통계·관리도 ──
  const finite = (a) => a.filter((x) => typeof x === "number" && isFinite(x));
  const mean = (a) => { const v = finite(a); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : NaN; };
  function sd(a) { const v = finite(a); if (v.length < 2) return NaN; const m = mean(v); return Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / (v.length - 1)); }
  // 관리한계 UCL/LCL = 선택 기간 평균 ± 3×표본표준편차(기존 ‘공정 모니터링’ 탭과 동일). sigW(이동범위÷1.128)는 참고용으로 함께 계산.
  function stats(values, lim) {
    const v = finite(values); lim = lim || {};
    const m = mean(v), s = sd(v);
    let mr = 0; for (let i = 1; i < v.length; i++) mr += Math.abs(v[i] - v[i - 1]);
    const sigW = v.length > 1 ? mr / (v.length - 1) / 1.128 : NaN;
    const o = { n: v.length, mean: m, sd: s, sigW, ucl: m + 3 * s, lcl: m - 3 * s, min: v.length ? Math.min(...v) : NaN, max: v.length ? Math.max(...v) : NaN, cp: NaN, cpk: NaN };
    const hasL = lim.lsl != null && isFinite(lim.lsl), hasU = lim.usl != null && isFinite(lim.usl);
    if (isFinite(s) && s > 0 && (hasL || hasU)) {
      if (hasL && hasU) o.cp = (lim.usl - lim.lsl) / (6 * s);
      o.cpk = Math.min(hasU ? (lim.usl - m) / (3 * s) : Infinity, hasL ? (m - lim.lsl) / (3 * s) : Infinity);
    }
    return o;
  }
  // 점별 판정: out3(3σ 밖) · run(같은 쪽 9점 연속, Nelson 규칙 2) · spec(기준 이탈)
  function flags(points, st, lim) {
    lim = lim || {}; let run = 0, side = 0; const out = [];
    points.forEach((p) => {
      const v = p.v; const sgn = v > st.mean ? 1 : v < st.mean ? -1 : 0;
      if (sgn !== 0 && sgn === side) run++; else { run = sgn === 0 ? 0 : 1; side = sgn; }
      out.push({
        out3: isFinite(st.sd) && st.sd > 0 && (v > st.ucl || v < st.lcl),
        run: run >= 9,
        spec: (lim.lsl != null && v < lim.lsl) || (lim.usl != null && v > lim.usl),
      });
    });
    return out;
  }
  // 선박별(단독 시험만) 통계: 한 척만 출항한 날의 값 = 그 배의 시험값
  function byShip(records, key) {
    const g = {};
    records.forEach((r) => { if (r.nShip === 1 && r.shipsOk && r.v[key] != null) (g[r.ships[0]] = g[r.ships[0]] || []).push(r.v[key]); });
    return Object.keys(g).map((n) => ({ ship: n, n: g[n].length, mean: mean(g[n]), sd: sd(g[n]), min: Math.min(...g[n]), max: Math.max(...g[n]) })).sort((a, b) => b.n - a.n);
  }

  return { ITEMS, BY, KS_NOTE, norm, detect, parse, merge, matchHeaders, parseShipsRaw, canonShip, hhmmToMin, stats, flags, byShip, mean, sd };
});
