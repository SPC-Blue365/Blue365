/* 출하속보(出荷速報) PDF 읽기 — 브라우저·Node 공용, 외부 라이브러리 없음
 *   SOKBO.read(ArrayBuffer|Uint8Array) → Promise<{ok, data, warn[]}>
 *   엑셀에서 PDF로 저장한 출하속보(셀마다 BT … Tm … TJ … ET)를 좌표와 함께 읽어 표를 다시 만든다.
 *   글꼴: TrueType(WinAnsi) + Type0(Identity-H, ToUnicode) */
(function (root) {
  'use strict';
  const isNode = typeof module !== 'undefined' && module.exports;

  /* ── 압축 풀기 (FlateDecode = zlib) */
  async function inflate(u8) {
    if (isNode) return new Uint8Array(require('zlib').inflateSync(Buffer.from(u8)));
    const ds = new DecompressionStream('deflate');
    const out = new Response(new Blob([u8]).stream().pipeThrough(ds));
    return new Uint8Array(await out.arrayBuffer());
  }
  const latin = u8 => { let s = ''; for (let i = 0; i < u8.length; i += 8192) s += String.fromCharCode.apply(null, u8.subarray(i, i + 8192)); return s; };

  /* ── PDF 객체 읽기 (직접 객체 + 객체 스트림) */
  async function objects(u8) {
    const raw = latin(u8), O = {}, jobs = [];
    const re = /(\d+)\s+0\s+obj\b/g; let m;
    const starts = [];
    while ((m = re.exec(raw))) starts.push([+m[1], m.index + m[0].length]);
    for (const [n, at] of starts) {
      const end = raw.indexOf('endobj', at); if (end < 0) continue;
      let body = raw.slice(at, end), stream = null;
      const si = body.search(/\bstream\r?\n/);
      if (si >= 0) {
        const dict = body.slice(0, si), lm = dict.match(/\/Length\s+(\d+)(\s+0\s+R)?/);
        const s0 = at + si + body.slice(si).match(/^stream\r?\n/)[0].length;
        let len = lm && !lm[2] ? +lm[1] : raw.indexOf('endstream', s0) - s0;
        stream = u8.subarray(s0, s0 + len);
        if (/\/FlateDecode/.test(dict)) { const raw0 = stream; stream = null; jobs.push(inflate(raw0).then(x => { O[n].stream = x; }, () => {})); }   // 한꺼번에 풀기 (화면 그리기 사이사이 기다리지 않게)
        body = dict;
      }
      O[n] = { dict: body, stream };
    }
    await Promise.all(jobs);
    // 객체 스트림 안의 객체
    for (const k of Object.keys(O)) {
      const o = O[k]; if (!o.stream || !/\/Type\s*\/ObjStm/.test(o.dict)) continue;
      const N = +(o.dict.match(/\/N\s+(\d+)/) || [])[1], F = +(o.dict.match(/\/First\s+(\d+)/) || [])[1];
      const s = latin(o.stream), hdr = s.slice(0, F).trim().split(/\s+/).map(Number);
      for (let i = 0; i < N; i++) {
        const num = hdr[2 * i], off = F + hdr[2 * i + 1], nx = i + 1 < N ? F + hdr[2 * i + 3] : s.length;
        if (!O[num]) O[num] = { dict: s.slice(off, nx), stream: null };
      }
    }
    return O;
  }
  const ref = (d, key) => { const m = d.match(new RegExp('/' + key + '\\s+(\\d+)\\s+0\\s+R')); return m ? +m[1] : null; };

  /* ── ToUnicode CMap → {코드(hex): 글자} */
  function cmap(txt) {
    const map = {}, hex2s = h => { let s = ''; for (let i = 0; i < h.length; i += 4) s += String.fromCharCode(parseInt(h.substr(i, 4), 16)); return s; };
    for (const b of txt.split('beginbfchar').slice(1)) {
      const body = b.split('endbfchar')[0], re = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g; let m;
      while ((m = re.exec(body))) map[m[1].toUpperCase().padStart(4, '0')] = hex2s(m[2]);
    }
    for (const b of txt.split('beginbfrange').slice(1)) {
      const body = b.split('endbfrange')[0], re = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<([0-9A-Fa-f]+)>|\[([^\]]*)\])/g; let m;
      while ((m = re.exec(body))) {
        const a = parseInt(m[1], 16), z = parseInt(m[2], 16);
        if (m[4]) { const base = parseInt(m[4].slice(-4), 16), pre = m[4].slice(0, -4); for (let c = a; c <= z; c++) map[c.toString(16).toUpperCase().padStart(4, '0')] = hex2s(pre + (base + c - a).toString(16).padStart(4, '0')); }
        else { const arr = m[5].match(/<([0-9A-Fa-f]+)>/g) || []; arr.forEach((h, i) => { map[(a + i).toString(16).toUpperCase().padStart(4, '0')] = hex2s(h.slice(1, -1)); }); }
      }
    }
    return map;
  }

  /* ── 페이지 글자 → [{x, y, t, s}]  (q/Q·cm·Do(Form XObject)·BT/ET·Tf·Tm·Td·TJ/Tj 해석) */
  const mul = (m, n) => [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3], m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3], m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]];
  function tokens(s) {
    const out = []; let i = 0; const n = s.length;
    while (i < n) {
      const c = s[i];
      if (/\s/.test(c)) { i++; continue; }
      if (c === '%') { while (i < n && s[i] !== '\n' && s[i] !== '\r') i++; continue; }
      if (c === '(') { let d = 0, j = i; for (; j < n; j++) { if (s[j] === '\\') { j++; continue; } if (s[j] === '(') d++; else if (s[j] === ')' && --d === 0) break; } out.push({ s: s.slice(i, j + 1) }); i = j + 1; continue; }
      if (c === '<' && s[i + 1] === '<') { out.push({ o: '<<' }); i += 2; continue; }
      if (c === '>' && s[i + 1] === '>') { out.push({ o: '>>' }); i += 2; continue; }
      if (c === '<') { const j = s.indexOf('>', i); out.push({ s: s.slice(i, j + 1) }); i = j + 1; continue; }
      if (c === '[' || c === ']' || c === '{' || c === '}') { out.push({ o: c }); i++; continue; }
      if (c === '/') { let j = i + 1; while (j < n && !/[\s\/\[\]<>()%{}]/.test(s[j])) j++; out.push({ name: s.slice(i + 1, j) }); i = j; continue; }
      let j = i; while (j < n && !/[\s\/\[\]<>()%{}]/.test(s[j])) j++;
      const w = s.slice(i, j); i = j || i + 1;
      if (/^[-+]?(\d+\.?\d*|\.\d+)$/.test(w)) out.push({ n: +w }); else out.push({ op: w });
    }
    return out;
  }
  async function textItems(u8) {
    const O = await objects(u8);
    const page = Object.keys(O).map(Number).find(n => /\/Type\s*\/Page\b(?!s)/.test(O[n].dict));
    if (page == null) throw new Error('PDF 페이지를 찾지 못했습니다');
    const fontCache = {};
    const fontOf = n => {
      if (fontCache[n]) return fontCache[n];
      const d = (O[n] || {}).dict || '', tu = ref(d, 'ToUnicode');
      return (fontCache[n] = { cid: /Identity-H/.test(d), map: tu && O[tu] && O[tu].stream ? cmap(latin(O[tu].stream)) : null });
    };
    const resOf = dict => {   // {fonts:{F1:obj}, xo:{Meta22:obj}}
      const r = { fonts: {}, xo: {} };
      const grab = (key, into) => { const m = dict.match(new RegExp('/' + key + '\\s*<<([^>]*)>>')); if (m) { const re = /\/(\w+)\s+(\d+)\s+0\s+R/g; let x; while ((x = re.exec(m[1]))) into[x[1]] = +x[2]; } };
      grab('Font', r.fonts); grab('XObject', r.xo); return r;
    };
    const items = [];
    const dec = (f, part) => {
      if (part[0] === '<') {
        const h = part.slice(1, -1).replace(/\s/g, '').toUpperCase();
        if (f.cid) { let s = ''; for (let i = 0; i < h.length; i += 4) { const c = h.substr(i, 4); s += f.map && f.map[c] != null ? f.map[c] : ''; } return s; }
        let s = ''; for (let i = 0; i < h.length; i += 2) s += String.fromCharCode(parseInt(h.substr(i, 2), 16)); return s;
      }
      let s = part.slice(1, -1).replace(/\\([nrtbf()\\]|[0-7]{1,3})/g, (_, e) => ({ n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', '(': '(', ')': ')', '\\': '\\' }[e] ?? String.fromCharCode(parseInt(e, 8))));
      if (f.cid && f.map) { let o = ''; for (let i = 0; i + 1 < s.length; i += 2) { const c = ((s.charCodeAt(i) << 8) | s.charCodeAt(i + 1)).toString(16).toUpperCase().padStart(4, '0'); o += f.map[c] ?? ''; } return o; }
      return s;
    };
    const run = (content, res, ctm0, depth) => {
      if (depth > 4) return;
      const T = tokens(content); let st = { ctm: ctm0, font: null, size: 0 }; const stack = [];
      let tm = [1, 0, 0, 1, 0, 0], tlm = tm, args = [];
      for (let k = 0; k < T.length; k++) {
        const t = T[k];
        if (t.op == null) {
          if (t.o === '[') { const arr = []; k++; for (; k < T.length && T[k].o !== ']'; k++) arr.push(T[k]); args.push({ arr }); continue; }
          if (t.o === '<<') { let d = 1; k++; for (; k < T.length && d; k++) { if (T[k].o === '<<') d++; else if (T[k].o === '>>') d--; } k--; args.push({ dict: 1 }); continue; }
          args.push(t); continue;
        }
        const op = t.op, nums = args.filter(a => a.n != null).map(a => a.n);
        switch (op) {
          case 'q': stack.push({ ...st }); break;
          case 'Q': st = stack.pop() || st; break;
          case 'cm': if (nums.length >= 6) st.ctm = mul(nums.slice(-6), st.ctm); break;
          case 'BT': tm = tlm = [1, 0, 0, 1, 0, 0]; break;
          case 'Tf': { const nm = args.find(a => a.name); if (nm) { st.font = res.fonts[nm.name] != null ? fontOf(res.fonts[nm.name]) : null; } st.size = nums[nums.length - 1] || st.size; break; }
          case 'Tm': if (nums.length >= 6) tm = tlm = nums.slice(-6); break;
          case 'Td': case 'TD': if (nums.length >= 2) tm = tlm = mul([1, 0, 0, 1, nums[nums.length - 2], nums[nums.length - 1]], tlm); break;
          case 'TJ': case 'Tj': case "'": case '"': {
            if (!st.font) break;
            const parts = op === 'TJ' ? ((args.find(a => a.arr) || {}).arr || []).filter(a => a.s) : args.filter(a => a.s);
            let s = ''; for (const p of parts) s += dec(st.font, p.s);
            s = s.replace(/\u0000/g, '');
            if (s.trim()) { const m = mul(tm, st.ctm); items.push({ x: +m[4].toFixed(2), y: +m[5].toFixed(2), t: s, s: +(st.size * Math.abs(m[3] || 1)).toFixed(2) }); }
            break; }
          case 'Do': {
            const nm = args.find(a => a.name), n = nm && res.xo[nm.name], xo = n != null && O[n];
            if (xo && xo.stream && /\/Subtype\s*\/Form/.test(xo.dict)) {
              const mm = xo.dict.match(/\/Matrix\s*\[\s*([^\]]+)\]/), M = mm ? mm[1].trim().split(/\s+/).map(Number) : [1, 0, 0, 1, 0, 0];
              const r2 = resOf(xo.dict); if (!Object.keys(r2.fonts).length) r2.fonts = res.fonts;
              run(latin(xo.stream), r2, mul(M, st.ctm), depth + 1);
            }
            break; }
        }
        args = [];
      }
    };
    const pd = O[page].dict, cref = pd.match(/\/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)/);
    const cids = cref ? (cref[1].match(/(\d+)\s+0\s+R/g) || []).map(x => +x.split(/\s/)[0]) : [];
    // 페이지 Resources 가 간접 객체일 수 있음
    let rdict = pd; const rr = ref(pd, 'Resources'); if (rr != null && O[rr]) rdict = O[rr].dict;
    const res = resOf(rdict);
    run(cids.map(n => O[n] && O[n].stream ? latin(O[n].stream) : '').join('\n'), res, [1, 0, 0, 1, 0, 0], 0);
    return items;
  }

  /* ── 좌표 → 줄 (y가 가까운 글자끼리, 위에서 아래로) */
  function rows(items, tol = 2.2) {
    const it = items.slice().sort((a, b) => b.y - a.y || a.x - b.x), out = [];
    for (const o of it) { const r = out.find(r => Math.abs(r.y - o.y) <= tol); if (r) r.c.push(o); else out.push({ y: o.y, c: [o] }); }
    out.forEach(r => r.c.sort((a, b) => a.x - b.x));
    return out.sort((a, b) => b.y - a.y);
  }

  /* ── 표 해석 ─────────────────────────────────────────── */
  const num = t => { const s = String(t).replace(/[,\s]/g, ''); if (!s || /^[-–=]+$/.test(s)) return null; const m = s.match(/^-?\d+(\.\d+)?$/); return m ? +s : null; };
  const W = o => { let w = 0; for (const ch of o.t) w += /[ᄀ-ᇿ　-鿿가-힯豈-﫿]/.test(ch) ? 1 : .5; return w * o.s; };
  const cx = o => o.x + W(o) / 2;
  const nearest = (o, cols) => { let b = null, d = 1e9; for (const c of cols) { const k = Math.abs(cx(o) - c.cx); if (k < d) { d = k; b = c; } } return b; };
  const sp = t => t.replace(/\s+/g, '');
  const pad2 = n => String(n).padStart(2, '0');

  function parse(items) {
    const R = rows(items, 1.2), warn = [];
    const all = R.flatMap(r => r.c);
    const find = re => R.find(r => r.c.some(o => re.test(sp(o.t))));
    const yOf = re => { const r = find(re); return r ? r.y : null; };
    // 보고일
    let date = null, weather = '';
    for (const o of all) { const m = o.t.match(/(20\d\d)\.\s*(\d{1,2})\.\s*(\d{1,2})\s*(?:\(([^)]*)\))?/); if (m) { date = `${m[1]}-${pad2(m[2])}-${pad2(m[3])}`; weather = (m[4] || '').split(/[,，]/).slice(1).join(',').trim(); break; } }
    if (!date) throw new Error('출하속보 날짜(예: 2026. 11.11)를 찾지 못했습니다');
    if (!all.some(o => /出荷速報|출하속보/.test(sp(o.t))) && !find(/^3\.선박$/)) throw new Error('출하속보 양식이 아닙니다');
    const [Y, M, D] = date.split('-').map(Number);
    // "11/02:48" → 날짜·시각 (보고일 기준 앞뒤 달 보정)
    const when = (t, defH) => {
      const m = String(t || '').match(/(\d{1,2})\s*\/\s*(\d{1,2})(?::(\d{2}))?/); if (!m) return null;
      let a = +m[1], b = +m[2], c = m[3], y = Y, mo = M, d, hh, mm;
      if (c != null) { d = a; hh = b; mm = +c; } else { mo = a; d = b; hh = defH || 0; mm = 0; }
      if (c != null) { if (d - D > 20) mo--; else if (D - d > 20) mo++; }
      if (mo < 1) { mo += 12; y--; } if (mo > 12) { mo -= 12; y++; }
      return `${y}-${pad2(mo)}-${pad2(d)}T${pad2(hh)}:${pad2(mm)}`;
    };
    const out = { v: 1, kind: 'sokbo', date, weather, made: null, prod: {}, move: [], stock: {}, ship: {}, unload: {}, vessels: [], expected: [] };
    const mk = all.find(o => /^20\d\d-\d\d-\d\d$/.test(o.t.trim())); if (mk) out.made = mk.t.trim();

    // ① 생산 · 이송 및 판매
    const yStock = yOf(/^1\.재고/), yShip = yOf(/^2\.출하/), yVes = yOf(/^3\.선박/);
    const topI = all.filter(o => yStock == null || o.y > yStock + 2);
    const near = (lab, x0, x1) => topI.filter(o => o.x > x0 && o.x < x1 && Math.abs(o.y - lab.y) < 3.2).sort((p, q) => p.x - q.x);
    const pv = lab => { const v = near(lab, 110, 230).map(o => num(o.t)).find(n => n != null); return v == null ? null : v; };
    for (const o of topI) {
      const t = sp(o.t);
      if (o.x < 110 && /^(크링커|클링커)$/.test(t) && out.prod.clk == null) out.prod.clk = pv(o);
      if (o.x < 110 && t === '삼척') out.prod.cemSC = pv(o);
      if (o.x < 110 && t === '동해') out.prod.cemDH = pv(o);
      if (o.x > 250 && /이송|판매/.test(o.t) && !/이송및판매/.test(t)) {
        const after = near(o, o.x + W(o) - 2, 999), iD = after.findIndex(x => sp(x.t) === '일계'), iC = after.findIndex(x => sp(x.t) === '누계');
        const dv = iD >= 0 ? after[iD + 1] : null, cv = iC >= 0 ? after[iC + 1] : null, dt = dv ? dv.t.trim() : '';
        out.move.push({ name: o.t.replace(/\s+/g, ' ').trim(), d: !dt || /^[-=]$/.test(dt) || /^(일계|누계)$/.test(dt) ? null : dt, c: cv ? num(cv.t) : null });
      }
    }
    out.move.sort((p, q) => 0);
    // ② 사일로 재고
    const hdr = R.find(r => yStock != null && r.y < yStock && r.y > (yShip ?? -1) && r.c.filter(o => /^\d{1,2}$/.test(o.t.trim())).length >= 6);
    if (hdr) {
      const cols = hdr.c.filter(o => /^\d{1,2}$/.test(o.t.trim()) || /소계|합계/.test(sp(o.t))).map(o => ({ k: /^\d/.test(o.t.trim()) ? +o.t.trim() : sp(o.t), cx: cx(o) }));
      const grab = r => { const v = {}; r.c.filter(o => o.x > 85).forEach(o => { const c = nearest(o, cols), n = num(o.t); if (c && (n != null || /^-$/.test(o.t.trim()))) v[c.k] = n == null ? 0 : n; }); return v; };
      const body = R.filter(r => r.y < hdr.y && (yShip == null || r.y > yShip));
      for (const r of body) {
        const lab = sp(r.c.filter(o => o.x < 85).map(o => o.t).join(''));
        if (/공장/.test(lab)) out.stock.sc = grab(r);
        else if (/부두/.test(lab)) out.stock.pier = grab(r);
        else if (/시멘트/.test(lab)) out.stock.dhCem = grab(r);
        else if (/크링커|클링커/.test(lab)) out.stock.dhClk = grab(r);
        else { const t = grab(r); if (t['합계'] != null && !Object.keys(t).some(k => /^\d+$/.test(k))) out.stock.total = t['합계']; }
      }
      for (const k of ['sc', 'pier', 'dhCem', 'dhClk']) { const o = out.stock[k]; if (o) { if (o['합계'] != null) { out.stock.total = o['합계']; delete o['합계']; } o.sum = o['소계']; delete o['소계']; } }
    } else warn.push('사일로 재고 표를 찾지 못했습니다.');
    // ③ 출하 (삼척·동해·합계 × 대·일계·누계)
    const sh = R.find(r => yShip != null && r.y < yShip && (yVes == null || r.y > yVes) && r.c.filter(o => /^(대|일계|누계)$/.test(sp(o.t))).length >= 6);
    if (sh) {
      const keys = ['scN', 'scD', 'scC', 'dhN', 'dhD', 'dhC', 'tD', 'tC'], hs = sh.c.filter(o => /^(대|일계|누계)$/.test(sp(o.t)));
      const cols = hs.slice(0, 8).map((o, i) => ({ k: keys[i], cx: cx(o) }));
      let land = true, bk = 0;
      for (const r of R.filter(r => r.y < sh.y && (yVes == null || r.y > yVes))) {
        const labs = r.c.filter(o => o.x < 85 && !/^[육자동차송해내수출하역]$/.test(o.t.trim())), lab = sp(labs.map(o => o.t).join(''));
        if (!lab) continue;
        const v = {}; r.c.filter(o => o.x >= 85).forEach(o => { const c = nearest(o, cols), n = num(o.t); if (c && n != null) v[c.k] = n; });
        let key = lab;
        if (lab === '소계') { key = land ? '육송' : '해송'; land = false; }
        else if (lab === 'B/K') { key = bk++ ? '수출B/K' : '내수B/K'; }
        else if (/출하합계/.test(lab)) key = '출하합계';
        else if (/하역합계/.test(lab)) key = '하역합계';
        if (/^(유연탄|P-Cokes|중화석고|천연석고|탈황석고|진해석고|3종샘플|SLAG|FlyAsh|D\.FlyAsh|황산철)$/.test(lab)) out.unload[lab] = v; else out.ship[key] = v;
      }
    } else warn.push('출하 표를 찾지 못했습니다.');
    // ④ 선박
    const vh = R.find(r => yVes != null && r.y < yVes && r.c.some(o => sp(o.t) === '선명'));
    if (vh) {
      const H = {}; vh.c.forEach(o => { H[sp(o.t)] = o; });
      const tcols = ['외항', '접안', '착수', '완료', '출항'].filter(k => H[k]).map(k => ({ k, cx: cx(H[k]) }));
      const xTH = H['T/H'] ? H['T/H'].x : 300, xBerth = H['선석'] ? H['선석'].x : 318, x24 = H['24시선적량'] ? H['24시선적량'].x : 334;
      const xExp = H['입항예정선박'] ? H['입항예정선박'].x - 60 : 450, xDest = x24 + 20;
      // 구분 세로 글자(삼·척·항 / 동·해·항)로 항구 구간 나누기
      const vl = all.filter(o => o.x < 34 && o.y < vh.y && /^[삼척동해항]$/.test(o.t.trim()));
      const cy = ch => { const a = vl.filter(o => ch.includes(o.t.trim())); return a.length ? a.reduce((s, o) => s + o.y, 0) / a.length : null; };
      const cS = cy(['삼', '척']), cD = cy(['동', '해']), topS = vh.y - 4.3;
      const split = cS != null && cD != null ? 2 * cS - topS : cD != null ? cD + 40 : -1e9;
      const foot = R.find(r => r.y < vh.y && r.c.some(o => /삼표에스앤씨|^20\d\d-\d\d-\d\d$/.test(sp(o.t))));
      const body = R.filter(r => r.y < vh.y - 1 && (!foot || r.y > foot.y + 1) && r.c.some(o => o.x >= 34));
      for (const r of body) {
        const port = r.y > split ? 'sc' : 'dh';
        const c = r.c.filter(o => o.x >= 34);
        const exp = c.filter(o => o.x >= xExp).map(o => o.t.trim()).join(' ').trim();
        const rest = c.filter(o => o.x < xExp);
        if (exp) {
          const m = exp.match(/^(.+?)\s+(\d{1,2}\/\d{1,2}:\d{2}|\d{1,2}\/\d{1,2})\s*(s-)?#?\s*(\d+)?\s*(?:\((.*)\))?\s*$/);
          if (m) out.expected.push({ port, name: m[1].trim(), eta: when(m[2], 12), berth: m[4] ? +m[4] : null, shift: !!m[3], note: (m[5] || '').trim() });
          else out.expected.push({ port, name: exp, eta: null, berth: null, note: '' });
        }
        if (!rest.length) continue;
        const v = { port, name: '', cargo: '', qty: null, t: {}, th: null, berth: null, load24: null, dest: '', note: '', eta: null };
        for (const o of rest) {
          const t = o.t.trim();
          if (o.x < 90) { v.name += (v.name ? ' ' : '') + t; continue; }
          if (o.x < 118) { v.cargo = t; continue; }
          if (o.x < 150 && num(t) != null) { v.qty = num(t); continue; }
          const eta = t.match(/\((\d{1,2}\/\d{1,2})\s*입\.?\s*예\)/); if (eta) { v.eta = when(eta[1], 12); v.etaDay = true; continue; }
          const etd = t.match(/\((\d{1,2}\/\d{1,2})\s*출\.?\s*예\)/); if (etd) { v.etd = when(etd[1], 12); v.etdDay = true; continue; }
          if (/^\d{1,2}\/\d{1,2}:\d{2}$/.test(t)) { const k = nearest(o, tcols); if (k) v.t[k.k] = when(t); continue; }
          if (o.x >= xTH - 4 && o.x < xBerth - 1 && num(t) != null) { v.th = num(t); continue; }
          if (o.x >= xBerth - 1 && o.x < x24 && num(t) != null) { v.berth = num(t); continue; }
          if (o.x >= x24 && o.x < xDest && num(t) != null) { v.load24 = num(t); continue; }
          if (o.x >= x24) { v.dest += (v.dest ? ' ' : '') + t; continue; }
        }
        if (!v.name) continue;
        // 양하지 "부산/07시:6,500mt" · "거제[판매]" · "인천/미실적" · "(CANADA)"
        let d = v.dest.replace(/^\(|\)$/g, '');
        const tg = d.match(/\[([^\]]+)\]/); if (tg) { v.note = tg[1]; d = d.replace(tg[0], ''); }
        const sl = d.split('/'); v.dest = sl[0].trim(); if (sl.length > 1) v.note = [v.note, sl.slice(1).join('/').trim()].filter(Boolean).join(' · ');
        const tq = v.note.match(/([\d,]+)\s*mt/i); if (tq && v.qty == null) v.qtyPlan = num(tq[1]);
        const th = v.note.match(/(\d{1,2})\s*시/); if (th && v.t['착수'] && !v.t['완료']) { const s0 = new Date(v.t['착수']); const e = new Date(s0); e.setHours(+th[1], 0, 0, 0); if (e <= s0) e.setDate(e.getDate() + 1); v.doneEst = `${e.getFullYear()}-${pad2(e.getMonth() + 1)}-${pad2(e.getDate())}T${pad2(e.getHours())}:00`; }
        out.vessels.push(v);
      }
    } else warn.push('선박 표를 찾지 못했습니다.');
    return { data: out, warn };
  }
  async function read(buf) {
    const u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    if (latin(u8.subarray(0, 5)) !== '%PDF-') throw new Error('PDF 파일이 아닙니다');
    return parse(await textItems(u8));
  }

  const api = { textItems, rows, cmap, parse, read };
  if (isNode) module.exports = api; else root.SOKBO = api;
})(typeof window !== 'undefined' ? window : globalThis);
