/* QMS 엑셀 → 화면 내장 기본 데이터(qms_default.json) 만들기 (개발용 · Node 18+)
 *   node make_default.js <QMS 통합 양식.xlsx>
 * 만든 뒤 python build.py 로 화면 파일에 넣습니다. */
const fs = require('fs'), path = require('path'), QMS = require('./qms.js');
(async () => {
  const src = process.argv[2];
  if (!src) { console.error('사용법: node make_default.js <QMS.xlsx>'); process.exit(1); }
  const sheets = await QMS.readXlsx(fs.readFileSync(src));
  const q = QMS.build(sheets);
  q.source = path.basename(src);
  fs.writeFileSync(path.join(__dirname, 'qms_default.json'), JSON.stringify(q));
  console.log(`qms_default.json: ${q.from} ~ ${q.to}, ${q.total}행, ${(JSON.stringify(q).length / 1024).toFixed(0)} KB`);
  q.warn.forEach(w => console.log(' - ' + w));
})();
