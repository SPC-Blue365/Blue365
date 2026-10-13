// 브라우저 e2e(수동): 먼저 `python3.13 tests/js/make_fixtures.py <폴더>` 로 엑셀 3종을 만들고 FX 경로를 맞춘 뒤
// `python3.13 scripts/build_dashboard.py` → `node tests/js/e2e_dashboard.js` (전역 playwright 필요)
const { chromium } = require("playwright");
const FX = (process.env.FX_DIR || "/tmp/fx") + "/";
const URL = "file://" + require("path").resolve(__dirname, "../../dist/dashboard/Blue365_QMS_대시보드.html");
(async () => {
  const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-proxy-server"] });
  const ctx = await b.newContext(); const page = await ctx.newPage();
  const errs = []; page.on("pageerror", (e) => errs.push("pageerror " + e.message)); page.on("console", (m) => { if (m.type() === "error") errs.push("console " + m.text()); });
  await page.goto(URL); await page.waitForTimeout(500);
  const goData = async () => { await page.evaluate(() => { const t = [...document.querySelectorAll("[data-tab],button,a")].find((x) => /데이터 불러오기/.test(x.textContent)); t && t.click(); }); await page.waitForTimeout(300); };
  const up = async (f) => { await page.setInputFiles('input[type=file]', FX + f); await page.waitForTimeout(700); };
  const txt = async (sel) => (await page.locator(sel).first().innerText().catch(() => "(없음)")).replace(/\n+/g, " / ");
  const out = (k, v) => console.log("\n## " + k + "\n" + v);
  await goData();
  // 1 세로형
  await up("long_lims.xlsx"); out("1 세로형 결과", await txt("#load-result")); out("1 panel visible", String(await page.locator("#map-panel").isVisible()));
  out("1 현재데이터", await txt("#current-data"));
  // 2 가로형 2줄 머리글
  await up("wide_two_row.xlsx"); out("2 가로 결과", await txt("#load-result")); out("2 panel", String(await page.locator("#map-panel").isVisible()));
  out("2 현재데이터", await txt("#current-data"));
  // 3 모르는 열
  await up("unknown_cols.xlsx"); out("3 결과", await txt("#load-result")); out("3 panel", String(await page.locator("#map-panel").isVisible()));
  out("3 panel text", (await txt("#map-panel")).slice(0, 900));
  if (await page.locator("#map-panel").isVisible()) {
    const sels = page.locator("#map-panel table select");
    const n = await sels.count(); out("3 selects", String(n));
    // X101 -> 자유석회, X102 -> 리터중량
    for (let i = 0; i < n; i++) { const row = await sels.nth(i).evaluate((s) => s.closest("tr").innerText.split("\n")[0]); if (/^일자/.test(row)) continue; if (/X101/.test(row)) await sels.nth(i).selectOption("clk_fcao"); if (/X102/.test(row)) await sels.nth(i).selectOption("clk_lw"); }
    await page.locator("#map-panel button", { hasText: "확인하고 불러오기" }).click(); await page.waitForTimeout(500);
    out("3 확정 후", await txt("#load-result")); out("3 현재데이터", await txt("#current-data"));
  }
  // 3b 같은 파일 다시 → 자동
  await up("unknown_cols.xlsx"); out("3b 재업로드 결과", await txt("#load-result")); out("3b panel", String(await page.locator("#map-panel").isVisible()));
  // 4 붙여넣기
  await page.fill("#paste-box", "시료채취일시\t시료명\t시험항목\t결과값\n2026-11-01 08:00\t클링커\tf-CaO\t0.9\n2026-11-01 16:00\t클링커\tf-CaO\t1.1\n2026-11-02 08:00\t클링커\tf-CaO\t1.3");
  await page.locator("button", { hasText: "붙여넣은 표 불러오기" }).click(); await page.waitForTimeout(500);
  out("4 paste", await txt("#load-result")); out("4 panel", String(await page.locator("#map-panel").isVisible()));
  // 5 대시보드 탭이 깨지지 않는지
  for (const id of ["overview", "monitor"]) { await page.evaluate((id) => { const t = [...document.querySelectorAll("[data-tab],button")].find((x) => x.dataset && x.dataset.tab === id); t && t.click(); }, id); await page.waitForTimeout(500); }
  out("errors", errs.length ? errs.join("\n") : "없음");
  await page.screenshot({ path: (process.env.FX_DIR || "/tmp/fx") + "/e2e_last.png" });
  await b.close();
})();
