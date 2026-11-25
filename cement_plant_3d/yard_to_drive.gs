/**
 * Blue365 — ‘석회석/부원료 재고현황’ 구글 시트를 15분마다 읽어 구글 드라이브에 JSON으로 저장 (Google Apps Script)
 *
 * 왜 필요한가
 *   재고현황 시트는 근무자가 실시간으로 고쳐 쓰는 한 장짜리 양식이라(날짜 칸 없음, 매일 같은 칸을 덮어씀)
 *   특정 시각에 열면 아직 안 쓴 칸이 0·0:00이고, 지난 값은 ‘버전 기록’에서만 볼 수 있습니다.
 *   이 스크립트는 15분마다 시트를 읽어 **바뀐 칸만** 그 근무조·날짜의 값으로 기억해 둡니다.
 *   → 버전 기록을 열지 않아도 근무조마다 마지막으로 입력된 값이 모입니다.
 *
 * 근무조와 날짜 (현장 설명 2026-11-25)
 *   3차 00~08시 · 1차 08~16시 · 2차 16~24시. 칸이 바뀐 시각으로 날짜를 정합니다:
 *   3차 칸 = 그날, 1차 칸은 08시 전에 바뀌면 전날, 2차 칸은 16시 전에 바뀌면 전날.
 *   (예: 11/25 06:35에 처음 읽으면 3차 = 11/25, 1차·2차 = 11/24 — 06:35 버전의 실제 내용과 같음)
 *   0 t · 0:00 · 빈 칸은 ‘아직 안 씀’으로 봅니다.
 *
 * 설치 (처음 한 번, 재고현황 메일을 받는 구글 계정으로)
 *   1) https://script.google.com → [새 프로젝트] → 이 파일 내용을 모두 붙여넣기 → 저장
 *      (출하속보 스크립트와 같은 프로젝트에 파일을 추가해도 됩니다 — 함수 이름이 겹치지 않게 setupYard 로 따로 둠)
 *   2) 위쪽 함수 선택에서 checkYard → [실행] → 권한 허용 → 아래 ‘실행 로그’에 단계별 ✓ / ✗ 가 나옵니다 (아무것도 저장하지 않는 점검)
 *   3) 모두 ✓ 이면 함수 선택에서 setupYard → [실행]  → 15분마다 자동 실행 등록 + 첫 저장
 *      시트 주소는 ‘석회석/부원료 재고현황’ 메일 본문의 링크 → 드라이브의 시트 이름 순서로 자동으로 찾습니다.
 *      못 찾으면 아래 SHEET_URL 에 시트 주소(브라우저 주소창 그대로)를 붙여넣고 다시 checkYard.
 *   4) 드라이브에 ‘Blue365 원료재고’ 폴더와 yard_latest.json 이 생깁니다.
 *   5) 서버 PC: 서버실행.bat 의 server.py 줄 끝에  --yard-watch auto  를 붙여 다시 실행
 *      (Google Drive 데스크톱 앱이 같은 계정으로 로그인되어 있어야 함 — 출하속보 자동 읽기와 같음)
 *
 * - 시트는 읽기만 합니다 (값·서식·버전을 바꾸지 않음). 보기 권한만 있어도 됩니다.
 * - 그만 쓰려면: script.google.com → 이 프로젝트 → 왼쪽 ‘트리거’(시계 아이콘)에서 pollYard 삭제.
 */
const YCFG = {
  SHEET_URL: '',                                   // 비워 두면 메일 → 드라이브 순서로 자동으로 찾음. 주소 또는 ID
  MAIL_QUERY: '(subject:재고현황 OR subject:석회석 OR subject:부원료) newer_than:30d',
  NAME_HINT: '재고현황',                           // 드라이브에서 찾을 때 시트 파일 이름에 들어간 말
  TAB: '재고 및 생산실적',
  FOLDER: 'Blue365 원료재고',
  FILE: 'yard_latest.json',
  EVERY_MIN: 15,
  KEEP_DAYS: 3,                                    // JSON에 넣는 최근 날짜 수
};

/** 처음 한 번 실행: 점검 → 15분마다 pollYard 가 돌도록 등록 → 첫 저장 */
function setupYard() {
  const tab = openTab_(console.log);
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'pollYard').forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('pollYard').timeBased().everyMinutes(YCFG.EVERY_MIN).create();
  pollYard_(tab);
  console.log(`✓ 설치 완료: ${YCFG.EVERY_MIN}분마다 드라이브 ‘${YCFG.FOLDER}/${YCFG.FILE}’ 에 저장합니다.`);
}

/** 점검만 (아무것도 저장·등록하지 않음): 메일 → 시트 열기 → 탭 → 해석 결과를 실행 로그에 */
function checkYard() {
  const tab = openTab_(console.log);
  const rg = range_(tab), P = yardParse_(rg.getValues(), rg.getDisplayValues());
  ['3', '1', '2'].forEach(s => {
    const o = P.shifts[s], v = k => o[k] == null ? '-' : o[k], y = ['PBA1', 'PBA2', 'PBB1', 'PBB2'].map(k => `${k} ${v('y.' + k + '.t')}${o['y.' + k + '.m'] || ''}`).join(' · ');
    console.log(`✓ ${s}차 칸: ${y} · 구치장 ${v('sub.A')} · OSP 인출 ${v('draw.A.t')} / ${v('draw.B.t')}`);
  });
  console.log(`✓ 품위 ${Object.keys(P.common.grade).length}개 야드 · 야드 변경 ${Object.keys(P.common.chg).join(', ') || '없음'}`);
  console.log('점검 끝 — 위가 모두 ✓ 이면 setupYard 를 실행하세요.');
}

/** 기억해 둔 값을 지우고 처음부터 (시트 양식이 크게 바뀌었을 때만) */
function resetYard() {
  PropertiesService.getScriptProperties().deleteProperty('ystate');
  console.log('기억해 둔 값을 지웠습니다. 다음 실행부터 지금 시트 내용으로 다시 시작합니다.');
}

/** 15분마다 (트리거) */
function pollYard() { pollYard_(openTab_(() => {})); }

const sheetId_ = t => {   // 주소·ID·메일 본문(인코딩된 링크 포함)에서 스프레드시트 ID
  let x = String(t || '');
  x += ' ' + x.replace(/%2F/gi, '/').replace(/%3A/gi, ':').replace(/%3F/gi, '?').replace(/%3D/gi, '=').replace(/%26/gi, '&');   // 메일 보안 링크(인코딩된 주소)
  const m = x.match(/spreadsheets\/(?:u\/\d+\/)?d\/([\w-]{25,})/) || x.match(/(?:file\/d\/|[?&]id=)([\w-]{25,})/) || x.match(/^\s*([\w-]{25,})\s*$/);
  return m ? m[1] : null;
};

/** 시트 열기: SHEET_URL → 메일 링크 → 드라이브 이름 검색 → 지난번 성공한 ID. 단계마다 log 로 알림 */
function openTab_(log) {
  const props = PropertiesService.getScriptProperties(), tried = [];
  const cands = [];
  if (YCFG.SHEET_URL) { const id = sheetId_(YCFG.SHEET_URL); if (!id) throw new Error('✗ SHEET_URL 에서 시트 ID를 읽지 못했습니다 — 브라우저 주소창의 주소를 그대로 붙여넣으세요'); cands.push([id, 'SHEET_URL']); }
  else {
    let n = 0;
    try {
      GmailApp.search(YCFG.MAIL_QUERY, 0, 20).forEach(th => th.getMessages().reverse().forEach(m => {
        if (!/재고현황|석회석|부원료/.test(m.getSubject())) return;
        n++;
        const id = sheetId_(m.getBody() + ' ' + m.getPlainBody());
        if (id && !cands.some(c => c[0] === id)) cands.push([id, `메일 ‘${m.getSubject()}’ (${Utilities.formatDate(m.getDate(), 'Asia/Seoul', 'MM/dd HH:mm')})`]);
      }));
      log(n ? `✓ 재고현황 메일 ${n}통 찾음 · 시트 링크 ${cands.length}개` : '✗ 최근 30일 재고현황 메일을 찾지 못함 → 드라이브에서 찾습니다');
    } catch (e) { log('✗ Gmail 읽기 실패: ' + e.message + ' → 드라이브에서 찾습니다'); }
    try {
      const it = DriveApp.searchFiles(`title contains '${YCFG.NAME_HINT}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false`);
      let k = 0;
      while (it.hasNext() && k < 10) { const f = it.next(); k++; if (!cands.some(c => c[0] === f.getId())) cands.push([f.getId(), `드라이브 ‘${f.getName()}’`]); }
      if (k) log(`✓ 드라이브에서 이름에 ‘${YCFG.NAME_HINT}’ 가 들어간 시트 ${k}개`);
    } catch (e) { log('✗ 드라이브 검색 실패: ' + e.message); }
    const saved = props.getProperty('sheetId');
    if (saved && !cands.some(c => c[0] === saved)) cands.push([saved, '지난번에 연 시트']);
  }
  for (const [id, how] of cands) {
    let ss;
    try { ss = SpreadsheetApp.openById(id); }
    catch (e) {
      let why = e.message;
      try { const mt = DriveApp.getFileById(id).getMimeType(); if (!/google-apps\.spreadsheet/.test(mt)) why = `구글 시트가 아니라 ${/sheet|excel/i.test(mt) ? '엑셀(.xlsx) 파일' : mt} 입니다 — 드라이브에서 [파일 → Google Sheets로 저장] 한 시트여야 읽을 수 있습니다`; }
      catch (e2) { why = '이 계정에 열람 권한이 없습니다 (시트 소유자에게 보기 권한 요청) · ' + e.message; }
      tried.push(`${how}: ${why}`); continue;
    }
    const tab = ss.getSheetByName(YCFG.TAB);
    if (!tab) { tried.push(`${how} ‘${ss.getName()}’: ‘${YCFG.TAB}’ 탭이 없음 (탭: ${ss.getSheets().map(x => x.getName()).slice(0, 6).join(', ')}…)`); continue; }
    log(`✓ 시트 열기: ‘${ss.getName()}’ → ‘${YCFG.TAB}’ 탭 (${how})`);
    if (props.getProperty('sheetId') !== id) props.setProperty('sheetId', id);
    return tab;
  }
  throw new Error(cands.length ? '✗ 시트를 열지 못했습니다:\n  ' + tried.join('\n  ') : '✗ 시트 링크를 찾지 못했습니다 — YCFG.SHEET_URL 에 시트 주소를 붙여넣고 다시 실행하세요');
}

const range_ = sh => sh.getRange(1, 1, Math.min(Math.max(sh.getLastRow(), 1), 80), Math.min(Math.max(sh.getLastColumn(), 1), 30));

/** 시트 읽기 → 바뀐 칸 기억 → 바뀐 게 있으면 드라이브 JSON 덮어쓰기 */
function pollYard_(tab) {
  const rg = range_(tab), props = PropertiesService.getScriptProperties();
  const out = yardTrack_(yardParse_(rg.getValues(), rg.getDisplayValues()), new Date(), JSON.parse(props.getProperty('ystate') || '{}'));
  props.setProperty('ystate', JSON.stringify(out.state));
  if (!out.changed) return;
  const it = DriveApp.getFoldersByName(YCFG.FOLDER), f = it.hasNext() ? it.next() : DriveApp.createFolder(YCFG.FOLDER);
  const fi = f.getFilesByName(YCFG.FILE), body = JSON.stringify(out.records);
  if (fi.hasNext()) fi.next().setContent(body); else f.createFile(YCFG.FILE, body, 'application/json');
  console.log(`원료 야드 ${out.records.length}개 근무조 저장: ` + out.records.map(r => r.date.slice(5) + ' ' + r.shift + '차').join(', '));
}

/* ---------------- 아래는 시트 해석 (Google 서비스를 쓰지 않음 — 서버 쪽 시험에서도 그대로 실행) ---------------- */

const kst_ = d => new Date(d.getTime() + 9 * 36e5).toISOString().slice(0, 19);   // 한국 시각 YYYY-MM-DDTHH:MM:SS
const SH_END_ = { '3': '08:00:00', '1': '16:00:00', '2': '23:59:00' };
function shiftDate_(now, s) {
  const h = +kst_(now).slice(11, 13), back = (s === '1' && h < 8) || (s === '2' && h < 16);
  return kst_(new Date(now.getTime() - (back ? 864e5 : 0))).slice(0, 10);
}

/**
 * ‘재고 및 생산실적’ 시트 → 근무조별 값 (칸 주소가 아니라 이름표로 찾음: 줄·칸이 조금 밀려도 동작)
 *   V = getValues(), D = getDisplayValues()  (0부터 세는 2차원 배열)
 */
function yardParse_(V, D) {
  const S = (r, c) => String((D[r] && D[r][c] != null ? D[r][c] : '')).replace(/\s+/g, '');
  const num = (r, c) => {
    const v = V[r] && V[r][c];
    if (typeof v === 'number') return v > 0 && v < 1e6 ? Math.round(v * 100) / 100 : null;
    const s = S(r, c).replace(/,/g, '');
    return /^\d+(\.\d+)?$/.test(s) && +s > 0 ? +s : null;
  };
  const pct = (r, c) => { const v = num(r, c); return v != null && v < 100 ? v : null; };
  const mode = (r, c) => { const s = S(r, c).toUpperCase(); return s === 'S' || s === 'R' ? s : null; };
  const mins = (r, c) => { const m = S(r, c).match(/^(\d{1,3}):(\d{2})/); return m ? +m[1] * 60 + +m[2] : 0; };
  const hm = n => n > 0 ? Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0') : null;
  const find = (re, r0, r1, c0, c1) => {
    for (let r = r0; r < Math.min(r1, V.length); r++) for (let c = c0; c < c1; c++) if (re.test(S(r, c))) return [r, c];
    return null;
  };
  const out = { shifts: { '3': {}, '1': {}, '2': {} }, common: { grade: {}, chg: {} } };

  // 1. 재고현황: ‘3차(00시~08시)’ ‘1차…’ ‘2차…’ 머리줄
  const h3 = find(/^3차\(/, 0, 20, 0, 14);
  if (!h3) throw new Error('‘3차(00시~08시)’ 머리줄을 찾지 못했습니다 — 시트 양식 확인');
  const hr = h3[0], col = {};
  for (let c = 0; c < 14; c++) { const m = S(hr, c).match(/^([123])차\(/); if (m) col[m[1]] = c; }
  const end = (find(/석회석생산실적/, hr + 1, hr + 40, 0, 6) || [hr + 30])[0];
  const g = find(/^PileCaO$/i, hr, hr + 3, 0, 30), nC = find(/^일시$/, hr, hr + 3, 0, 30), fC = find(/^만실량$/, hr, hr + 3, 0, 30);
  let sec = '', line = '';
  const ID = { '석회석|A|1yard': 'PBA1', '석회석|A|2yard': 'PBA2', '석회석|B|1yard': 'PBB1', '석회석|B|2yard': 'PBB2', '부원료|B|1yard': 'SB1', '부원료|B|2yard': 'SB2' };
  for (let r = hr + 1; r < end; r++) {
    const a = S(r, 0), b = S(r, 1), cc = S(r, 2);
    if (a) { sec = /부원료/.test(a) ? '부원료' : /석회석/.test(a) ? '석회석' : sec; line = ''; }
    const lm = b.match(/^(\d)-(\d)K$/i);
    if (lm) line = lm[1] === '1' ? 'A' : 'B';
    const item = (cc || (lm ? '' : b)).toLowerCase(), key = `${sec}|${line}|${item}`, id = ID[key];
    if (id) {   // 품위(석회석 야드만)·야드 변경(일시·만실량)은 근무조와 무관
      if (g && sec === '석회석') { const q = { pcao: pct(r, g[1]), cao: pct(r, g[1] + 1), mgo: pct(r, g[1] + 2), k2o: pct(r, g[1] + 3) }; if (Object.values(q).some(v => v != null)) out.common.grade[id] = q; }
      if (nC && Object.prototype.toString.call(V[r][nC[1]]) === '[object Date]' && !isNaN(V[r][nC[1]])) out.common.chg[id] = { at: kst_(V[r][nC[1]]).slice(0, 16), full: fC ? num(r, fC[1]) : null };
    }
    Object.entries(col).forEach(([s, c]) => {
      const o = out.shifts[s];
      if (id && sec === '석회석') { o[`y.${id}.t`] = num(r, c); o[`y.${id}.m`] = mode(r, c + 1); }
      else if (id) { const k = id === 'SB1' ? 'B1' : 'B2'; o[`subm.${k}.t`] = num(r, c); o[`subm.${k}.m`] = mode(r, c + 1); }
      else if (key === '석회석|A|구치장') o['sub.A'] = num(r, c);
      else if (key === '석회석|A|인출시간') o['run.A'] = hm(mins(r, c + 1));
      else if (key === '석회석|A|r/e') o['run.RE'] = hm(mins(r, c + 1));
      else if (key === '석회석|B|인출시간') o['run.B'] = hm(mins(r, c + 1));
      else if (key === '석회석|B|osp1') o['ex.osp1'] = num(r, c);
      else if (key === '석회석|B|osp2') o['ex.osp2'] = num(r, c);
      else if (key === '부원료|B|인출시간') o['run.SB'] = hm(mins(r, c + 1));
    });
  }

  // 2. 인출현황: ‘1-5K’ ‘6-7K’ ‘쉘’ 머리 · 근무조 3줄 묶음 (OSP 49Q · 47Q · L-Slag/직송)
  const t = find(/인출현황/, hr, V.length, 0, 30);
  if (t) {
    const pA = find(/^1-5K$/i, t[0] + 1, t[0] + 3, t[1], 30), pB = find(/^6-7K$/i, t[0] + 1, t[0] + 3, t[1], 30), pS = find(/^쉘$/, t[0] + 1, t[0] + 3, t[1], 30);
    for (let r = t[0] + 2; r < Math.min(t[0] + 20, V.length); r++) {
      const m = S(r, t[1]).match(/^([123])차/);
      if (!m) continue;
      const o = out.shifts[m[1]], sum = (c, rows) => rows.reduce((x, rr) => x + (num(rr, c) || 0), 0), msum = (c, rows) => rows.reduce((x, rr) => x + mins(rr, c), 0);
      const put = (k, c, rows) => { o[`draw.${k}.t`] = sum(c, rows) || null; o[`draw.${k}.h`] = hm(msum(c + 1, rows)); };
      if (pA) { put('A', pA[1], [r, r + 1]); put('LS', pA[1], [r + 2]); }
      if (pB) { put('B', pB[1], [r, r + 1]); put('DR', pB[1], [r + 2]); }
      if (pS) [r, r + 1, r + 2].forEach(rr => { const lab = S(rr, pS[1] + 2); if (lab === '기존') put('SA', pS[1], [rr]); if (lab === '신설') put('SB', pS[1], [rr]); });
    }
  }
  return out;
}

/** 바뀐 칸만 그 시각의 근무조·날짜로 기억 → 날짜#근무조 기록으로 묶음 */
function yardTrack_(P, now, st) {
  st = st && st.f ? st : { f: {} };
  let changed = false;
  ['3', '1', '2'].forEach(s => {
    const cur = P.shifts[s] || {}, mem = st.f[s] = st.f[s] || {}, date = shiftDate_(now, s);
    const at = [kst_(now), date + 'T' + SH_END_[s]].sort()[0];   // 늦게 처음 읽은 값(설치 직후 1·2차)은 근무조 끝 시각
    new Set([...Object.keys(cur), ...Object.keys(mem)]).forEach(k => {
      const v = cur[k] == null ? null : cur[k], p = mem[k];
      if (p && p.v === v) return;
      changed = true;
      mem[k] = v == null ? { v: null } : { v, date, at };
    });
  });
  const gs = JSON.stringify(P.common);
  if (st.g !== gs) { st.g = gs; changed = true; }
  const cut = kst_(new Date(now.getTime() - YCFG.KEEP_DAYS * 864e5)).slice(0, 10), recs = {};
  ['3', '1', '2'].forEach(s => Object.entries(st.f[s]).forEach(([k, o]) => {
    if (o.v == null || !o.date || o.date < cut) return;
    const key = o.date + '#' + s;
    const r = recs[key] = recs[key] || { date: o.date, shift: s, at: o.at, yards: {}, sub: {}, run: {}, subm: {}, draw: {}, extra: {}, grade: P.common.grade, chg: P.common.chg };
    if (o.at > r.at) r.at = o.at;
    const [grp, a, b] = k.split('.');
    if (grp === 'y') { const y = r.yards[a] = r.yards[a] || {}; y[b] = o.v; if (b === 't') y.at = o.at; }
    else if (grp === 'subm' || grp === 'draw') { (r[grp][a] = r[grp][a] || {})[b] = o.v; }
    else ({ sub: r.sub, run: r.run, ex: r.extra })[grp][a] = o.v;
  }));
  const O = { '3': 0, '1': 1, '2': 2 }, records = Object.values(recs).sort((x, y) => x.date < y.date ? -1 : x.date > y.date ? 1 : O[x.shift] - O[y.shift]);
  return { state: st, changed, records };
}

if (typeof module !== 'undefined') module.exports = { yardParse_, yardTrack_, shiftDate_, kst_ };
