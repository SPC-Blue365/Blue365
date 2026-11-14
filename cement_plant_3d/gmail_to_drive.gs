/**
 * Blue365 — Gmail로 오는 출하속보 PDF를 구글 드라이브 폴더에 자동 저장 (Google Apps Script)
 *
 * 설치 (처음 한 번, 출하속보를 받는 Gmail 계정으로 로그인한 상태에서)
 *   1) https://script.google.com → [새 프로젝트] → 이 파일 내용을 모두 붙여넣기 → 저장(디스크 아이콘)
 *   2) 위쪽 함수 선택에서 setup 선택 → [실행] → 권한 허용
 *      (Gmail 읽기 · 드라이브 파일 만들기 권한. ‘확인되지 않은 앱’ 화면이 나오면 [고급] → [이동])
 *   3) 구글 드라이브에 ‘Blue365 출하속보’ 폴더가 생기고, 그 뒤로 10분마다 새 출하속보 PDF가 저장됩니다.
 *   4) 서버 PC: ‘Google Drive(데스크톱)’ 앱을 같은 계정으로 로그인 → 이 폴더가 G:\내 드라이브\Blue365 출하속보 처럼 보이면
 *      서버실행.bat 의 server.py 줄 끝에  --sokbo-watch "G:\내 드라이브\Blue365 출하속보"  를 붙여 다시 실행
 *
 * - 메일은 읽기만 합니다 (읽음 표시·라벨·이동을 바꾸지 않음). 이미 저장한 메일은 기억해 두고 다시 저장하지 않습니다.
 * - 60일이 지난 PDF는 드라이브 휴지통으로 옮깁니다 (KEEP_DAYS).
 * - 그만 쓰려면: script.google.com → 이 프로젝트 → 왼쪽 ‘트리거’(시계 아이콘)에서 삭제.
 */
const CFG = {
  QUERY: 'subject:(출하속보 OR 出荷速報) has:attachment filename:pdf newer_than:3d',   // 보낸 사람으로 거르려면 뒤에  from:보낸사람주소  추가
  SUBJECT: /출하속보|出荷速報/,
  FOLDER: 'Blue365 출하속보',
  KEEP_DAYS: 60,
  EVERY_MIN: 10,
};

/** 처음 한 번 실행: 10분마다 saveSokbo 가 돌도록 등록하고 바로 한 번 실행 */
function setup() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'saveSokbo').forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('saveSokbo').timeBased().everyMinutes(CFG.EVERY_MIN).create();
  saveSokbo();
  console.log(`설치 완료: ${CFG.EVERY_MIN}분마다 ‘${CFG.FOLDER}’ 폴더에 저장합니다.`);
}

function folder_() {
  const it = DriveApp.getFoldersByName(CFG.FOLDER);
  return it.hasNext() ? it.next() : DriveApp.createFolder(CFG.FOLDER);
}

/** 새 출하속보 메일의 PDF 첨부를 드라이브 폴더에 저장 (파일 이름: 메일날짜_시각_원래이름.pdf) */
function saveSokbo() {
  const props = PropertiesService.getScriptProperties();
  const done = JSON.parse(props.getProperty('done') || '[]');
  const f = folder_();
  let n = 0;
  GmailApp.search(CFG.QUERY, 0, 30).forEach(th => th.getMessages().forEach(m => {
    const id = m.getId();
    if (done.includes(id) || !CFG.SUBJECT.test(m.getSubject().replace(/\s/g, ''))) return;
    m.getAttachments({ includeInlineImages: false })
      .filter(a => /\.pdf$/i.test(a.getName()) || a.getContentType() === 'application/pdf')
      .forEach(a => {
        const name = Utilities.formatDate(m.getDate(), 'Asia/Seoul', 'yyyy-MM-dd_HHmm') + '_' + a.getName().replace(/[\\/:*?"<>|]/g, '');
        if (!f.getFilesByName(name).hasNext()) { f.createFile(a.copyBlob().setName(name)); n++; }
      });
    done.push(id);
  }));
  props.setProperty('done', JSON.stringify(done.slice(-300)));
  const cut = Date.now() - CFG.KEEP_DAYS * 864e5, it = f.getFiles();
  while (it.hasNext()) { const x = it.next(); if (x.getDateCreated().getTime() < cut) x.setTrashed(true); }
  if (n) console.log(`출하속보 PDF ${n}개 저장`);
}
