/* Blue365 QMS — 엑셀(.xlsx) 읽기 + QMS 통합 업로드 양식(LIMS 원본 형식) 해석·집계
 * 브라우저와 Node(18+) 공용 · 외부 라이브러리 없음.
 *   QMS.readXlsx(ArrayBuffer)        → { 시트명: [[행 값...], ...] }
 *   QMS.build(sheets, {now})          → 압축 분석 데이터셋 (화면이 쓰는 형식)
 * 시트 종류는 이름이 아니라 3행 머리글로 알아봅니다(시트 이름을 바꿔도 됨).
 */
(function (root) {
  'use strict';
  const VERSION = 1;

  /* ---------------- .xlsx 읽기 (ZIP + 정규식 XML) ---------------- */
  const td = new TextDecoder('utf-8');
  const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
  const unx = s => s.indexOf('&') < 0 ? s : s.replace(/&(#x[0-9a-fA-F]+|#\d+|amp|lt|gt|quot|apos);/g, (m, e) =>
    e[0] === '#' ? String.fromCodePoint(e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : ENT[e]);
  const attr = (s, n) => { const m = s.match(new RegExp('(?:^|\\s)' + n + '="([^"]*)"')); return m ? unx(m[1]) : null; };
  const colIdx = ref => { let n = 0; for (const ch of ref) { const c = ch.charCodeAt(0); if (c >= 65 && c <= 90) n = n * 26 + c - 64; else if (c >= 97 && c <= 122) n = n * 26 + c - 96; else break; } return n - 1; };

  async function inflate(u8) {
    if (typeof DecompressionStream === 'undefined') throw new Error('이 브라우저는 엑셀 직접 읽기를 지원하지 않습니다. 최신 Edge·Chrome을 써 주세요.');
    const out = await new Response(new Blob([u8]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer();
    return new Uint8Array(out);
  }
  async function readXlsx(buf) {
    const u8 = new Uint8Array(buf), dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    let eocd = -1;
    for (let i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error('엑셀(.xlsx) 파일 형식이 아닙니다. 엑셀에서 “Excel 통합 문서(.xlsx)”로 다시 저장해 주세요.');
    const n = dv.getUint16(eocd + 10, true); let off = dv.getUint32(eocd + 16, true); const files = {};
    for (let k = 0; k < n; k++) {
      if (off + 46 > u8.length || dv.getUint32(off, true) !== 0x02014b50) break;
      const method = dv.getUint16(off + 10, true), csize = dv.getUint32(off + 20, true), nlen = dv.getUint16(off + 28, true), xlen = dv.getUint16(off + 30, true), clen = dv.getUint16(off + 32, true), lho = dv.getUint32(off + 42, true);
      files[td.decode(u8.subarray(off + 46, off + 46 + nlen))] = { method, csize, lho }; off += 46 + nlen + xlen + clen;
    }
    const get = async name => {
      const f = files[name]; if (!f) return null;
      const st = f.lho + 30 + dv.getUint16(f.lho + 26, true) + dv.getUint16(f.lho + 28, true), data = u8.subarray(st, st + f.csize);
      if (f.method === 0) return td.decode(data);
      if (f.method !== 8) throw new Error('지원하지 않는 압축 방식의 엑셀 파일입니다.');
      return td.decode(await inflate(data));
    };
    const wb = await get('xl/workbook.xml'); if (!wb) throw new Error('엑셀 통합 문서 구조를 찾지 못했습니다.');
    const rels = {}; for (const m of ((await get('xl/_rels/workbook.xml.rels')) || '').matchAll(/<Relationship\b([^>]*)>/g)) rels[attr(m[1], 'Id')] = attr(m[1], 'Target');
    const sst = []; const ss = await get('xl/sharedStrings.xml');
    if (ss) for (const m of ss.matchAll(/<si>([\s\S]*?)<\/si>/g)) { let t = ''; for (const x of m[1].replace(/<rPh\b[\s\S]*?<\/rPh>/g, '').matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)) t += unx(x[1]); sst.push(t); }
    const out = {};
    for (const m of wb.matchAll(/<sheet\b([^>]*?)\/?>/g)) {
      const name = attr(m[1], 'name'), rid = attr(m[1], 'r:id'); let tg = rels[rid]; if (!tg) continue;
      tg = tg.replace(/^\//, ''); if (!tg.startsWith('xl/')) tg = 'xl/' + tg;
      const xml = await get(tg); if (!xml) continue;
      const rows = []; let rn = 0;
      for (const r of xml.matchAll(/<row\b([^>]*?)(?:\/>|>([\s\S]*?)<\/row>)/g)) {
        const ra = attr(r[1], 'r'), ri = ra ? (+ra - 1) : rn; rn = ri + 1;
        if (!r[2]) continue;
        const row = []; let cn = 0;
        for (const c of r[2].matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
          const ca = attr(c[1], 'r'), ci = ca ? colIdx(ca) : cn; cn = ci + 1;
          const t = attr(c[1], 't'), body = c[2] || ''; let v = null;
          const vm = body.match(/<v>([\s\S]*?)<\/v>/);
          if (t === 's') v = vm ? (sst[+vm[1]] ?? null) : null;
          else if (t === 'inlineStr') { v = ''; for (const x of body.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)) v += unx(x[1]); }
          else if (t === 'b') v = vm ? vm[1] === '1' : null;
          else if (t === 'str' || t === 'e') v = vm ? unx(vm[1]) : null;
          else v = vm && vm[1] !== '' ? Number(vm[1]) : null;
          row[ci] = v;
        }
        rows[ri] = Array.from(row, x => x === undefined ? null : x);
      }
      out[name] = Array.from(rows, x => x || []);
    }
    return out;
  }

  /* ---------------- 공통 변환 ---------------- */
  const H = s => String(s ?? '').replace(/\(.*?\)|\[.*?\]/g, '').replace(/₂/g, '2').replace(/₃/g, '3').replace(/[\s_·:]/g, '').toLowerCase();
  const pad = n => String(n).padStart(2, '0');
  // 날짜 → 'YYYY-MM-DD' (시간대 영향 없음) / 시각 → 분
  function dayOf(v) {
    if (v == null || v === '') return null;
    if (typeof v === 'number') { if (v < 1 || v > 2958465) return null; const d = new Date(Math.round(Math.floor(v) - 25569) * 864e5); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`; }
    if (v instanceof Date) return isNaN(v) ? null : `${v.getFullYear()}-${pad(v.getMonth() + 1)}-${pad(v.getDate())}`;
    const m = String(v).trim().replace(/[./]/g, '-').match(/^(\d{4})-(\d{1,2})-(\d{1,2})/); if (!m) return null;
    return `${m[1]}-${pad(+m[2])}-${pad(+m[3])}`;
  }
  function minOf(v, dateCell) {
    if (typeof v === 'number') { const f = v >= 1 ? v - Math.floor(v) : v; return Math.round(f * 1440) % 1440; }
    if (v instanceof Date) return v.getHours() * 60 + v.getMinutes();
    const m = String(v ?? '').trim().match(/^(\d{1,2}):(\d{2})/); if (m) return (+m[1]) * 60 + (+m[2]);
    if (typeof dateCell === 'number' && dateCell % 1) return Math.round((dateCell % 1) * 1440) % 1440;
    return 0;
  }
  const dayMs = d => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
  const tsOf = (d, min) => Math.round(dayMs(d) / 60000) + (min || 0);          // 시간대 없는 '분' 시각
  const num = v => { if (v == null || v === '') return null; const n = typeof v === 'number' ? v : Number(String(v).replace(/,/g, '').trim()); return isFinite(n) ? n : null; };
  const ana = v => { const n = num(v); return n == null || n <= 0 ? null : n; };   // 0·빈칸 = 미시험(결과 안 나옴), 음수 = 검출한계 아래 등 무효
  const r5 = v => v == null ? null : Number(v.toPrecision(5));
  // 시각·시간 → 분: 엑셀 시간(하루의 비율), 'H:MM' 문자열, 큰 수는 분으로 봄 (0·빈칸 = 미시험)
  const hmMin = v => { if (v == null || v === '') return null; if (typeof v === 'number') { const m = v < 1 ? v * 1440 : v <= 30 ? v * 60 : v; return m > 0 ? Math.round(m) : null; }
    const t = String(v).trim().match(/^(\d{1,2}):(\d{2})/); if (t) { const m = (+t[1]) * 60 + (+t[2]); return m > 0 ? m : null; } const n = num(v); return n ? (n < 1 ? Math.round(n * 1440) : n <= 30 ? Math.round(n * 60) : Math.round(n)) : null; };
  const txt = v => v == null ? '' : String(v).trim();

  function unitOf(s) {
    const c = txt(s).toUpperCase().replace(/\s+/g, '').replace(/_/g, '-'); let m;
    if ((m = c.match(/^([3-7])K(?:ILN)?$/))) return 'K' + m[1];
    if ((m = c.match(/^([3-7](?:-1)?)R\/?M$/))) return 'RM' + m[1].replace('-', '');
    if ((m = c.match(/^([2-7])C\/?M$/))) return 'CM' + m[1];
    return null;
  }
  const clkSilo = s => { const m = txt(s).replace(/\s/g, '').match(/^(\d)(?:-(\d))?호?$/); return m ? 'CS' + m[1] + (m[2] || '') : null; };
  const cemSilo = s => { const t = txt(s).replace(/\s/g, ''); let m; if ((m = t.match(/구내(\d+)호/))) return 'SL' + m[1]; if ((m = t.match(/부두(\d+)호/))) return 'PIER' + m[1]; if ((m = t.match(/^(\d+)호$/))) return 'SL' + m[1]; return null; };
  const rawSilo = s => { const m = txt(s).replace(/\s/g, '').match(/^([67])-([12])호?$/); return m ? 'RS' + m[1] + m[2] : null; };
  /* 시멘트구분 → 품종 (내수 = 1종). 알 수 없으면 null → 품명으로 판단 */
  function productByType(s) {
    const t = txt(s).replace(/\s/g, '');
    if (!t) return null;
    if (t === '내수' || /^1종/.test(t)) return '1종';
    if (/^3종$/.test(t)) return '3종';
    if (/S\/?C|고로|슬래그/i.test(t)) return /3종/.test(t) ? 'S/C3종' : 'S/C2종';
    if (/^2종$/.test(t)) return 'S/C2종';
    return null;
  }
  function product(s) {
    const t = txt(s).replace(/\s/g, '');
    if (/고로|슬래그|S\/?C/i.test(t)) return /3종/.test(t) ? 'S/C3종' : 'S/C2종';
    if (/^2종/.test(t)) return 'S/C2종';
    if (/3종/.test(t)) return '3종';
    if (/1종/.test(t)) return '1종';
    return t || null;
  }

  /* 시트 종류별 열 정의: [필드, 머리글 후보...] */
  const COLS = {
    raw: [['CaO', 'cao'], ['SiO2', 'sio2'], ['Al2O3', 'al2o3'], ['Fe2O3', 'fe2o3'], ['MgO', 'mgo'], ['SO3', 'so3'], ['K2O', 'k2o'], ['Na2O', 'na2o'], ['LOI', 'loi'], ['Cl', 'cl'], ['F', 'f'], ['KFUI', 'kfui'], ['tC3S', 'targetc3s'], ['LSF', 'lsf'], ['SM', 'sm'], ['IM', 'im']],
    res: [['r90', '90㎛', '90μm', '90um'], ['r200', '200㎛', '200μm', '200um']],
    dcs: [['feed', '원료투입량'], ['coal', '석탄투입량'], ['bzt', '소성대온도'], ['o2', '킬른입구o2'], ['co', '킬른입구co'], ['mload', '주모터부하'], ['pc', '하소로출구온도'], ['sec', '2차공기온도']],
    clk: [['CaO', 'cao'], ['SiO2', 'sio2'], ['Al2O3', 'al2o3'], ['Fe2O3', 'fe2o3'], ['MgO', 'mgo'], ['SO3', 'so3'], ['K2O', 'k2o'], ['Na2O', 'na2o'], ['fcao', 'f-cao', 'fcao'], ['Cl', 'cl'], ['F', 'f'], ['temp', '온도'], ['lw', '용중'],
          ['LSF', 'lsf'], ['SM', 'sm'], ['IM', 'im'], ['HM', 'hm'], ['TA', 'ta'], ['C3S', 'c3s'], ['mC3S', 'mc3s'], ['C2S', 'c2s'], ['C3A', 'c3a'], ['C4AF', 'c4af']],
    xrd: [['alite', 'alite', 'c3s'], ['belite', 'belite', 'c2s'], ['C3A', 'c3a'], ['C4AF', 'c4af'], ['fcao', 'f-cao'], ['peri', 'periclase'], ['cr', '총크롬'], ['cr6', '6가크롬']],
    cem: [['blaine', 'blaine'], ['r45', '45㎛', '45μm', '45um'], ['SO3', 'so3'], ['LOI', 'loi'], ['MgO', 'mgo'], ['CaO', 'cao'], ['SiO2', 'sio2'], ['Al2O3', 'al2o3'], ['Fe2O3', 'fe2o3'], ['Cl', 'cl'], ['fcao', 'f-cao'], ['ls', '석회석비율'], ['feed', '시멘트밀투입량'], ['temp', '원료온도']],
    cemop: [['feed', '시멘트밀투입량'], ['temp', '밀출구온도']],
    ship: [['ls', '석회석비율'], ['addr', '첨가재비율'], ['LOI', 'loi'], ['Al2O3', 'al2o3'], ['MgO', 'mgo'], ['SO3', 'so3'], ['Cl', 'cl'], ['TA', 'ta'], ['s1', '압축강도1일'], ['s3', '압축강도3일'], ['s7', '압축강도7일'], ['s28', '압축강도28일'], ['dens', '밀도'], ['r45', '45㎛'], ['blaine', 'blaine'], ['cons', '주도'], ['flow', 'flow'], ['ac', 'autoclave'], ['ist', '초결시간'], ['fst', '종결시간']]
  };
  const DAILY = {   // 일별 평균으로 남길 필드 (용량 절감)
    raw: ['LSF', 'SM', 'IM', 'MgO', 'SO3', 'K2O', 'Cl'], feed: ['LSF', 'SM', 'IM'], res: ['r90', 'r200'], dcs: ['feed', 'coal', 'bzt', 'o2', 'co', 'mload', 'pc', 'sec'],
    clk: ['fcao', 'LSF', 'SM', 'IM', 'C3S', 'mC3S', 'C2S', 'C3A', 'MgO', 'SO3', 'K2O', 'Cl'], xrd: ['alite', 'belite', 'C3A', 'C4AF', 'fcao', 'peri', 'cr', 'cr6'],
    cem: ['blaine', 'r45', 'SO3', 'LOI', 'MgO'], raws: ['LSF', 'SM', 'IM'], cemop: ['feed', 'temp']
  };

  function kindOf(h) {
    const s = new Set(h);
    if (s.has('limslot.no') || s.has('limslotno')) return 'ship';
    if (s.has('합부판정') || (s.has('로트번호') && s.has('품명'))) return 'acc';
    if (s.has('alite') || s.has('belite')) return 'xrd';
    if (s.has('소성대온도') || s.has('원료투입량') || s.has('석탄투입량')) return 'dcs';
    if (s.has('90㎛') || s.has('90μm')) return 'res';
    if (s.has('blaine') && s.has('공정구분')) return 'cem';
    if (s.has('공정구분') && (s.has('시멘트밀투입량') || s.has('밀출구온도'))) return 'cemop';   // 시멘트밀 운전값(DCS)
    if (s.has('f-cao') && s.has('cao') && s.has('공정구분')) return 'clk';
    if (s.has('cao') && s.has('공정구분') && (s.has('kfui') || s.has('targetc3s') || s.has('석회석') || s.has('샘플위치'))) return 'raw';
    return null;
  }
  const modules = o => {
    const { CaO: C, SiO2: S, Al2O3: A, Fe2O3: F } = o; if ([C, S, A, F].some(v => v == null) || !S || !F) return {};
    return { LSF: C / (2.8 * S + 1.18 * A + 0.65 * F) * 100, SM: S / (A + F), IM: A / F };
  };
  /* Bogue (LIMS와 같은 식 — 확인: 클링커 1만 5천여 행에서 LIMS 계산값과 일치)
     C3S = 4.071CaO − 7.600SiO2 − 6.718Al2O3 − 1.430Fe2O3 (SO3·f-CaO 보정 없음), mC3S = f-CaO 차감 */
  const bogue = o => {
    const { CaO: C, SiO2: S, Al2O3: A, Fe2O3: F } = o; if ([C, S, A, F].some(v => v == null)) return {};
    const c3s = 4.071 * C - 7.600 * S - 6.718 * A - 1.430 * F;
    return { C3S: c3s, mC3S: o.fcao != null ? c3s - 4.071 * o.fcao : null, C2S: 2.867 * S - 0.7544 * c3s, C3A: 2.650 * A - 1.692 * F, C4AF: 3.043 * F };
  };
  /* LIMS 계산값 열이 없을 때만 계산값으로 채움 (열은 있는데 0·음수면 미시험·무효로 그대로 둠) */
  const fill = (o, calc, has) => { for (const [k, v] of Object.entries(calc)) if (!has.has(k)) o[k] = v != null && isFinite(v) && v > 0 ? v : null; };

  /* ---------------- 해석·집계 ---------------- */
  function build(sheets, opt = {}) {
    const now = opt.now ? new Date(opt.now) : new Date();
    const maxDay = dayOf(new Date(now.getTime() + 864e5));
    const warn = [], counts = {}, recs = { raw: [], res: [], dcs: [], clk: [], xrd: [], cem: [], cemop: [], ship: [], acc: [] }, oddDates = [];
    let future = 0, swapped = 0, noUnit = 0, badCode = 0;
    for (const [name, rows] of Object.entries(sheets || {})) {
      if (!Array.isArray(rows)) continue;
      let hr = -1, kind = null, hdr = null;
      for (let r = 0; r < Math.min(8, rows.length); r++) { const h = (rows[r] || []).map(H); if (h.includes('채취일') || h.includes('로트번호')) { const k = kindOf(h); if (k) { hr = r; kind = k; hdr = h; break; } } }
      if (!kind) { if (!/사용법|공정구분|항목사전|안내|readme/i.test(name)) warn.push(`‘${name}’ 시트는 양식과 맞지 않아 건너뛰었습니다.`); continue; }
      const ix = k => hdr.indexOf(k), find = als => { for (const a of als) { const i = hdr.indexOf(a); if (i >= 0) return i; } return -1; };
      const cDay = ix('채취일') >= 0 ? ix('채취일') : ix('검사일'), cTime = ix('채취시간'), cUnit = ix('공정구분'), cName = ix('품명');
      const cPos = ix('샘플위치'), cRsil = find(['투입사일로', '투입silo']), cCs = ix('클링커투입사일로'), cSs = ix('시멘트투입사일로');
      const cols = (COLS[kind] || []).map(([f, ...a]) => [f, find(a)]).filter(x => x[1] >= 0), has = new Set(cols.map(c => c[0]));
      const cCtype = find(['클링커구분', '시멘트구분']);
      let n = 0;const seen = [];
      for (let r = hr + 1; r < rows.length; r++) {
        const row = rows[r]; if (!row || !row.length) continue;
        const day = dayOf(row[cDay]); if (!day) continue;
        seen.push([r + 1, day]);
        if (day > maxDay) { future++; continue; }
        const o = { day, ts: tsOf(day, cTime >= 0 ? minOf(row[cTime], row[cDay]) : minOf(null, row[cDay])) };
        if (kind === 'acc') {
          o.kind = hdr.includes('결정수') ? '석고' : hdr.includes('품위구분') ? '고령토' : '원료';
          o.name = txt(row[cName]).split(/\s+-/)[0].trim() || '(품명 없음)'; o.judge = txt(row[ix('합부판정')]); o.vendor = txt(row[ix('거래처')]);
          recs.acc.push(o); n++; continue;
        }
        if (kind === 'ship') {
          o.lot = txt(row[find(['limslot.no', 'limslotno'])]); o.product = product(row[cName]); o.add = txt(row[ix('첨가재명칭')]); o.ships = txt(row[ix('비고')]);
          for (const [f, i] of cols) o[f] = f === 'fst' ? hmMin(row[i]) : ana(row[i]);
          recs.ship.push(o); n++; continue;
        }
        const unit = unitOf(row[cUnit]); if (!unit) { if (/^SA1KL\d$/i.test(txt(row[cUnit]))) badCode++; else noUnit++; continue; }   // SA1KL3·SA1KL6 = 입력 오류 코드
        o.unit = unit; if (cName >= 0) o.grade = txt(row[cName]); if (cCtype >= 0) o.ctype = txt(row[cCtype]);
        if (kind === 'cemop') { for (const [f, i] of cols) o[f] = num(row[i]); recs.cemop.push(o); n++; continue; }   // 운전값: 0은 실제 값(정지)
        for (const [f, i] of cols) o[f] = kind === 'dcs' ? num(row[i]) : ana(row[i]);
        if (kind === 'cem') {   // LIMS 내려받기에서 Blaine·45㎛ 값이 서로 바뀌어 들어오는 경우 자동 보정
          if (o.blaine != null && o.r45 != null && o.blaine < 100 && o.r45 > 1000) { const t = o.blaine; o.blaine = o.r45; o.r45 = t; swapped++; }
          o.product = productByType(o.ctype) || product(row[cName]); o.silo = cemSilo(row[cSs]); o.siloRaw = txt(row[cSs]);   // 시멘트구분 우선
          if (o.feed != null || o.temp != null) recs.cemop.push({ day: o.day, ts: o.ts, unit: o.unit, feed: o.feed, temp: o.temp });   // 예전 양식(시멘트 시트에 투입량·원료온도)
        }
        if (kind === 'raw') { fill(o, modules(o), has); o.feed = /요입/.test(txt(row[cPos])) || unit[0] === 'K'; o.rsilo = rawSilo(row[cRsil]); }
        if (kind === 'clk') { fill(o, Object.assign(modules(o), bogue(o)), has); o.silo = clkSilo(row[cCs]); }
        recs[kind].push(o); n++;
      }
      counts[name] = n;
      for (let i = 1; i < seen.length - 1; i++) {   // 앞뒤 행 날짜는 서로 가까운데(7일 이내) 이 행만 60일 넘게 떨어진 경우
        const a = dayMs(seen[i - 1][1]), b = dayMs(seen[i + 1][1]), x = dayMs(seen[i][1]);
        if (Math.abs(b - a) <= 7 * 864e5 && Math.abs(x - a) > 60 * 864e5 && Math.abs(x - b) > 60 * 864e5) oddDates.push(`${name} ${seen[i][0]}행(${seen[i][1]})`);
      }
    }
    if (future) warn.push(`미래 날짜(${maxDay} 이후) ${future}행은 날짜 오류로 보고 제외했습니다.`);
    if (oddDates.length) warn.push(`앞뒤 행과 동떨어진 날짜 ${oddDates.length}건 — 확인해 주세요: ${oddDates.slice(0, 6).join(', ')}${oddDates.length > 6 ? ' 외' : ''}`);
    if (swapped) warn.push(`시멘트 시트의 Blaine·45㎛ 값이 서로 바뀐 ${swapped}행을 자동으로 바로잡았습니다.`);
    if (badCode) warn.push(`입력 오류 공정구분(SA1KL…) ${badCode}행은 제외했습니다.`);
    if (noUnit) warn.push(`공정구분(호기·밀)을 알 수 없는 ${noUnit}행은 건너뛰었습니다.`);

    const all = [...recs.raw, ...recs.clk, ...recs.cem, ...recs.res, ...recs.xrd, ...recs.dcs, ...recs.ship];
    const main = [...recs.raw, ...recs.clk, ...recs.cem];
    const to = all.reduce((a, o) => o.day > a ? o.day : a, '0000'), from = (main.length ? main : all).reduce((a, o) => o.day < a ? o.day : a, '9999');
    const toMs = all.length ? dayMs(to) : 0, recentFrom = Math.round((toMs - 13 * 864e5) / 60000), statFrom = Math.round((toMs - 89 * 864e5) / 60000);
    const streams = {};
    const addStream = (key, list, fields, dailyFields, byProduct) => {
      if (!list.length) return;
      list.sort((a, b) => a.ts - b.ts);
      const days = new Map();
      for (const o of list) { let d = days.get(o.day); if (!d) { d = { n: 0, s: {}, c: {} }; days.set(o.day, d); } d.n++; for (const f of dailyFields) if (o[f] != null && isFinite(o[f])) { d.s[f] = (d.s[f] || 0) + o[f]; d.c[f] = (d.c[f] || 0) + 1; } }
      const st = {}, stp = {};
      const acc = (tgt, o) => { for (const f of fields) if (o[f] != null && isFinite(o[f])) { const a = tgt[f] || (tgt[f] = [0, 0, 0]); a[0] += o[f]; a[1] += o[f] * o[f]; a[2]++; } };
      for (const o of list) if (o.ts >= statFrom) { acc(st, o); if (byProduct && o.product) acc(stp[o.product] || (stp[o.product] = {}), o); }
      const fin = t => { for (const f in t) { const [s, q, c] = t[f]; const m = s / c; t[f] = [r5(m), r5(Math.sqrt(Math.max(0, q / c - m * m))), c]; } return t; };
      fin(st); for (const p in stp) fin(stp[p]);
      const last = list[list.length - 1];
      streams[key] = {
        f: fields, df: dailyFields,
        d: [...days.entries()].map(([day, d]) => [day, d.n, ...dailyFields.map(f => d.c[f] ? r5(d.s[f] / d.c[f]) : null)]),
        r: list.filter(o => o.ts >= recentFrom).slice(-400).map(o => [o.ts, ...fields.map(f => o[f] == null ? null : r5(o[f])), o.product || o.grade || '', o.silo || o.rsilo || '']),
        st, stp: byProduct ? stp : undefined,
        last: { ts: last.ts, grade: last.grade || '', product: last.product || '', silo: last.silo || '', siloRaw: last.siloRaw || '' }
      };
    };
    const group = (list, keyf) => { const m = {}; for (const o of list) { const k = keyf(o); if (k) (m[k] || (m[k] = [])).push(o); } return m; };
    const RAWF = ['CaO', 'SiO2', 'Al2O3', 'Fe2O3', 'MgO', 'SO3', 'K2O', 'Na2O', 'LOI', 'Cl', 'LSF', 'SM', 'IM'];
    for (const [u, l] of Object.entries(group(recs.raw.filter(o => !o.feed), o => o.unit))) addStream('raw:' + u, l, RAWF, DAILY.raw);
    for (const [u, l] of Object.entries(group(recs.raw.filter(o => o.feed), o => o.unit))) addStream('feed:' + u, l, ['LSF', 'SM', 'IM', 'CaO', 'SiO2', 'Al2O3', 'Fe2O3', 'MgO'], DAILY.feed);
    for (const [s, l] of Object.entries(group(recs.raw.filter(o => !o.feed), o => o.rsilo))) addStream('raws:' + s, l, ['LSF', 'SM', 'IM'], DAILY.raws);
    for (const [u, l] of Object.entries(group(recs.res, o => o.unit))) addStream('res:' + u, l, ['r90', 'r200'], DAILY.res);
    for (const [u, l] of Object.entries(group(recs.dcs, o => o.unit))) addStream('dcs:' + u, l, DAILY.dcs, DAILY.dcs);
    for (const [u, l] of Object.entries(group(recs.clk, o => o.unit))) addStream('clk:' + u, l, ['CaO', 'SiO2', 'Al2O3', 'Fe2O3', 'MgO', 'SO3', 'K2O', 'Na2O', 'fcao', 'Cl', 'F', 'temp', 'LSF', 'SM', 'IM', 'C3S', 'mC3S', 'C2S', 'C3A', 'C4AF'], DAILY.clk);
    for (const [u, l] of Object.entries(group(recs.xrd, o => o.unit))) addStream('xrd:' + u, l, DAILY.xrd, DAILY.xrd);
    for (const [u, l] of Object.entries(group(recs.cem, o => o.unit))) addStream('cem:' + u, l, ['blaine', 'r45', 'SO3', 'LOI', 'MgO', 'CaO', 'SiO2', 'Al2O3', 'Fe2O3', 'Cl'], DAILY.cem, true);
    for (const [u, l] of Object.entries(group(recs.cemop, o => o.unit))) addStream('cemop:' + u, l, DAILY.cemop, DAILY.cemop);

    // 클링커 사일로 · 시멘트 사일로: 마지막 투입 내역과 최근 30일 품명 구성
    const d30 = Math.round((toMs - 29 * 864e5) / 60000);
    const csilo = {}, ssilo = {};
    for (const o of recs.clk) if (o.silo) { const s = csilo[o.silo] || (csilo[o.silo] = { n30: {}, ts: 0 }); if (o.ts >= s.ts) Object.assign(s, { ts: o.ts, grade: o.grade, kiln: o.unit, ctype: o.ctype || '' }); if (o.ts >= d30) s.n30[o.grade || '-'] = (s.n30[o.grade || '-'] || 0) + 1; }
    for (const o of recs.cem) if (o.silo) { const s = ssilo[o.silo] || (ssilo[o.silo] = { n30: {}, ts: 0 }); if (o.ts >= s.ts) Object.assign(s, { ts: o.ts, product: o.product, mill: o.unit, label: o.siloRaw, ctype: o.ctype || '' }); if (o.ts >= d30) s.n30[o.product || '-'] = (s.n30[o.product || '-'] || 0) + 1; }

    // 출하 시멘트 로트 (전체)
    const SF = ['ls', 'addr', 'LOI', 'Al2O3', 'MgO', 'SO3', 'Cl', 'TA', 's1', 's3', 's7', 's28', 'dens', 'r45', 'blaine', 'cons', 'flow', 'ac', 'ist', 'fst'];
    recs.ship.sort((a, b) => a.ts - b.ts);
    const ship = { f: SF, rows: recs.ship.map(o => [o.day, o.lot, o.product, o.add, o.ships, ...SF.map(f => o[f] == null ? null : r5(o[f]))]) };

    // 인수검사: 종류·품명별 로트 수
    const accMap = new Map();
    for (const o of recs.acc) { const k = o.kind + '|' + o.name; const a = accMap.get(k) || { kind: o.kind, name: o.name, n: 0, n30: 0, last: '', pass: 0, fail: 0 }; a.n++; if (o.ts >= d30) a.n30++; if (o.day > a.last) a.last = o.day; if (/불/.test(o.judge)) a.fail++; else if (/합/.test(o.judge)) a.pass++; accMap.set(k, a); }
    const accept = [...accMap.values()].sort((a, b) => b.n30 - a.n30 || b.n - a.n);
    const accTo = recs.acc.reduce((a, o) => o.day > a ? o.day : a, '');

    // 최근 시료 (시료 목록용)
    const samples = [];
    const pushS = (list, f) => list.slice(-60).forEach(o => samples.push(f(o)));
    pushS(recs.clk, o => [o.ts, o.unit, `${o.unit.slice(1)}호 클링커 XRF · f-CaO ${o.fcao == null ? '-' : o.fcao}`, o.grade || '']);
    pushS(recs.cem, o => [o.ts, o.unit, `${o.unit.slice(2)}호 C/M ${o.product || ''} · Blaine ${o.blaine == null ? '-' : Math.round(o.blaine)}`, o.siloRaw || '']);
    pushS(recs.raw, o => [o.ts, o.unit, `${o.unit.startsWith('K') ? o.unit.slice(1) + '호 요입' : o.unit.slice(2).replace('51', '5-1') + '호 R/M'} 원료 · LSF ${o.LSF == null ? '-' : o.LSF.toFixed(1)}`, '']);
    samples.sort((a, b) => b[0] - a[0]);

    return {
      v: VERSION, from: all.length ? from : null, to: all.length ? to : null, accTo, built: new Date().toISOString(),
      counts, warn, total: Object.values(counts).reduce((a, b) => a + b, 0),
      streams, csilo, ssilo, ship, accept, samples: samples.slice(0, 12)
    };
  }

  const api = { VERSION, readXlsx, build, unitOf, product, H };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.QMS = api;
})(typeof window !== 'undefined' ? window : globalThis);
