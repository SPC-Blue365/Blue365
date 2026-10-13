// 브라우저 e2e(수동): python3.13 scripts/build_dashboard.py → python3.13 tests/js/make_ship_fixture.py /tmp/ship_fx.xlsx → node tests/js/e2e_ship.js /tmp/ship_fx.xlsx (전역 playwright 필요)
const { chromium } = require("playwright");
const URL = "file://" + require("path").resolve(__dirname, "../../dist/dashboard/Blue365_QMS_대시보드.html");
const FILE = process.argv[2];
(async () => {
  const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-proxy-server"] });
  const page = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errs = []; page.on("pageerror", (e) => errs.push("pageerror " + e.message)); page.on("console", (m) => { if (m.type() === "error") errs.push("console " + m.text()); });
  await page.goto(URL); await page.waitForTimeout(500);
  const tab = async (id) => { await page.evaluate((id) => document.querySelector(`#tabs button[data-id=${id}]`).click(), id); await page.waitForTimeout(500); };
  const txt = async (sel, n = 700) => (await page.locator(sel).first().innerText().catch(() => "(없음)")).replace(/\n+/g, " / ").slice(0, n);
  await tab("data");
  await page.setInputFiles("input[type=file]", FILE); await page.waitForTimeout(1500);
  console.log("ERRS:", errs.join(" | ")); console.log("TAB after upload:", await page.evaluate(() => { const a = document.querySelector(".tab.active, section.active"); return a ? (a.dataset.tab || a.id) : "none:" + [...document.querySelectorAll("[data-tab]")].map(x=>x.className).join(","); }));
  console.log("BADGE:", await txt("#databadge"));
  console.log("METRICS:", await txt("#ship-body .metrics"));
  console.log("TABLE:", await txt("#ship-body table.stbl", 2500));
  await page.screenshot({ path: (process.env.OUT_DIR || "/tmp") + "/ship1.png", fullPage: true });
  for (const v of ["spc", "hist", "month", "ship", "combo", "trend"]) {
    await page.selectOption("#ship-detail select >> nth=1", v); await page.waitForTimeout(600);
    console.log("VIEW", v, "| stats:", await txt("#ship-stats", 200), "| extra:", await txt("#ship-extra", 250), "| plot:", await page.locator("#ship-chart .main-svg").count());
    if (v === "ship" || v === "combo") await page.screenshot({ path: `${process.env.OUT_DIR || "/tmp"}/ship_${v}.png`, fullPage: false });
  }
  // 항목 바꾸기(MgO), 필터
  await page.selectOption("#ship-detail select >> nth=0", "mgo"); await page.waitForTimeout(500);
  await page.screenshot({ path: (process.env.OUT_DIR || "/tmp") + "/ship_mgo.png", fullPage: false });
  await page.selectOption(".toolbar select >> nth=0", "90"); await page.waitForTimeout(600);
  console.log("90일 METRICS:", await txt("#ship-body .metrics"));
  await page.selectOption(".toolbar select >> nth=2", "single"); await page.waitForTimeout(600);
  console.log("단독 METRICS:", await txt("#ship-body .metrics"));
  // 재업로드(덮어쓰기) 메시지
  await tab("data"); await page.setInputFiles("input[type=file]", FILE); await page.waitForTimeout(1200);
  await tab("data"); console.log("DATA TAB:", await txt("#load-result", 900));
  console.log("ERRORS:", errs.length ? errs.join("\n") : "없음");
  await b.close();
})();
