/* Blue365 QMS 대시보드 — 화면 로직 (오프라인 단일 파일). 설치형 Streamlit 앱과 같은 계산(chem.js)을 쓴다. */
(function () {
  "use strict";
  const C = window.CHEM;
  const RAW = window.__QMS_DATA__ || { spec: { items: [], tables: {}, products: [] }, sample: {} };
  const SPEC = RAW.spec;
  const ITEM = {};
  SPEC.items.forEach((it) => { ITEM[it.key] = it; });
  const PRODUCTS = SPEC.products || [];
  const TEXTCOLS = new Set(SPEC.textColumns || ["sand_lot", "operator"]);
  const $ = (s, r) => (r || document).querySelector(s);
  const TOUCH = ("ontouchstart" in window) || navigator.maxTouchPoints > 0;

  // ── 유틸 ──
  const isNum = (v) => v !== null && v !== undefined && v !== "" && isFinite(+v);
  function fmt(v, d = 2) { return isNum(v) ? (+v).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—"; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === "class") e.className = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else if (k.startsWith("on") && typeof attrs[k] === "function") e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
    }
    (children || []).forEach((c) => e.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return e;
  }

  // ── 데이터 레이어 ──
  const STATE = { data: {}, source: "sample", loadedInfo: null, loadError: null };
  function deepCopy(o) { return JSON.parse(JSON.stringify(o || {})); }
  const TABLE_KEYS = {}; SPEC.items.forEach((it) => { (TABLE_KEYS[it.table] = TABLE_KEYS[it.table] || new Set()).add(it.key); });

  // 산화물 → 계수치 자동 계산(설치형 앱 add_*_derived 와 동일). 이미 측정값이 있으면 덮어쓰지 않음.
  const DERIVE = {
    raw_meal: [
      { key: "rm_lsf", need: ["rm_cao", "rm_sio2", "rm_al2o3", "rm_fe2o3"], fn: (g) => C.lsf(g("rm_cao"), g("rm_sio2"), g("rm_al2o3"), g("rm_fe2o3")) },
      { key: "rm_sm", need: ["rm_sio2", "rm_al2o3", "rm_fe2o3"], fn: (g) => C.silicaModulus(g("rm_sio2"), g("rm_al2o3"), g("rm_fe2o3")) },
      { key: "rm_im", need: ["rm_al2o3", "rm_fe2o3"], fn: (g) => C.ironModulus(g("rm_al2o3"), g("rm_fe2o3")) },
    ],
    clinker: [
      { key: "clk_lsf", need: ["clk_cao", "clk_sio2", "clk_al2o3", "clk_fe2o3"], fn: (g) => C.lsf(g("clk_cao"), g("clk_sio2"), g("clk_al2o3"), g("clk_fe2o3")) },
      { key: "clk_sm", need: ["clk_sio2", "clk_al2o3", "clk_fe2o3"], fn: (g) => C.silicaModulus(g("clk_sio2"), g("clk_al2o3"), g("clk_fe2o3")) },
      { key: "clk_im", need: ["clk_al2o3", "clk_fe2o3"], fn: (g) => C.ironModulus(g("clk_al2o3"), g("clk_fe2o3")) },
      { key: "clk_c3s", need: ["clk_cao", "clk_sio2", "clk_al2o3", "clk_fe2o3"], fn: (g) => C.bogue(g("clk_cao"), g("clk_sio2"), g("clk_al2o3"), g("clk_fe2o3"), g("clk_so3"), g("clk_fcao")).C3S },
      { key: "clk_c2s", need: ["clk_cao", "clk_sio2", "clk_al2o3", "clk_fe2o3"], fn: (g) => C.bogue(g("clk_cao"), g("clk_sio2"), g("clk_al2o3"), g("clk_fe2o3"), g("clk_so3"), g("clk_fcao")).C2S },
      { key: "clk_c3a", need: ["clk_al2o3", "clk_fe2o3"], fn: (g) => C.bogue(g("clk_cao"), g("clk_sio2"), g("clk_al2o3"), g("clk_fe2o3"), g("clk_so3"), g("clk_fcao")).C3A },
      { key: "clk_c4af", need: ["clk_fe2o3"], fn: (g) => C.bogue(g("clk_cao"), g("clk_sio2"), g("clk_al2o3"), g("clk_fe2o3"), g("clk_so3"), g("clk_fcao")).C4AF },
      { key: "clk_liquid", need: ["clk_al2o3", "clk_fe2o3"], fn: (g) => C.liquidPhase1450(g("clk_al2o3"), g("clk_fe2o3"), g("clk_mgo"), g("clk_k2o"), g("clk_na2o")) },
      { key: "clk_na2oeq", need: ["clk_na2o", "clk_k2o"], fn: (g) => C.na2oEq(g("clk_na2o"), g("clk_k2o")) },
    ],
  };
  function deriveAll(data) {
    for (const t in DERIVE) {
      const T = data[t]; if (!T) continue;
      const off = T.byProduct ? 2 : 1;
      DERIVE[t].forEach((rule) => {
        if (!ITEM[rule.key] || T.columns.includes(rule.key)) return;
        if (!rule.need.every((k) => T.columns.includes(k))) return;
        const pos = {}; T.columns.forEach((k, i) => { pos[k] = off + i; });
        T.columns.push(rule.key);
        T.rows.forEach((r) => {
          const ok = rule.need.every((k) => isNum(r[pos[k]]));
          const g = (k) => (pos[k] != null && isNum(r[pos[k]]) ? +r[pos[k]] : 0);
          r.push(ok ? round(rule.fn(g), 4) : null);
        });
      });
    }
    return data;
  }
  function setData(data, source) { deriveAll(data); STATE.data = data; STATE.source = source; }
  function tbl(t) { return STATE.data[t]; }
  function valOffset(T) { return T.byProduct ? 2 : 1; }
  function colPos(T, key) { const i = T.columns.indexOf(key); return i < 0 ? -1 : valOffset(T) + i; }
  function tableOf(key) { return ITEM[key] ? ITEM[key].table : null; }
  function limFor(key, product) { const it = ITEM[key]; if (!it) return {}; return (product && it.limits[product]) || it.limits["*"] || {}; }

  function series(key, product) {
    const t = tableOf(key); const T = t && tbl(t); if (!T) return [];
    const pos = colPos(T, key); if (pos < 0) return [];
    const out = [];
    for (const r of T.rows) {
      if (T.byProduct && product && r[1] !== product) continue;
      const v = r[pos]; if (isNum(v)) out.push({ t: r[0], v: +v });
    }
    return out;
  }
  function latest(key, product) { const s = series(key, product); return s.length ? s[s.length - 1] : null; }
  function products(key) {
    const t = tableOf(key); const T = t && tbl(t); if (!T || !T.byProduct) return [null];
    const set = new Set(); T.rows.forEach((r) => { if (r[1]) set.add(r[1]); }); return [...set];
  }
  function judge(v, lim) {
    if (!isNum(v) || (lim.lsl == null && lim.usl == null)) return { cls: "gray", label: "—" };
    if ((lim.lsl != null && v < lim.lsl) || (lim.usl != null && v > lim.usl)) return { cls: "red", label: "기준 이탈" };
    return { cls: "green", label: "기준 이내" };
  }
  function dataPeriod() {
    let lo = null, hi = null;
    for (const t in STATE.data) for (const r of STATE.data[t].rows) { if (!lo || r[0] < lo) lo = r[0]; if (!hi || r[0] > hi) hi = r[0]; }
    return [lo, hi];
  }

  // ── 탭 ──
  const TABS = [
    { id: "overview", label: "🏠 종합 현황", render: renderOverview },
    { id: "ship", label: "🚢 출하시멘트", render: renderShip },
    { id: "monitor", label: "📈 공정 모니터링", render: renderMonitor },
    { id: "chem", label: "🧮 화학 계산기", render: renderChem },
    { id: "rawmix", label: "🧪 배합 설계", render: renderRawmix },
    { id: "chromium", label: "☢️ 6가크롬", render: renderChromium },
    { id: "data", label: "📥 데이터 불러오기", render: renderData },
  ];
  let active = "overview";
  function show(id) {
    active = id;
    $("#tabs").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
    document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.dataset.tab === id));
    const def = TABS.find((t) => t.id === id);
    const sec = $(`.tab[data-tab="${id}"]`);
    sec.innerHTML = ""; def.render(sec);
    window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
  }
  function refreshBadge() {
    const p = dataPeriod();
    const src = STATE.source === "sample" ? "샘플(데모) 데이터" : "불러온 데이터";
    const sh = STATE.ship && STATE.ship.records.length ? ` · 출하시멘트 ${STATE.ship.records[0].date} ~ ${STATE.ship.records[STATE.ship.records.length - 1].date} (${STATE.ship.records.length}건)` : "";
    $("#databadge").textContent = `${src}${p[0] ? ` · ${p[0].slice(0, 10)} ~ ${p[1].slice(0, 10)}` : ""}${sh}`;
  }

  // ── ① 종합 현황 ──
  function renderOverview(root) {
    const keyItems = SPEC.items.filter((it) => it.keyItem);
    let danger = 0, ok = 0, nolim = 0;
    const perStage = {};
    keyItems.forEach((it) => {
      (it.byProduct ? products(it.key) : [null]).forEach((p) => {
        const lt = latest(it.key, p); const lim = limFor(it.key, p); const j = judge(lt && lt.v, lim);
        if (j.cls === "red") danger++; else if (j.cls === "green") ok++; else nolim++;
        (perStage[it.stage] = perStage[it.stage] || []).push({ it, p, lt, lim, j });
      });
    });
    root.appendChild(el("h2", {}, ["종합 현황"]));
    root.appendChild(el("p", { class: "hint" }, [`핵심 관리항목 ${keyItems.length}종의 최신값을 KS·사내 관리기준과 대조합니다. 실제 데이터는 '📥 데이터 불러오기'에서 올리세요.`]));

    const m = el("div", { class: "metrics" });
    m.appendChild(metric("기준 이탈(핵심항목)", String(danger), danger ? "red" : "green", danger ? "확인 필요" : "이상 없음"));
    m.appendChild(metric("기준 이내", String(ok), "green", "핵심항목 중"));
    const lastLot = latest("phy_s28", "1종");
    m.appendChild(metric("1종 28일 강도(최근)", lastLot ? fmt(lastLot.v, 1) + " MPa" : "—", "blue", lastLot ? lastLot.t.slice(0, 10) : ""));
    const fcao = latest("clk_fcao");
    m.appendChild(metric("클링커 f-CaO(최근)", fcao ? fmt(fcao.v, 2) + " %" : "—", "blue", fcao ? fcao.t.slice(0, 10) : ""));
    root.appendChild(m);

    root.appendChild(el("h3", { style: "margin-top:18px" }, ["공정별 상태"]));
    const sc = el("div", { class: "statecards" });
    for (const stage in perStage) {
      const card = el("div", { class: "card statecard" });
      card.appendChild(el("h4", {}, [stage]));
      perStage[stage].forEach(({ it, p, lt, lim, j }) => {
        const name = it.name + (p ? ` · ${p}` : "");
        const rng = lim.lsl != null && lim.usl != null ? `${lim.lsl}~${lim.usl}` : lim.usl != null ? `≤${lim.usl}` : lim.lsl != null ? `≥${lim.lsl}` : "";
        card.appendChild(el("div", { class: "row" }, [
          el("span", { html: `<span class="dot ${j.cls === "gray" ? "gray" : j.cls}"></span> ${esc(name)}` }),
          el("span", { class: "val", html: `${lt ? fmt(lt.v, it.decimals) : "—"} <span class="small">${esc(it.unit)}${rng ? " · " + rng : ""}</span>` }),
        ]));
      });
      sc.appendChild(card);
    }
    root.appendChild(sc);
  }
  function metric(label, value, cls, delta) {
    return el("div", { class: "metric " + (cls || "") }, [
      el("div", { class: "label" }, [label]), el("div", { class: "value" }, [value]),
      delta ? el("div", { class: "delta small" }, [delta]) : document.createTextNode(""),
    ]);
  }

  // ── ② 공정 모니터링 ──
  const MON = { key: "clk_fcao", product: null, view: "trend" };
  function renderMonitor(root) {
    root.appendChild(el("h2", {}, ["공정 모니터링"]));
    const withData = SPEC.items.filter((it) => series(it.key).length > 1 || (it.byProduct && products(it.key).some((p) => series(it.key, p).length > 1)));
    if (!withData.length) { root.appendChild(el("div", { class: "note warn" }, ["표시할 수치 데이터가 없습니다. '📥 데이터 불러오기'에서 파일을 올리세요."])); return; }
    if (!withData.find((it) => it.key === MON.key)) MON.key = withData[0].key;
    const stages = [...new Set(withData.map((it) => it.stage))];
    const sel = el("select", { onchange: (e) => { MON.key = e.target.value; MON.product = null; drawMon(); } });
    stages.forEach((stg) => {
      const og = el("optgroup", { label: stg });
      withData.filter((it) => it.stage === stg).forEach((it) => og.appendChild(el("option", { value: it.key, ...(it.key === MON.key ? { selected: "selected" } : {}) }, [it.name + (it.unit ? ` (${it.unit})` : "")])));
      sel.appendChild(og);
    });
    const tb = el("div", { class: "toolbar" });
    tb.appendChild(el("label", { class: "field" }, [el("span", {}, ["항목"]), sel]));
    const prodWrap = el("label", { class: "field", id: "mon-prod-wrap" });
    tb.appendChild(prodWrap);
    const viewSel = el("select", { onchange: (e) => { MON.view = e.target.value; drawMon(); } }, []);
    [["trend", "추이"], ["spc", "관리도(SPC)"], ["hist", "분포"]].forEach(([v, l]) => viewSel.appendChild(el("option", { value: v, ...(v === MON.view ? { selected: "selected" } : {}) }, [l])));
    tb.appendChild(el("label", { class: "field" }, [el("span", {}, ["보기"]), viewSel]));
    root.appendChild(tb);
    root.appendChild(el("div", { class: "metrics", id: "mon-stats" }));
    const card = el("div", { class: "card" });
    card.appendChild(el("div", { class: "chart", id: "mon-chart" }));
    if (TOUCH) card.appendChild(el("div", { class: "hint" }, ["그래프를 탭하면 값이 표시됩니다."]));
    root.appendChild(card);
    drawMon();
  }
  function drawMon() {
    const it = ITEM[MON.key];
    const pw = $("#mon-prod-wrap"); pw.innerHTML = "";
    if (it.byProduct) {
      const ps = products(MON.key).filter((p) => p);
      if (!MON.product) MON.product = ps[0] || null;
      const ps2 = el("select", { onchange: (e) => { MON.product = e.target.value; drawMon(); } },
        ps.map((p) => el("option", { value: p, ...(p === MON.product ? { selected: "selected" } : {}) }, [p])));
      pw.appendChild(el("span", {}, ["품종"])); pw.appendChild(ps2); pw.style.display = "";
    } else { pw.style.display = "none"; MON.product = null; }
    const s = series(MON.key, MON.product);
    const lim = limFor(MON.key, MON.product);
    const vals = s.map((d) => d.v);
    const st = C.spcStats(vals, lim.lsl ?? null, lim.usl ?? null);
    const sb = $("#mon-stats"); sb.innerHTML = "";
    const lt = s.length ? s[s.length - 1] : null;
    const j = judge(lt && lt.v, lim);
    sb.appendChild(metric("최근값", lt ? fmt(lt.v, it.decimals) + " " + it.unit : "—", j.cls === "gray" ? "blue" : j.cls, j.label !== "—" ? j.label : (lt ? lt.t.slice(0, 10) : "")));
    sb.appendChild(metric("평균 ± 표준편차", fmt(st.mean, it.decimals) + " ± " + fmt(st.std, it.decimals), "blue", `n=${st.n}`));
    sb.appendChild(metric("최소 / 최대", fmt(Math.min(...vals), it.decimals) + " / " + fmt(Math.max(...vals), it.decimals), "blue"));
    sb.appendChild(metric("공정능력 Cpk", isNum(st.cpk) ? fmt(st.cpk, 2) : "—", isNum(st.cpk) ? (st.cpk >= 1.33 ? "green" : st.cpk >= 1.0 ? "amber" : "red") : "gray", isNum(st.cp) ? "Cp " + fmt(st.cp, 2) : "기준 필요"));
    const div = $("#mon-chart");
    const blue = "#2a78d6", red = "#dc2626", green = "#16a34a", amber = "#f59e0b";
    const layout = { height: 360, margin: { l: 48, r: 16, t: 10, b: 36 }, hovermode: "x unified", dragmode: TOUCH ? false : "zoom", showlegend: false, xaxis: { type: "date" }, yaxis: { title: it.unit || "" }, shapes: [], annotations: [] };
    function hline(y, color, text, dash) { if (!isNum(y)) return; layout.shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1.3, dash: dash || "dash" } }); layout.annotations.push({ xref: "paper", x: 0, y, xanchor: "left", yanchor: "bottom", text, showarrow: false, font: { size: 10, color } }); }
    let traces = [];
    if (MON.view === "hist") {
      traces = [{ type: "histogram", x: vals, marker: { color: blue } }];
      layout.yaxis = { title: "빈도" }; layout.xaxis = { title: it.unit || "" };
      hline(null); layout.shapes = []; layout.annotations = [];
      [["lsl", "하한", red], ["usl", "상한", red], ["target", "목표", green]].forEach(([k, lab, col]) => { if (isNum(lim[k])) { layout.shapes.push({ type: "line", yref: "paper", y0: 0, y1: 1, x0: lim[k], x1: lim[k], line: { color: col, width: 1.3, dash: "dash" } }); layout.annotations.push({ yref: "paper", y: 1, x: lim[k], yanchor: "top", text: `${lab} ${lim[k]}`, showarrow: false, font: { size: 10, color: col } }); } });
    } else if (MON.view === "spc") {
      const x = s.map((d) => d.t);
      const colors = s.map((d) => (isNum(st.ucl) && (d.v > st.ucl || d.v < st.lcl)) ? red : blue);
      traces = [{ type: "scatter", mode: "lines+markers", x, y: vals, line: { color: blue, width: 1.3 }, marker: { color: colors, size: 6 } }];
      hline(st.mean, "#64748b", "CL " + fmt(st.mean, it.decimals), "solid");
      hline(st.ucl, amber, "UCL(+3σ)"); hline(st.lcl, amber, "LCL(−3σ)");
    } else {
      traces = [{ type: "scatter", mode: s.length > 400 ? "lines" : "lines+markers", x: s.map((d) => d.t), y: vals, line: { color: blue, width: 1.5 }, marker: { color: blue, size: 4 } }];
      hline(lim.target, green, "목표 " + lim.target);
      hline(lim.lsl, red, "하한 " + lim.lsl); hline(lim.usl, red, "상한 " + lim.usl);
    }
    Plotly.react(div, traces, layout, { displayModeBar: false, responsive: true, scrollZoom: false });
  }

  // ── ③ 화학 계산기 ──
  const CHEM_IN = { CaO: 65.5, SiO2: 21.5, Al2O3: 5.3, Fe2O3: 3.2, SO3: 1.0, MgO: 1.8, K2O: 0.8, Na2O: 0.2, fcao: 1.0 };
  function renderChem(root) {
    root.appendChild(el("h2", {}, ["화학 계산기 (클링커·시멘트 산화물 → 계수치)"]));
    root.appendChild(el("p", { class: "hint" }, ["산화물(질량 %)을 입력하면 LSF·SM·IM·Bogue 광물·액상량을 계산합니다. 근거: Lea & Parker, ASTM C150 Bogue."]));
    const card = el("div", { class: "card" });
    const inWrap = el("div", { class: "inputs" });
    const fields = [["CaO", "CaO"], ["SiO2", "SiO₂"], ["Al2O3", "Al₂O₃"], ["Fe2O3", "Fe₂O₃"], ["MgO", "MgO"], ["SO3", "SO₃"], ["K2O", "K₂O"], ["Na2O", "Na₂O"], ["fcao", "자유석회 f-CaO"]];
    fields.forEach(([k, lab]) => inWrap.appendChild(numField(lab + " (%)", CHEM_IN[k], (v) => { CHEM_IN[k] = v; chemOut(); }, 0.1)));
    card.appendChild(inWrap);
    root.appendChild(card);
    root.appendChild(el("div", { class: "metrics", id: "chem-out" }));
    chemOut();
  }
  function chemOut() {
    const r = C.moduliFromOxides(CHEM_IN);
    const out = $("#chem-out"); out.innerHTML = "";
    [["LSF", r.LSF, 1, ""], ["SM(규산율)", r.SM, 2, ""], ["IM(철률)", r.IM, 2, ""],
    ["C₃S(Bogue)", r.C3S, 1, "%"], ["C₂S", r.C2S, 1, "%"], ["C₃A", r.C3A, 1, "%"], ["C₄AF", r.C4AF, 1, "%"],
    ["액상량 1450℃", r.liquid, 1, "%"], ["Na₂Oeq", r.na2oeq, 2, "%"], ["소성성지수 BI", r.BI, 2, ""]]
      .forEach(([l, v, d, u]) => out.appendChild(metric(l, fmt(v, d) + (u ? " " + u : ""), "blue")));
  }

  // ── ④ 배합 설계 (다원료 수동) ──
  const CATS = ["석회석", "실리카원", "알루미나원", "철질원", "기타"];
  const MAXCAT = 5;
  const DEFAULT_MATS = [
    { use: true, name: "석회석", category: "석회석", SiO2: 4, Al2O3: 1, Fe2O3: .5, CaO: 52, MgO: 1.2, SO3: .05, K2O: .2, Na2O: .05, LOI: 41.5, H2O: 3, Cr: 14, ratio: 80 },
    { use: true, name: "규석", category: "실리카원", SiO2: 88, Al2O3: 5, Fe2O3: 1.5, CaO: 1, MgO: .3, SO3: .02, K2O: 1, Na2O: .3, LOI: 2, H2O: 5, Cr: 20, ratio: 8 },
    { use: true, name: "점토(셰일)", category: "알루미나원", SiO2: 60, Al2O3: 16, Fe2O3: 6, CaO: 3, MgO: 2, SO3: .1, K2O: 2.5, Na2O: .8, LOI: 8, H2O: 12, Cr: 90, ratio: 7 },
    { use: true, name: "철광석", category: "철질원", SiO2: 15, Al2O3: 3, Fe2O3: 70, CaO: 2, MgO: 1, SO3: .05, K2O: .1, Na2O: .05, LOI: 3, H2O: 8, Cr: 300, ratio: 2 },
    { use: true, name: "석탄재(플라이애시)", category: "기타", SiO2: 52, Al2O3: 24, Fe2O3: 7, CaO: 5, MgO: 1.5, SO3: .8, K2O: 1.2, Na2O: .6, LOI: 4, H2O: 15, Cr: 190, ratio: 3 },
  ];
  const MATOX = ["SiO2", "Al2O3", "Fe2O3", "CaO", "MgO", "SO3", "K2O", "Na2O"];
  const MATOXL = { SiO2: "SiO₂", Al2O3: "Al₂O₃", Fe2O3: "Fe₂O₃", CaO: "CaO", MgO: "MgO", SO3: "SO₃", K2O: "K₂O", Na2O: "Na₂O" };
  let MATS = DEFAULT_MATS.map((m) => Object.assign({}, m));
  const KP = { coal_kg_per_t: 115, coal_ash: 14, ash_absorption: 100, coal_s: 1, so3_retention: 60, k2o_retention: 85, na2o_retention: 95, fcao: 1.0 };

  function catCount(cat) { return MATS.filter((m) => m.category === cat && String(m.name || "").trim() !== "").length; }
  function renderRawmix(root) {
    root.appendChild(el("h2", {}, ["원료 배합 설계 (수동)"]));
    root.appendChild(el("p", { class: "hint" }, ["구분별로 후보 원료를 최대 5종 등록하고, '사용'을 켠 원료의 건조 배합비(%)를 입력하면 생료·클링커 계수치와 Bogue 광물을 계산합니다. (자동 최적화는 설치형 앱 기능)"]));
    const tcard = el("div", { class: "card" });
    tcard.appendChild(el("div", { class: "tablewrap", id: "mat-table" }));
    // 후보 추가 컨트롤
    const ctl = el("div", { class: "btnrow" });
    const catSel = el("select", { id: "mat-cat", style: "width:auto;min-width:8rem" }, CATS.map((c) => el("option", { value: c, ...(c === "실리카원" ? { selected: "selected" } : {}) }, [c])));
    ctl.appendChild(catSel);
    ctl.appendChild(el("button", { class: "btn sec", onclick: () => { const c = catSel.value; if (catCount(c) < MAXCAT) { MATS.push(blankMat(c)); drawMatTable(); calcMix(); } } }, ["➕ 후보 추가"]));
    ctl.appendChild(el("button", { class: "btn ghost", onclick: () => { CATS.forEach((c) => { for (let i = catCount(c); i < MAXCAT; i++) MATS.push(blankMat(c)); }); drawMatTable(); calcMix(); } }, ["구분별 5칸 채우기"]));
    ctl.appendChild(el("button", { class: "btn ghost", onclick: () => { MATS = DEFAULT_MATS.map((m) => Object.assign({}, m)); drawMatTable(); calcMix(); } }, ["기본 예시로 초기화"]));
    ctl.appendChild(el("span", { class: "small", id: "mat-count" }));
    tcard.appendChild(ctl);
    root.appendChild(tcard);

    // 소성 조건
    const kcard = el("div", { class: "card" });
    kcard.appendChild(el("h3", {}, ["소성 조건 (석탄회 흡수·휘발 성분)"]));
    const kin = el("div", { class: "inputs" });
    [["coal_kg_per_t", "석탄 원단위(kg/t-clk)", 1], ["coal_ash", "석탄 회분(%)", .5], ["ash_absorption", "회분 흡수율(%)", 1], ["coal_s", "석탄 황분(%)", .1], ["so3_retention", "SO₃ 잔류율(%)", 5], ["k2o_retention", "K₂O 잔류율(%)", 5], ["na2o_retention", "Na₂O 잔류율(%)", 5], ["fcao", "예상 f-CaO(%)", .1]]
      .forEach(([k, lab, step]) => kin.appendChild(numField(lab, KP[k], (v) => { KP[k] = v; calcMix(); }, step)));
    kcard.appendChild(kin);
    root.appendChild(kcard);

    root.appendChild(el("div", { class: "metrics", id: "mix-sum" }));
    root.appendChild(el("div", { class: "cols2" }, [
      el("div", { class: "card" }, [el("h3", {}, ["생료·클링커 조성"]), el("div", { class: "tablewrap", id: "mix-comp" })]),
      el("div", { class: "card" }, [el("h3", {}, ["건조 배합비"]), el("div", { class: "chart", id: "mix-bar" })]),
    ]));
    root.appendChild(el("div", { class: "btnrow" }, [el("button", { class: "btn", onclick: exportMixExcel }, ["⬇️ 배합 설계서(엑셀)"])]));
    drawMatTable(); calcMix();
  }
  function blankMat(cat) { const m = { use: false, name: `${cat} 후보${catCount(cat) + 1}`, category: cat, LOI: 0, H2O: 0, Cr: 0, ratio: 0 }; MATOX.forEach((o) => (m[o] = 0)); return m; }
  function drawMatTable() {
    const host = $("#mat-table"); if (!host) return;
    const t = el("table");
    const head = ["사용", "원료명", "구분", ...MATOX.map((o) => MATOXL[o]), "강열감량", "수분%", "총Cr", "배합비%", ""];
    t.appendChild(el("tr", {}, head.map((h, i) => el("th", { class: i === 1 || i === 2 ? "txt" : "" }, [h]))));
    MATS.forEach((m, idx) => {
      const tr = el("tr");
      const chk = el("input", { type: "checkbox", ...(m.use ? { checked: "checked" } : {}) });
      chk.addEventListener("change", () => { m.use = chk.checked; calcMix(); updateMatCount(); });
      tr.appendChild(el("td", {}, [chk]));
      tr.appendChild(td(cellInput(m, "name", "text")));
      const sel = el("select", {}, CATS.map((c) => el("option", { value: c, ...(c === m.category ? { selected: "selected" } : {}) }, [c])));
      sel.addEventListener("change", () => { m.category = sel.value; updateMatCount(); });
      tr.appendChild(el("td", { class: "txt" }, [sel]));
      MATOX.forEach((o) => tr.appendChild(td(cellInput(m, o, "number"))));
      ["LOI", "H2O", "Cr", "ratio"].forEach((k) => tr.appendChild(td(cellInput(m, k, "number"))));
      tr.appendChild(td(el("button", { class: "btn ghost", style: "padding:3px 9px", onclick: () => { MATS.splice(idx, 1); drawMatTable(); calcMix(); } }, ["✕"])));
      t.appendChild(tr);
    });
    host.innerHTML = ""; host.appendChild(t); updateMatCount();
  }
  function cellInput(m, key, type) {
    const inp = el("input", { type: type === "number" ? "number" : "text", value: m[key] == null ? "" : m[key], step: "any", style: type === "number" ? "width:5.2rem;text-align:right" : "width:8rem;text-align:left", class: "editable" });
    inp.addEventListener("input", () => { m[key] = type === "number" ? (inp.value === "" ? 0 : +inp.value) : inp.value; if (key === "ratio" || type === "number") calcMix(); });
    return inp;
  }
  const td = (c) => el("td", {}, [c]);
  function updateMatCount() {
    const over = CATS.filter((c) => catCount(c) > MAXCAT);
    $("#mat-count").innerHTML = "구분별 등록: " + CATS.map((c) => `${c} ${catCount(c)}/${MAXCAT}`).join(" · ") + (over.length ? ` · ⚠️ ${over.join(",")} 권장 상한 초과` : "");
  }
  function calcMix() {
    const used = MATS.filter((m) => m.use);
    const sumEl = $("#mix-sum"); if (!sumEl) return;
    if (!used.length) { sumEl.innerHTML = ""; sumEl.appendChild(el("div", { class: "note warn" }, ["'사용'을 켠 원료가 없습니다."])); $("#mix-comp").innerHTML = ""; Plotly.purge($("#mix-bar")); return; }
    const ratios = used.map((m) => +m.ratio || 0);
    const sum = ratios.reduce((a, b) => a + b, 0);
    const r = C.predictClinker(MATS, ratios, KP, KP.fcao);
    sumEl.innerHTML = "";
    sumEl.appendChild(metric("배합비 합계", fmt(sum, 1) + " %", Math.abs(sum - 100) < .05 ? "green" : "amber", Math.abs(sum - 100) < .05 ? "정규화됨" : "합계 100%로 정규화 계산"));
    sumEl.appendChild(metric("클링커 LSF", fmt(r.LSF, 1), "blue", "생료 " + fmt(r.rawLsf, 1)));
    sumEl.appendChild(metric("클링커 SM", fmt(r.SM, 2), "blue"));
    sumEl.appendChild(metric("클링커 IM", fmt(r.IM, 2), "blue"));
    sumEl.appendChild(metric("C₃S(Bogue)", fmt(r.C3S, 1) + " %", "blue", "C₂S " + fmt(r.C2S, 1)));
    sumEl.appendChild(metric("액상량 1450℃", fmt(r.liquid, 1) + " %", "blue"));
    sumEl.appendChild(metric("생료/클링커", fmt(r.kilnFactor, 3) + " t/t", "blue", "흡수 석탄회 " + fmt(r.a, 4)));
    // 조성표
    const t = el("table");
    t.appendChild(el("tr", {}, [el("th", { class: "txt" }, ["성분"]), el("th", {}, ["생료(건조)%"]), el("th", {}, ["클링커 예측%"])]));
    MATOX.forEach((o) => t.appendChild(el("tr", {}, [el("td", { class: "txt" }, [MATOXL[o]]), el("td", {}, [fmt(r.raw[o], 2)]), el("td", {}, [fmt(r.clinker[o], 2)])])));
    t.appendChild(el("tr", {}, [el("td", { class: "txt" }, ["강열감량"]), el("td", {}, [fmt(r.raw.LOI, 2)]), el("td", {}, ["—"])]));
    $("#mix-comp").innerHTML = ""; $("#mix-comp").appendChild(t);
    // 배합비 막대
    Plotly.react($("#mix-bar"), [{ type: "bar", x: r.names, y: r.x.map((v) => v * 100), marker: { color: "#2a78d6" }, text: r.x.map((v) => fmt(v * 100, 1)), textposition: "outside" }],
      { height: 300, margin: { l: 40, r: 10, t: 10, b: 70 }, yaxis: { title: "건조 배합비(%)" }, xaxis: { tickangle: -20 } }, { displayModeBar: false, responsive: true });
    STATE.lastMix = r;
  }

  // ── ⑤ 6가크롬 ──
  const CR_IN = [
    { name: "석회석", amount: 1250, cr: 14, retention: 100 },
    { name: "점토(셰일)", amount: 95, cr: 90, retention: 100 },
    { name: "석탄재", amount: 40, cr: 190, retention: 100 },
    { name: "석탄(연료)", amount: 115, cr: 25, retention: 60 },
    { name: "내화물 마모", amount: 0.2, cr: 68420, retention: 100 },
  ];
  const CRP = { conv: 12, fraction: 95, media: 0.2, reducer: "FeSO4·7H2O", purity: 90, excess: 10, retention: 1.0, target: 10 };
  function renderChromium(root) {
    root.appendChild(el("h2", {}, ["시멘트 6가크롬(Cr⁶⁺)"]));
    root.appendChild(el("p", { class: "hint" }, ["원·부원료·연료·내화물의 총 Cr과 킬른 전환율로 클링커·시멘트 Cr⁶⁺을 추정하고, 목표 이하로 낮추는 환원제 투입량을 계산합니다. 기준: 국내 자율 20 mg/kg(KS L 5221), EU 2 mg/kg(EN 196-10)."]));
    const tcard = el("div", { class: "card" });
    tcard.appendChild(el("h3", {}, ["투입원 (클링커 1 t 기준)"]));
    tcard.appendChild(el("div", { class: "tablewrap", id: "cr-table" }));
    tcard.appendChild(el("div", { class: "btnrow" }, [el("button", { class: "btn sec", onclick: () => { CR_IN.push({ name: "추가 투입원", amount: 0, cr: 0, retention: 100 }); drawCrTable(); calcCr(); } }, ["➕ 투입원 추가"])]));
    root.appendChild(tcard);
    const pcard = el("div", { class: "card" });
    pcard.appendChild(el("h3", {}, ["전환·환원 조건"]));
    const pin = el("div", { class: "inputs" });
    pin.appendChild(numField("킬른 Cr⁶⁺ 전환율(%)", CRP.conv, (v) => { CRP.conv = v; calcCr(); }, 1));
    pin.appendChild(numField("시멘트 중 클링커 비율(%)", CRP.fraction, (v) => { CRP.fraction = v; calcCr(); }, 1));
    pin.appendChild(numField("분쇄매체 Cr⁶⁺ 기여(mg/kg)", CRP.media, (v) => { CRP.media = v; calcCr(); }, .1));
    const rsel = el("select", {}, Object.keys(C.REDUCERS).map((k) => el("option", { value: k, ...(k === CRP.reducer ? { selected: "selected" } : {}) }, [C.REDUCERS[k].label])));
    rsel.addEventListener("change", () => { CRP.reducer = rsel.value; const r = C.REDUCERS[rsel.value]; CRP.purity = r.purity; CRP.excess = r.excess; renderChromium($(".tab[data-tab=chromium]")); });
    pin.appendChild(el("label", { class: "field" }, [el("span", {}, ["환원제"]), rsel]));
    pin.appendChild(numField("순도(%)", CRP.purity, (v) => { CRP.purity = v; calcCr(); }, 1));
    pin.appendChild(numField("현장 과잉계수(배)", CRP.excess, (v) => { CRP.excess = v; calcCr(); }, 1));
    pin.appendChild(numField("실효계수(저장·열화)", CRP.retention, (v) => { CRP.retention = v; calcCr(); }, .05));
    pin.appendChild(numField("목표 Cr⁶⁺(mg/kg)", CRP.target, (v) => { CRP.target = v; calcCr(); }, 1));
    pcard.appendChild(pin);
    pcard.appendChild(el("div", { class: "hint" }, ["실효계수: 신품·저온 투입 1.0. FeSO₄를 고온(밀) 투입하면 저장·열화로 통상 0.6 전후(설치형 앱 기본값). 1.0은 이상적(최소) 투입량입니다."]));
    root.appendChild(pcard);
    root.appendChild(el("div", { class: "metrics", id: "cr-sum" }));
    drawCrTable(); calcCr();
  }
  function drawCrTable() {
    const host = $("#cr-table"); if (!host) return;
    const t = el("table");
    t.appendChild(el("tr", {}, [["투입원", "txt"], ["투입량(kg/t-clk)", ""], ["총Cr(mg/kg)", ""], ["이행률(%)", ""], ["", ""]].map(([h, c]) => el("th", { class: c }, [h]))));
    CR_IN.forEach((r, idx) => {
      const tr = el("tr");
      tr.appendChild(el("td", { class: "txt" }, [crCell(r, "name", "text")]));
      ["amount", "cr", "retention"].forEach((k) => tr.appendChild(el("td", {}, [crCell(r, k, "number")])));
      tr.appendChild(el("td", {}, [el("button", { class: "btn ghost", style: "padding:3px 9px", onclick: () => { CR_IN.splice(idx, 1); drawCrTable(); calcCr(); } }, ["✕"])]));
      t.appendChild(tr);
    });
    host.innerHTML = ""; host.appendChild(t);
  }
  function crCell(r, key, type) {
    const inp = el("input", { type: type === "number" ? "number" : "text", value: r[key], step: "any", class: "editable", style: type === "number" ? "width:7rem;text-align:right" : "width:9rem" });
    inp.addEventListener("input", () => { r[key] = type === "number" ? (inp.value === "" ? 0 : +inp.value) : inp.value; calcCr(); });
    return inp;
  }
  function calcCr() {
    const total = C.clinkerTotalCr(CR_IN);
    const crviClk = total * CRP.conv / 100;
    const crvi0 = crviClk * CRP.fraction / 100 + (+CRP.media || 0);
    const dose = C.requiredDose(crvi0, CRP.target, CRP.reducer, CRP.purity, CRP.excess, CRP.retention);
    const sum = $("#cr-sum"); if (!sum) return; sum.innerHTML = "";
    sum.appendChild(metric("클링커 총 Cr", fmt(total, 1) + " mg/kg", "blue"));
    sum.appendChild(metric("클링커 Cr⁶⁺", fmt(crviClk, 2) + " mg/kg", "blue", `전환율 ${CRP.conv}%`));
    const jc = crvi0 > C.LIMIT_KR ? "red" : crvi0 > CRP.target ? "amber" : "green";
    sum.appendChild(metric("시멘트 Cr⁶⁺(환원 전)", fmt(crvi0, 2) + " mg/kg", jc, crvi0 > C.LIMIT_KR ? "자율기준 20 초과" : crvi0 > CRP.target ? "목표 초과" : "목표 이내"));
    sum.appendChild(metric("필요 환원제", isFinite(dose) ? fmt(dose, 3) + " kg/t" : "—", dose > 0 ? "amber" : "green", isFinite(dose) ? `${C.REDUCERS[CRP.reducer].label.split("(")[0]} · ${fmt(dose * C.REDUCERS[CRP.reducer].price, 0)} 원/t` : ""));
    sum.appendChild(metric("투입 후 Cr⁶⁺(목표)", fmt(CRP.target, 1) + " mg/kg", "green", "환원제 투입 시"));
  }

  // ── ⑥ 데이터 불러오기 ──
  const ENGINE = window.INGEST.create(SPEC);
  const CONF = { high: ["✅", "확실"], mid: ["🔶", "추정·확인"], low: ["❓", "후보 여럿·확인"], none: ["⚪", "무시"] };

  function renderData(root) {
    root.appendChild(el("h2", {}, ["데이터 불러오기"]));
    root.appendChild(el("div", { class: "note", html: "LIMS·실험실 <b>엑셀·CSV</b>를 올리면 <b>파일 구조(머리글 줄·가로/세로 형식·단위 줄·날짜/시간 열)를 스스로 읽고</b> 필요한 항목만 뽑아 옵니다. 확실하지 않은 열만 물어보고, <b>한 번 확인하면 다음부터 자동</b>입니다. 모든 처리는 이 PC 브라우저 안에서만 일어납니다." }));
    const fz = el("div", { class: "filezone", id: "filezone", html: "📂 <b>엑셀·CSV 파일 선택</b> 또는 여기로 끌어다 놓기<div class='small'>양식을 맞출 필요 없이 LIMS에서 내보낸 그대로 올리세요</div>" });
    const fin = el("input", { type: "file", accept: ".xlsx,.xls,.csv", style: "display:none" });
    fin.addEventListener("change", (e) => { if (e.target.files[0]) loadFile(e.target.files[0]); e.target.value = ""; });
    fz.addEventListener("click", () => fin.click());
    fz.addEventListener("dragover", (e) => { e.preventDefault(); fz.classList.add("drag"); });
    fz.addEventListener("dragleave", () => fz.classList.remove("drag"));
    fz.addEventListener("drop", (e) => { e.preventDefault(); fz.classList.remove("drag"); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); });
    root.appendChild(fz); root.appendChild(fin);
    const pcard = el("div", { class: "card", style: "margin-top:12px" });
    pcard.appendChild(el("div", { class: "small", html: "또는 <b>엑셀에서 표를 복사(Ctrl+C) → 아래에 붙여넣기(Ctrl+V)</b> (파일 선택이 막힌 PC용) — 제목·머리글 줄까지 함께 복사하세요" }));
    pcard.appendChild(el("textarea", { id: "paste-box", rows: "4", style: "width:100%;margin-top:6px;border:1px solid var(--line);border-radius:8px;padding:8px;font-family:inherit", placeholder: "시료채취일시   시료명   시험항목   결과값\n2026-11-01 08:00   클링커   f-CaO   0.9" }));
    pcard.appendChild(el("div", { class: "btnrow" }, [el("button", { class: "btn sec", onclick: () => loadPaste($("#paste-box").value) }, ["붙여넣은 표 불러오기"])]));
    root.appendChild(pcard);
    root.appendChild(el("div", { id: "load-result" }));
    root.appendChild(el("div", { id: "map-panel", style: "display:none;margin-top:4px" }));
    renderLoadResult();
    root.appendChild(el("div", { class: "btnrow" }, [
      el("button", { class: "btn sec", onclick: () => { setData(deepCopy(RAW.sample), "sample"); STATE.loadedInfo = null; STATE.loadError = null; STATE.sheets = null; refreshBadge(); renderLoadResult(); refreshCurrentData(); $("#map-panel").style.display = "none"; } }, ["샘플 데이터로 보기"]),
      el("button", { class: "btn ghost", onclick: downloadTemplate }, ["⬇️ 입력 템플릿(엑셀, 선택)"]),
      el("button", { class: "btn ghost", onclick: exportDataExcel }, ["⬇️ 현재 데이터 내보내기(엑셀)"]),
      el("button", { class: "btn ghost", onclick: () => { try { Object.keys(localStorage).filter((k) => k.indexOf("qmsmap_") === 0).forEach((k) => localStorage.removeItem(k)); } catch (e) { /* file:// 차단 */ } STATE.loadedInfo = null; STATE.loadError = null; renderLoadResult(); $("#load-result").appendChild(el("div", { class: "note" }, ["기억된 열 지정을 모두 지웠습니다."])); } }, ["기억된 열 지정 초기화"]),
    ]));
    root.appendChild(el("div", { class: "card", id: "current-data", style: "margin-top:12px" }));
    refreshCurrentData();
  }
  function refreshCurrentData() {
    const info = $("#current-data"); if (!info) return; info.innerHTML = "";
    info.appendChild(el("h3", {}, ["현재 데이터"]));
    const [lo, hi] = dataPeriod();
    info.appendChild(el("p", { class: "small" }, [`출처: ${STATE.source === "sample" ? "샘플(데모)" : "불러온 데이터"}` + (lo ? ` · 기간 ${lo.slice(0, 10)} ~ ${hi.slice(0, 10)}` : " · (데이터 없음)")]));
    const tb = el("table"); tb.appendChild(el("tr", {}, [el("th", { class: "txt" }, ["공정"]), el("th", {}, ["행 수"]), el("th", { class: "txt" }, ["항목"])]));
    for (const t in STATE.data) { const T = STATE.data[t]; tb.appendChild(el("tr", {}, [el("td", { class: "txt" }, [SPEC.tables[t] ? SPEC.tables[t].label : t]), el("td", {}, [String(T.rows.length)]), el("td", { class: "txt small" }, [T.columns.map((c) => (ITEM[c] ? ITEM[c].name : c)).join(", ")])])); }
    info.appendChild(el("div", { class: "tablewrap" }, [tb]));
  }

  // 읽은 결과 요약(항상 표시)
  function renderLoadResult() {
    const res = $("#load-result"); if (!res) return; res.innerHTML = "";
    if (STATE.loadError) { res.appendChild(el("div", { class: "note warn" }, [STATE.loadError])); return; }
    const info = STATE.loadedInfo; if (!info) return;
    if (info.kind === "ship") { const c = renderShipLoadCard(); if (c) res.appendChild(c); return; }
    const card = el("div", { class: "card", style: "border:2px solid var(--green)" });
    card.appendChild(el("h3", {}, [`✅ ${info.file} — 불러오기 완료`]));
    info.sheets.forEach((s) => {
      const m = s.summary;
      const lines = [`<b>${esc(s.name)}</b>: ${m.layout === "long" ? "세로(시험 1건=1행) 형식" : "가로(시료 1행) 형식"}으로 인식 · 머리글 ${m.headerRow}행${m.unitRow ? " · 단위 줄 제외" : ""}`,
        `읽은 행 <b>${m.rowsRead}</b>건` + (m.rowsSkipped ? ` · 날짜가 없어 건너뜀 ${m.rowsSkipped}행(합계·빈 줄 등)` : "") + (m.censored ? ` · 부등호 값(&lt;, &gt;) ${m.censored}건은 숫자만 사용` : "")];
      m.perTable.forEach((p) => lines.push(`• ${esc(SPEC.tables[p.table].label)} ${p.rows}행: ${p.items.map((k) => esc(ITEM[k].name)).join(", ")}`));
      if (m.ignored.length) lines.push(`<span class="small">무시한 열: ${m.ignored.slice(0, 20).map(esc).join(", ")}</span>`);
      card.appendChild(el("div", { class: "small", style: "margin:6px 0;line-height:1.7", html: lines.join("<br>") }));
    });
    card.appendChild(el("div", { class: "btnrow" }, [
      el("button", { class: "btn", onclick: () => show("overview") }, ["종합 현황 보기"]), el("button", { class: "btn sec", onclick: () => show("monitor") }, ["공정 모니터링 보기"]),
      el("button", { class: "btn ghost", onclick: () => openPanel("읽은 방식을 확인·수정하세요. 바꾸고 ‘확인하고 불러오기’를 누르면 다시 반영됩니다.") }, ["읽은 방식 보기·수정"]),
    ]));
    res.appendChild(card);
  }

  // ── 불러오기 흐름 ──
  function sheetsFromBuffer(buf) {
    const wb = XLSX.read(new Uint8Array(buf), { type: "array", cellDates: false });
    return wb.SheetNames.map((sn) => ({ name: sn, aoa: XLSX.utils.sheet_to_json(wb.Sheets[sn], { header: 1, raw: true, defval: null, blankrows: true }) }));
  }
  function loadFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => { try { ingest(sheetsFromBuffer(e.target.result), file.name); } catch (err) { STATE.loadError = "파일을 읽지 못했습니다: " + err.message + " — 엑셀에서 표를 복사해 ‘붙여넣기’를 써 보세요."; renderLoadResult(); } };
    reader.onerror = () => { STATE.loadError = "파일을 읽지 못했습니다 — 회사 PC가 브라우저의 파일 접근을 막았을 수 있습니다. ‘붙여넣기’(엑셀에서 복사→붙여넣기)를 사용하세요."; renderLoadResult(); };
    reader.readAsArrayBuffer(file);
  }
  function loadPaste(text) {
    if (!text || !text.trim()) { STATE.loadError = "붙여넣은 내용이 없습니다. 엑셀에서 표(머리글 줄 포함)를 복사해 붙여넣으세요."; renderLoadResult(); return; }
    const sep = text.indexOf("\t") >= 0 ? "\t" : (text.indexOf(",") < 0 && text.indexOf(";") >= 0 ? ";" : ",");
    const aoa = text.replace(/\r/g, "").split("\n").filter((l) => l.length).map((l) => l.split(sep).map((c) => c.trim()));
    ingest([{ name: "붙여넣기", aoa }], "붙여넣은 표");
  }

  // 기억된 열 지정
  function hashStr(s) { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return "qmsmap_" + (h >>> 0).toString(36); }
  function sigOf(a) { return hashStr(a.cols.map((c) => ENGINE.nkey(c.header)).join("|")); }
  function loadSaved(sig) { try { return JSON.parse(localStorage.getItem(sig) || "null"); } catch (e) { return null; } }
  function storeSaved(sh) {
    const a = sh.a; const d = { layout: a.layout, headerRow: a.headerRow, roles: a.roles, cols: {}, pairs: {} };
    a.cols.forEach((c) => { if (c.role) d.cols[ENGINE.nkey(c.header)] = { role: c.role, key: c.key }; });
    (a.pairs || []).forEach((p) => { if (p.key) d.pairs[p.point + "\u0001" + p.test] = p.key; });
    try { localStorage.setItem(sh.sig, JSON.stringify(d)); } catch (e) { /* file:// 차단 시 무시 */ }
  }
  function applySaved(sh, saved) {
    sh.opts = { headerRow: saved.headerRow, layout: saved.layout, roles: saved.roles };
    sh.a = ENGINE.analyze(sh.aoa, Object.assign({ sheetName: sh.name }, sh.opts)); if (!sh.a) return;
    sh.a.cols.forEach((c) => { const s = saved.cols[ENGINE.nkey(c.header)]; if (s && c.role !== "ts" && !["time", "product", "point", "test", "value"].includes(c.role)) { c.role = s.role; c.key = s.key; c.conf = s.role === "item" ? "high" : c.conf; c.why = "기억된 지정"; } });
    (sh.a.pairs || []).forEach((p) => { const k = saved.pairs[p.point + "\u0001" + p.test]; if (k) { p.key = k; p.conf = "high"; p.why = "기억된 지정"; } });
    ENGINE.refresh(sh.a);
  }

  function mergeTables(list) {
    const out = {};
    list.forEach((tables) => {
      for (const t in tables) {
        if (!out[t]) { out[t] = deepCopy(tables[t]); continue; }
        const A = out[t], B = tables[t]; const cols = [...new Set(A.columns.concat(B.columns))]; const byProduct = A.byProduct || B.byProduct;
        const map = new Map();
        [[A, A.columns], [B, B.columns]].forEach(([T, tc]) => T.rows.forEach((r) => {
          const off = T.byProduct ? 2 : 1; const k = r[0] + "|" + (T.byProduct ? r[1] : "");
          if (!map.has(k)) map.set(k, { ts: r[0], prod: T.byProduct ? r[1] : "-", v: {} });
          tc.forEach((c, i) => { if (r[off + i] != null) map.get(k).v[c] = r[off + i]; });
        }));
        const rows = [...map.values()].sort((p, q) => (p.ts < q.ts ? -1 : 1)).map((x) => [x.ts].concat(byProduct ? [x.prod] : []).concat(cols.map((c) => (x.v[c] == null ? null : x.v[c]))));
        out[t] = { byProduct, columns: cols, rows };
      }
    });
    return out;
  }
  function commit(fileName) {
    const results = STATE.sheets.filter((s) => s.a && s.a.status.items > 0).map((s) => ({ s, r: ENGINE.extract(s.a) }));
    const merged = mergeTables(results.map((x) => x.r.tables));
    if (!Object.keys(merged).length) { STATE.loadError = "추출된 데이터가 없습니다. ‘일시’ 열과 항목을 지정했는지 확인하세요."; renderLoadResult(); return false; }
    setData(merged, "file"); STATE.loadError = null;
    STATE.loadedInfo = { file: fileName, sheets: results.map((x) => ({ name: x.s.name, summary: x.r.summary })) };
    refreshBadge(); renderLoadResult(); refreshCurrentData(); $("#map-panel").style.display = "none"; window.scrollTo({ top: 0 });
    return true;
  }
  function ingest(sheets, fileName) {
    STATE.fileName = fileName;
    const shipSheet = sheets.find((s) => s.aoa && SH.detect(s.aoa));      // 출하시멘트(LIMS 일일 로트 표) 형식이면 전용 처리
    if (shipSheet) { shipIngest(shipSheet, fileName); return; }
    STATE.sheets = sheets.filter((s) => s.aoa && s.aoa.length >= 2).map((s) => {
      const a = ENGINE.analyze(s.aoa, { sheetName: s.name });
      const sh = { name: s.name, aoa: s.aoa, a, opts: {}, sig: a ? sigOf(a) : "" };
      if (a) { const saved = loadSaved(sh.sig); if (saved) applySaved(sh, saved); }
      return sh;
    });
    if (!STATE.sheets.length) { STATE.loadError = "표를 찾지 못했습니다. 머리글 줄과 그 아래 값이 있어야 합니다."; renderLoadResult(); $("#map-panel").style.display = "none"; return; }
    const useful = STATE.sheets.filter((s) => s.a && (s.a.status.items > 0 || s.a.status.auto));
    const needs = STATE.sheets.filter((s) => s.a && s.a.status.items > 0 && !s.a.status.auto);
    if (useful.length && !needs.length && commit(fileName)) return;
    STATE.loadedInfo = null; STATE.loadError = null; renderLoadResult();
    const first = needs[0] || STATE.sheets[0];
    openPanel(needs.length ? "일부 열은 확실하지 않아 확인이 필요합니다(🔶 추정, ❓ 후보 여럿). 맞는지 보고 ‘확인하고 불러오기’를 누르세요. 확인한 내용은 기억해서 다음부터 자동으로 적용합니다."
      : "파일에서 항목을 자동으로 찾지 못했습니다. 아래에서 ‘일시’ 열과 항목 열을 지정해 주세요(한 번만 하면 기억합니다).", STATE.sheets.indexOf(first));
  }

  // ── 확인·수정 패널 ──
  function itemSelect(c) {
    const cur = c.role === "item" ? c.key : (["ts", "time", "product"].includes(c.role) ? c.role : "");
    const sel = el("select", { style: "min-width:14rem" });
    const opt = (v, label) => sel.appendChild(el("option", { value: v, ...(cur === v ? { selected: "selected" } : {}) }, [label]));
    opt("", "— 무시 —"); opt("ts", "📅 일시(날짜)"); opt("time", "🕒 시간(별도 열)"); opt("product", "품종(1종·3종)");
    [...new Set(SPEC.items.map((it) => it.stage))].forEach((stg) => {
      const og = el("optgroup", { label: stg });
      SPEC.items.filter((it) => it.stage === stg && !/^pred_/.test(it.key)).forEach((it) => og.appendChild(el("option", { value: it.key, ...(cur === it.key ? { selected: "selected" } : {}) }, [it.name + (it.unit ? ` (${it.unit})` : "")])));
      sel.appendChild(og);
    });
    return sel;
  }
  function pairSelect(p) {
    const sel = el("select", { style: "min-width:14rem" });
    sel.appendChild(el("option", { value: "", ...(!p.key ? { selected: "selected" } : {}) }, ["— 무시 —"]));
    [...new Set(SPEC.items.map((it) => it.stage))].forEach((stg) => {
      const og = el("optgroup", { label: stg });
      SPEC.items.filter((it) => it.stage === stg && !/^pred_/.test(it.key)).forEach((it) => og.appendChild(el("option", { value: it.key, ...(p.key === it.key ? { selected: "selected" } : {}) }, [it.name + (it.unit ? ` (${it.unit})` : "")])));
      sel.appendChild(og);
    });
    return sel;
  }
  function roleColSelect(a, role, label) {
    const sel = el("select", { style: "min-width:11rem" });
    sel.appendChild(el("option", { value: -1 }, ["— 없음 —"]));
    a.cols.forEach((c) => sel.appendChild(el("option", { value: c.idx, ...(a.roles[role] === c.idx ? { selected: "selected" } : {}) }, [`${c.header}`])));
    return el("label", { class: "field", style: "min-width:11rem;flex:1 1 11rem" }, [el("span", {}, [label]), sel]);
  }
  function openPanel(msg, focus) {
    const panel = $("#map-panel"); if (!panel || !STATE.sheets) return;
    panel.style.display = ""; panel.innerHTML = "";
    let si = focus || 0;
    const card = el("div", { class: "card", style: "border:2px solid var(--blue)" });
    card.appendChild(el("h3", {}, ["읽은 방식 확인·수정"]));
    if (msg) card.appendChild(el("div", { class: "note" }, [msg]));
    const body = el("div"); card.appendChild(body); panel.appendChild(card);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    function redo(opts) { const sh = STATE.sheets[si]; sh.opts = Object.assign(sh.opts || {}, opts); sh.a = ENGINE.analyze(sh.aoa, Object.assign({ sheetName: sh.name }, sh.opts)); draw(); }
    function draw() {
      body.innerHTML = ""; const sh = STATE.sheets[si]; const a = sh.a;
      if (STATE.sheets.length > 1) body.appendChild(el("label", { class: "field" }, [el("span", {}, ["시트"]), el("select", { style: "width:auto", onchange: (e) => { si = +e.target.value; draw(); } }, STATE.sheets.map((s, i) => el("option", { value: i, ...(i === si ? { selected: "selected" } : {}) }, [s.name + (s.a ? ` (${s.a.status.items}개 항목)` : " (표 아님)")])))]));
      if (!a) { body.appendChild(el("div", { class: "note warn" }, ["이 시트는 표로 읽을 수 없습니다(행·열이 너무 적음)."])); return; }
      const hrOpts = sh.aoa.slice(0, Math.min(sh.aoa.length, 15)).map((r, i) => el("option", { value: i, ...(i === a.headerRow ? { selected: "selected" } : {}) }, [`${i + 1}행: ${(r || []).slice(0, 6).map((x) => String(x == null ? "" : x)).join(" | ").slice(0, 60)}`]));
      body.appendChild(el("div", { class: "toolbar" }, [
        el("label", { class: "field", style: "flex:2 1 18rem" }, [el("span", {}, ["열 이름(머리글)이 있는 줄"]), el("select", { style: "width:100%", onchange: (e) => redo({ headerRow: +e.target.value, roles: null }) }, hrOpts)]),
        el("label", { class: "field" }, [el("span", {}, ["표 형식"]), el("select", { onchange: (e) => redo({ layout: e.target.value || null, roles: null }) }, [["", `자동(${a.layout === "long" ? "세로" : "가로"}로 인식)`], ["wide", "가로(시료 1행·항목이 열)"], ["long", "세로(시험 1건=1행)"]].map(([v, l]) => el("option", { value: v, ...((sh.opts.layout || "") === v ? { selected: "selected" } : {}) }, [l])))]),
      ]));
      const summary = el("div", { class: "small", style: "margin:8px 0" });
      const upd = () => { ENGINE.refresh(a); const st = a.status; const need = a.layout === "wide" ? a.cols.filter((c) => c.role === "item" && c.conf !== "high").length : a.pairs.filter((p) => p.key && p.conf !== "high").length; summary.innerHTML = `지금 설정으로 읽으면 — 📅 일시 ${a.roles.ts >= 0 ? "지정됨" : "<b style='color:var(--red)'>없음</b>"} · 항목 <b>${st.items}</b>개 · 확인 필요 ${need}개`; };
      if (a.layout === "wide") {
        const t = el("table"); t.appendChild(el("tr", {}, ["파일의 열", "이 열은 무엇?", "판단 근거", "값 미리보기"].map((h) => el("th", { class: "txt" }, [h]))));
        a.cols.forEach((c) => {
          if (c.n === 0) return;
          const sel = itemSelect(c);
          sel.addEventListener("change", () => {
            const v = sel.value;
            if (["ts", "time", "product"].includes(v)) { a.cols.forEach((x) => { if (x.role === v) { x.role = ""; x.conf = "none"; } }); c.role = v; c.key = null; }
            else if (v) { c.role = "item"; c.key = v; } else { c.role = ""; c.key = null; }
            c.conf = v ? "high" : "none"; c.why = v ? "사용자 지정" : "무시"; upd(); badge.textContent = CONF[c.conf][0];
          });
          const badge = el("span", { title: CONF[c.conf][1], style: "margin-right:6px" }, [CONF[c.conf][0]]);
          const warn = c.conf === "mid" || c.conf === "low";
          t.appendChild(el("tr", { ...(warn ? { style: "background:#fff7ed" } : {}) }, [
            el("td", { class: "txt" }, [c.group ? el("span", { class: "small" }, [c.group + " › "]) : document.createTextNode(""), el("b", {}, [c.header])]),
            el("td", { class: "txt" }, [badge, sel]), el("td", { class: "txt small", style: "white-space:normal;min-width:12rem" }, [c.why]), el("td", { class: "txt small" }, [c.sample.join(", ")])]));
        });
        body.appendChild(el("div", { class: "tablewrap" }, [t]));
      } else {
        body.appendChild(el("div", { class: "toolbar" }, [["ts", "📅 일시"], ["time", "🕒 시간(별도 열)"], ["test", "시험항목 열"], ["value", "결과값 열"], ["point", "시료·지점 열"], ["product", "품종 열"]].map(([r, l]) => { const f = roleColSelect(a, r, l); f.querySelector("select").addEventListener("change", (e) => { const roles = Object.assign({}, a.roles); roles[r] = +e.target.value; redo({ roles }); }); return f; })));
        const t = el("table"); t.appendChild(el("tr", {}, ["지점/시료", "시험항목", "건수", "값 미리보기", "이 항목은 무엇?", "판단 근거"].map((h) => el("th", { class: "txt" }, [h]))));
        a.pairs.forEach((p) => {
          const sel = pairSelect(p);
          const badge = el("span", { style: "margin-right:6px" }, [CONF[p.key ? p.conf : "none"][0]]);
          sel.addEventListener("change", () => { p.key = sel.value || null; p.conf = p.key ? "high" : "none"; p.why = p.key ? "사용자 지정" : "무시"; badge.textContent = CONF[p.conf][0]; upd(); });
          const warn = p.key && p.conf !== "high";
          t.appendChild(el("tr", { ...(warn ? { style: "background:#fff7ed" } : {}) }, [el("td", { class: "txt" }, [p.point || "—"]), el("td", { class: "txt" }, [el("b", {}, [p.test])]), el("td", {}, [String(p.n)]), el("td", { class: "txt small" }, [p.sample.join(", ")]), el("td", { class: "txt" }, [badge, sel]), el("td", { class: "txt small", style: "white-space:normal;min-width:12rem" }, [p.why])]));
        });
        body.appendChild(el("div", { class: "tablewrap" }, [t]));
      }
      body.appendChild(summary); upd();
      const rem = el("input", { type: "checkbox", checked: "checked" });
      body.appendChild(el("label", { class: "chk", style: "margin:4px 0" }, [rem, " 이 열 구성을 기억해서 다음부터 자동으로 불러오기"]));
      body.appendChild(el("div", { class: "btnrow" }, [
        el("button", { class: "btn", onclick: () => { if (rem.checked) STATE.sheets.forEach((s) => { if (s.a && s.a.status.items > 0) storeSaved(s); }); commit(STATE.fileName || "불러온 파일"); } }, ["✔ 확인하고 불러오기"]),
        el("button", { class: "btn ghost", onclick: () => { $("#map-panel").style.display = "none"; } }, ["닫기"]),
      ]));
    }
    draw();
  }

  // ── ⑦ 출하시멘트(LIMS 일일 로트 표) 모니터링 ──
  const SH = window.SHIP;
  STATE.ship = null;      // { records, items, info }
  const SUI = { key: "s28", view: "trend", range: "180", from: "", to: "", additive: "", mode: "all", noLowCl: false, showLim: false };
  const SLIM_KEY = "qmsship_limits", SDATA_KEY = "qmsship_data";
  const lsGet = (k) => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } };
  const lsDel = (k) => { try { localStorage.removeItem(k); } catch (e) { /* file:// 차단 */ } };

  const SLIMS = {};
  function loadShipLimits() {
    SH.ITEMS.forEach((it) => { SLIMS[it.key] = Object.assign({ lsl: null, usl: null, target: null, src: "" }, it.lim || {}); });
    const sv = lsGet(SLIM_KEY); if (sv) for (const k in sv) SLIMS[k] = Object.assign({ lsl: null, usl: null, target: null }, sv[k], { src: "사용자 설정" });
  }
  loadShipLimits();
  const slim = (k) => SLIMS[k] || { lsl: null, usl: null, target: null, src: "" };
  function shipFmt(it, v, withUnit) {
    if (!isNum(v)) return "—";
    if (it.hhmm) { const m = Math.round(v); return `${fmt(m, 0)}분 (${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")})`; }
    return fmt(v, it.dec) + (withUnit && it.unit ? " " + it.unit : "");
  }
  const shipItem = (k) => (STATE.ship && STATE.ship.items.find((i) => i.key === k)) || null;
  const isSingle = (r) => r.nShip === 1 && r.shipsOk;

  function shipRecs() {
    const all = (STATE.ship && STATE.ship.records) || []; if (!all.length) return [];
    let from = "", to = "9999";
    if (SUI.range === "custom") { from = SUI.from || ""; to = SUI.to ? SUI.to + "~" : "9999"; }
    else if (SUI.range !== "all") from = new Date(Date.parse(all[all.length - 1].date) - (+SUI.range) * 864e5).toISOString().slice(0, 10);
    return all.filter((r) => r.date >= from && r.date <= to && (!SUI.additive || r.additive === SUI.additive)
      && (SUI.mode === "all" || (SUI.mode === "single" ? isSingle(r) : r.nShip >= 2)) && !(SUI.noLowCl && r.lowCl));
  }
  function shipPts(recs, key) { const o = []; recs.forEach((r) => { const v = r.v[key]; if (isNum(v)) o.push({ t: r.date, v: +v, r }); }); return o; }

  // 항목 한 줄 요약(종합표용)
  function shipSummary(recs, it) {
    const pts = shipPts(recs, it.key); const lim = slim(it.key);
    const st = SH.stats(pts.map((p) => p.v), lim);
    const fl = SH.flags(pts, st, lim);
    const last = pts.length ? pts[pts.length - 1] : null;
    const tail = fl.slice(-10);
    const nSpec = fl.filter((f) => f.spec).length, nOut = fl.filter((f) => f.out3).length;
    let status = "gray", label = "자료 부족";
    if (it.setting) { status = "gray"; label = "배합 설정값(판정 제외)"; }
    else if (pts.length >= 5) {
      if (tail.some((f) => f.spec)) { status = "red"; label = "최근 10건 중 기준 이탈"; }
      else if (tail.some((f) => f.out3)) { status = "amber"; label = "최근 10건 중 3σ 이탈"; }
      else if (tail.some((f) => f.run)) { status = "yellow"; label = "같은 쪽 9점 연속(참고)"; }
      else { status = "green"; label = "정상"; }
    }
    return { it, pts, st, fl, last, nSpec, nOut, status, label, missing: recs.length - pts.length, lim };
  }
  const SDOT = { red: "🔴", amber: "🟠", yellow: "🟡", green: "🟢", gray: "⚪" };

  function renderShip(root) {
    root.appendChild(el("h2", {}, ["출하시멘트 모니터링"]));
    if (!STATE.ship || !STATE.ship.records.length) {
      root.appendChild(el("div", { class: "note", html: "LIMS 출하시멘트 엑셀(채취일·첨가재명칭·석회석비율·LOI·강도·Blaine·비고(선박명) 등이 있는 표)을 올리면 <b>자동으로 인식</b>해 이 화면에서 항목별 추이·관리도·선박별·배합별 비교를 보여 줍니다. 한 번 올리면 이후 같은 양식은 그대로 올리면 됩니다(새 파일의 같은 날짜는 덮어쓰기, 새 날짜는 추가)." }));
      const fz = el("div", { class: "filezone", html: "📂 <b>출하시멘트 엑셀 선택</b> 또는 여기로 끌어다 놓기" });
      const fin = el("input", { type: "file", accept: ".xlsx,.xls,.csv", style: "display:none" });
      fin.addEventListener("change", (e) => { if (e.target.files[0]) loadFile(e.target.files[0]); e.target.value = ""; });
      fz.addEventListener("click", () => fin.click());
      fz.addEventListener("dragover", (e) => { e.preventDefault(); fz.classList.add("drag"); });
      fz.addEventListener("dragleave", () => fz.classList.remove("drag"));
      fz.addEventListener("drop", (e) => { e.preventDefault(); fz.classList.remove("drag"); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); });
      root.appendChild(fz); root.appendChild(fin);
      return;
    }
    const S = STATE.ship;
    // 인식 결과(접기)
    const det = el("details", { class: "card", style: "padding:10px 16px" });
    det.appendChild(el("summary", { style: "cursor:pointer;font-weight:700" }, [`📋 파일 인식 결과 — ${S.info.file} · ${S.records.length}건 (${S.records[0].date} ~ ${S.records[S.records.length - 1].date})`]));
    det.appendChild(el("div", { class: "small", style: "line-height:1.7;margin-top:6px", html: shipInfoHtml(S.info) }));
    root.appendChild(det);

    // 필터
    const adds = [...new Set(S.records.map((r) => r.additive).filter(Boolean))];
    const tb = el("div", { class: "toolbar" });
    const selOf = (opts, cur, fn) => { const s = el("select", { onchange: (e) => fn(e.target.value) }); opts.forEach(([v, l]) => s.appendChild(el("option", { value: v, ...(String(cur) === String(v) ? { selected: "selected" } : {}) }, [l]))); return s; };
    tb.appendChild(el("label", { class: "field" }, [el("span", {}, ["기간"]), selOf([["all", "전체"], ["30", "최근 30일"], ["90", "최근 90일"], ["180", "최근 180일"], ["365", "최근 1년"], ["custom", "직접 지정"]], SUI.range, (v) => { SUI.range = v; refreshShip(); })]));
    if (SUI.range === "custom") {
      tb.appendChild(el("label", { class: "field" }, [el("span", {}, ["시작"]), el("input", { type: "date", value: SUI.from, onchange: (e) => { SUI.from = e.target.value; refreshShip(); } })]));
      tb.appendChild(el("label", { class: "field" }, [el("span", {}, ["끝"]), el("input", { type: "date", value: SUI.to, onchange: (e) => { SUI.to = e.target.value; refreshShip(); } })]));
    }
    if (adds.length > 1) tb.appendChild(el("label", { class: "field" }, [el("span", {}, ["첨가재"]), selOf([["", "전체"]].concat(adds.map((a) => [a, a])), SUI.additive, (v) => { SUI.additive = v; refreshShip(); })]));
    tb.appendChild(el("label", { class: "field" }, [el("span", {}, ["모선 수"]), selOf([["all", "전체"], ["single", "1모선(단독 시험)만"], ["multi", "2모선 이상(평균값)만"]], SUI.mode, (v) => { SUI.mode = v; refreshShip(); })]));
    if (S.records.some((r) => r.lowCl)) {
      const cb = el("input", { type: "checkbox", ...(SUI.noLowCl ? { checked: "checked" } : {}) }); cb.addEventListener("change", () => { SUI.noLowCl = cb.checked; refreshShip(); });
      tb.appendChild(el("label", { class: "chk field", style: "align-self:flex-end" }, [cb, " ‘저염’ 표기일 제외"]));
    }
    root.appendChild(tb);
    const body = el("div", { id: "ship-body" }); root.appendChild(body);
    drawShipSections(body);
  }
  function refreshShip() { const y = window.scrollY; show("ship"); window.scrollTo({ top: y }); }   // 필터 막대(직접 지정 칸)까지 다시 그림

  function shipInfoHtml(info) {
    const R = info.report; const L = [];
    L.push(`읽은 행 <b>${R.rowsRead}</b>건 · 머리글 ${R.headerRow + 1}행` + (R.rowsSkipped ? ` · 날짜가 없어 건너뜀 ${R.rowsSkipped}행` : "") + (info.added != null ? ` · 기존 대비 새로 추가 ${info.added}건 / 덮어쓰기 ${info.replaced}건` : ""));
    L.push(`인식한 항목 ${R.found.length}개: ` + R.found.map((f) => `${esc(SH.BY[f.key].name)}←<span class="small">${esc(f.header)}</span>`).join(", "));
    if (R.missing.length) L.push(`<b style="color:var(--amber)">찾지 못한 항목:</b> ${R.missing.map((k) => esc(SH.BY[k].name)).join(", ")} (데이터 불러오기 탭에서 열을 지정할 수 있습니다)`);
    const zk = Object.keys(R.zeros).filter((k) => !k.startsWith("x:")).map((k) => `${esc(SH.BY[k].name)} ${R.zeros[k]}건`);
    L.push(`값이 <b>0</b>인 칸은 ‘미시험’으로 보고 계산에서 뺐습니다${zk.length ? ": " + zk.join(", ") : ""} (예: 28일 강도는 시험 전이라 0)`);
    if (R.shipsFound) {
      const top = Object.entries(R.shipCount).sort((a, b) => b[1] - a[1]).slice(0, 14).map(([n, c]) => `${esc(n)} ${c}`).join(" · ");
      L.push(`비고(선박) 해석: 선박 ${R.nShips}척 — ${top}`);
      if (R.shipUnsure.length) L.push(`<b style="color:var(--amber)">비고를 확신하지 못한 ${R.shipUnsure.length}건</b>은 ‘1모선 단독’ 분석에서 제외했습니다 (예: ${R.shipUnsure.slice(0, 4).map((u) => esc(u.date + " “" + u.raw + "”")).join(", ")})`);
    }
    if (R.extras.length) L.push(`<span class="small">그 밖에 항목 목록에서 고를 수 있는 열 ${R.extras.length}개: ${R.extras.slice(0, 12).map(esc).join(", ")}${R.extras.length > 12 ? " …" : ""}</span>`);
    return L.join("<br>");
  }

  // 종합표 + 상세
  function drawShipSections(body) {
    const S = STATE.ship; const recs = shipRecs();
    body.innerHTML = "";
    if (!recs.length) { body.appendChild(el("div", { class: "note warn" }, ["선택한 조건에 맞는 자료가 없습니다. 기간·첨가재·모선 조건을 바꿔 보세요."])); return; }
    const core = S.items.filter((i) => !i.extra);
    const sums = core.map((it) => shipSummary(recs, it));
    // KPI
    const nSingle = recs.filter(isSingle).length;
    const red = sums.filter((s) => s.status === "red").length, amb = sums.filter((s) => s.status === "amber").length, yel = sums.filter((s) => s.status === "yellow").length;
    const m = el("div", { class: "metrics" });
    m.appendChild(metric("분석 대상", `${recs.length}건`, "blue", `${recs[0].date} ~ ${recs[recs.length - 1].date}`));
    m.appendChild(metric("1모선 단독 시험", `${nSingle}건`, "blue", `${Math.round(nSingle / recs.length * 100)}% · 나머지는 복수 모선 평균`));
    m.appendChild(metric("기준 이탈 항목(최근 10건)", `${red}개`, red ? "red" : "green", red ? "아래 표 🔴 확인" : "이상 없음"));
    m.appendChild(metric("관리한계(3σ) 이탈 항목", `${amb}개`, amb ? "amber" : "green", yel ? `최근 10건 기준 · 치우침 참고 ${yel}개` : "최근 10건 기준"));
    body.appendChild(m);

    // 종합표
    const card = el("div", { class: "card", style: "margin-top:14px" });
    card.appendChild(el("h3", {}, ["핵심 항목 한눈에"]));
    card.appendChild(el("div", { class: "hint", html: "행을 누르면 아래에 그 항목의 상세 그래프가 열립니다. 상태: 🔴 최근 10건 중 기준(규격·사내) 이탈 · 🟠 최근 10건 중 관리한계(평균±3σ) 이탈 · 🟡 같은 쪽 9점 연속 치우침(참고) · 🟢 정상 · ⚪ 판정 제외·자료 부족(5건 미만)<br>관리한계는 선택한 기간 데이터의 평균±3×표준편차입니다. 배합이 바뀐 구간이 섞이면 넓어지므로 기간·첨가재 필터로 구간을 좁혀 보세요(Nelson 규칙 1·2; Nelson, 1984, J. Quality Technology 16(4))." }));
    const t = el("table", { class: "stbl" });
    t.appendChild(el("tr", {}, ["", "항목", "최근값", "평균", "표준편차", "최소 ~ 최대", "규격·기준", "기준이탈", "3σ이탈", "미시험", "판정"].map((h, i) => el("th", { class: i === 1 || i === 10 || i === 6 ? "txt" : "" }, [h]))));
    let grp = "";
    sums.forEach((s) => {
      const it = s.it;
      if (it.group !== grp) { grp = it.group; t.appendChild(el("tr", {}, [el("td", { colspan: "11", class: "txt", style: "background:#f1f5f9;font-weight:700" }, [grp])])); }
      const lim = s.lim; const rng = lim.lsl != null && lim.usl != null ? `${lim.lsl} ~ ${lim.usl}` : lim.usl != null ? `≤ ${lim.usl}` : lim.lsl != null ? `≥ ${lim.lsl}` : "—";
      const tr = el("tr", { style: "cursor:pointer" + (SUI.key === it.key ? ";background:#eff6ff" : ""), onclick: () => { SUI.key = it.key; drawShipSections(body); const d = $("#ship-detail"); if (d) d.scrollIntoView({ behavior: "smooth", block: "start" }); } }, [
        el("td", {}, [SDOT[s.status]]), el("td", { class: "txt" }, [el("b", {}, [it.name]), document.createTextNode(it.unit && !it.hhmm ? ` (${it.unit})` : "")]),
        el("td", {}, [s.last ? shipFmt(it, s.last.v) : "—"]), el("td", {}, [shipFmt(it, s.st.mean)]), el("td", {}, [isFinite(s.st.sd) ? fmt(s.st.sd, it.dec + 1) : "—"]),
        el("td", {}, [s.pts.length ? shipFmt(it, s.st.min) + " ~ " + shipFmt(it, s.st.max) : "—"]),
        el("td", { class: "txt small" }, [rng]), el("td", {}, [lim.lsl == null && lim.usl == null ? "—" : String(s.nSpec)]), el("td", {}, [String(s.nOut)]),
        el("td", { title: "0 또는 빈칸(시험 전)" }, [s.missing ? String(s.missing) : "0"]), el("td", { class: "txt small" }, [s.label]),
      ]);
      t.appendChild(tr);
    });
    card.appendChild(el("div", { class: "tablewrap" }, [t]));
    body.appendChild(card);

    // 상세
    const det = el("div", { class: "card", id: "ship-detail" });
    det.appendChild(el("h3", {}, ["항목 상세"]));
    const items = S.items;
    const sel = el("select", { onchange: (e) => { SUI.key = e.target.value; drawShipSections(body); } });
    [...new Set(items.map((i) => i.group))].forEach((g) => { const og = el("optgroup", { label: g }); items.filter((i) => i.group === g).forEach((i) => og.appendChild(el("option", { value: i.key, ...(i.key === SUI.key ? { selected: "selected" } : {}) }, [i.name + (i.unit ? ` (${i.unit})` : "")]))); sel.appendChild(og); });
    if (!items.find((i) => i.key === SUI.key)) SUI.key = items[0].key;
    const views = [["trend", "추이"], ["spc", "관리도(SPC)"], ["hist", "분포"], ["month", "월별"], ["ship", "선박별(단독)"], ["combo", "배합별"]];
    const vsel = el("select", { onchange: (e) => { SUI.view = e.target.value; drawShipSections(body); } }, views.map(([v, l]) => el("option", { value: v, ...(v === SUI.view ? { selected: "selected" } : {}) }, [l])));
    det.appendChild(el("div", { class: "toolbar" }, [el("label", { class: "field", style: "flex:2 1 14rem" }, [el("span", {}, ["항목"]), sel]), el("label", { class: "field" }, [el("span", {}, ["보기"]), vsel])]));
    const stats = el("div", { class: "metrics", id: "ship-stats" }); det.appendChild(stats);
    det.appendChild(el("div", { class: "chart", id: "ship-chart", style: "margin-top:10px" }));
    det.appendChild(el("div", { id: "ship-extra" }));
    if (TOUCH) det.appendChild(el("div", { class: "hint" }, ["그래프를 탭하면 값이 표시됩니다."]));
    body.appendChild(det);
    drawShipDetail(recs);

    // 기준값 설정
    const lc = el("details", { class: "card" });
    lc.appendChild(el("summary", { style: "cursor:pointer;font-weight:700" }, ["⚙️ 규격·관리 기준값 설정 (하한·상한·목표)"]));
    lc.appendChild(el("div", { class: "hint", html: `초기값은 ${esc(SH.KS_NOTE)}입니다 — <b>이 환경에서 원문을 확인하지 못했으므로 사내 규격·KS 원문과 대조해 고쳐 주세요.</b> 고친 값은 이 PC 브라우저에 기억됩니다. 비워 두면 해당 기준 없이 표시합니다.` }));
    const lt = el("table"); lt.appendChild(el("tr", {}, ["항목", "하한(LSL)", "상한(USL)", "목표", "출처"].map((h, i) => el("th", { class: i === 0 || i === 4 ? "txt" : "" }, [h]))));
    core.forEach((it) => {
      const L = slim(it.key);
      const inp = (f) => { const i = el("input", { type: "number", step: "any", class: "editable", style: "width:6.5rem;text-align:right", value: L[f] == null ? "" : L[f] }); i.addEventListener("change", () => { SLIMS[it.key] = Object.assign({}, slim(it.key), { [f]: i.value === "" ? null : +i.value, src: "사용자 설정" }); const sv = {}; for (const k in SLIMS) if (SLIMS[k].src === "사용자 설정") sv[k] = { lsl: SLIMS[k].lsl, usl: SLIMS[k].usl, target: SLIMS[k].target }; lsSet(SLIM_KEY, sv); drawShipSections(body); }); return i; };
      lt.appendChild(el("tr", {}, [el("td", { class: "txt" }, [it.name + (it.hhmm ? " (분)" : "")]), el("td", {}, [inp("lsl")]), el("td", {}, [inp("usl")]), el("td", {}, [inp("target")]), el("td", { class: "txt small" }, [L.src || "—"])]));
    });
    lc.appendChild(el("div", { class: "tablewrap" }, [lt]));
    lc.appendChild(el("div", { class: "btnrow" }, [el("button", { class: "btn ghost", onclick: () => { lsDel(SLIM_KEY); loadShipLimits(); drawShipSections(body); } }, ["초기값으로 되돌리기"])]));
    body.appendChild(lc);
    body.appendChild(el("div", { class: "hint", html: "※ 항목 단위: Cl(XRF)·45㎛·주도·Flow는 파일에 단위 표기가 없어 값 규모로 추정했습니다(Cl=ppm, 45㎛=잔사 %, 주도=%). TA는 Na₂O+0.658·K₂O와 일치(실제 파일 검증). 0은 ‘미시험’으로 처리합니다." }));
  }

  function drawShipDetail(recs) {
    const it = shipItem(SUI.key); if (!it) return;
    const pts = shipPts(recs, it.key); const lim = slim(it.key);
    const st = SH.stats(pts.map((p) => p.v), lim); const fl = SH.flags(pts, st, lim);
    const sb = $("#ship-stats"); sb.innerHTML = "";
    const last = pts.length ? pts[pts.length - 1] : null;
    const lastSpec = last && ((lim.lsl != null && last.v < lim.lsl) || (lim.usl != null && last.v > lim.usl));
    sb.appendChild(metric("최근값", last ? shipFmt(it, last.v, true) : "—", lastSpec ? "red" : "blue", last ? last.t : ""));
    sb.appendChild(metric("평균 ± 표준편차", `${shipFmt(it, st.mean)} ± ${isFinite(st.sd) ? fmt(st.sd, it.dec + 1) : "—"}`, "blue", `n=${st.n}`));
    sb.appendChild(metric("최소 / 최대", `${shipFmt(it, st.min)} / ${shipFmt(it, st.max)}`, "blue"));
    sb.appendChild(metric("Cpk", isFinite(st.cpk) ? fmt(st.cpk, 2) : "—", isFinite(st.cpk) ? (st.cpk >= 1.33 ? "green" : st.cpk >= 1 ? "amber" : "red") : "gray", isFinite(st.cpk) ? "규격 대비 여유" : "기준값 필요"));
    sb.appendChild(metric("3σ 이탈 / 기준 이탈", `${fl.filter((f) => f.out3).length} / ${fl.filter((f) => f.spec).length}건`, fl.some((f) => f.spec) ? "red" : fl.some((f) => f.out3) ? "amber" : "green"));
    const div = $("#ship-chart"); const ex = $("#ship-extra"); ex.innerHTML = "";
    if (!pts.length) { Plotly.purge(div); div.innerHTML = ""; ex.appendChild(el("div", { class: "note warn" }, ["선택한 조건에 이 항목의 값이 없습니다(시험 전 0은 제외)."])); return; }
    const blue = "#2a78d6", red = "#dc2626", green = "#16a34a", amber = "#f59e0b", gray = "#64748b";
    const addNames = [...new Set(pts.map((p) => p.r.additive || "미표기"))].sort();
    const PAL = ["#2a78d6", "#f59e0b", "#16a34a", "#9333ea", "#0891b2"]; const colorOf = (a) => PAL[addNames.indexOf(a) % PAL.length];
    const layout = { height: 400, margin: { l: 52, r: 16, t: 10, b: 40 }, hovermode: "closest", dragmode: TOUCH ? false : "zoom", showlegend: true, legend: { orientation: "h", y: -0.18 }, xaxis: { type: "date" }, yaxis: { title: it.unit || "" }, shapes: [], annotations: [] };
    const hline = (y, color, text, dash) => { if (!isNum(y)) return; layout.shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1.3, dash: dash || "dash" } }); layout.annotations.push({ xref: "paper", x: 1, y, xanchor: "right", yanchor: "bottom", text, showarrow: false, font: { size: 10, color } }); };
    const hov = (p) => `${p.t} · ${shipFmt(it, p.v, true)}<br>${p.r.additive || ""} 석회석 ${p.r.v.ls ?? "-"}% / 첨가재 ${p.r.v.addr ?? "-"}%<br>${p.r.ships.join(", ") || "선박 미기재"} (${isSingle(p.r) ? "단독" : p.r.nShip + "모선 평균"})`;
    let traces = [];
    const ptsTrace = (arr, name, color, symbol) => ({ type: "scatter", mode: "markers", name, x: arr.map((p) => p.t), y: arr.map((p) => p.v), text: arr.map(hov), hovertemplate: "%{text}<extra></extra>", marker: { color: arr.map((p, i) => (p.mark || color)), size: 6, symbol, line: { width: 0 } } });
    if (SUI.view === "trend" || SUI.view === "spc") {
      const spc = SUI.view === "spc";
      pts.forEach((p, i) => { p.mark = spc && (fl[i].out3 || fl[i].run) ? (fl[i].out3 ? red : amber) : null; });
      traces.push({ type: "scatter", mode: "lines", name: "연결선", x: pts.map((p) => p.t), y: pts.map((p) => p.v), line: { color: "#cbd5e1", width: 1 }, hoverinfo: "skip", showlegend: false });
      addNames.forEach((a) => {
        [["단독", "circle", (p) => isSingle(p.r)], ["복수 평균", "diamond", (p) => !isSingle(p.r)]].forEach(([lab, sym, fn]) => {
          const arr = pts.filter((p) => (p.r.additive || "미표기") === a && fn(p)); if (arr.length) traces.push(ptsTrace(arr, `${a} · ${lab}`, colorOf(a), sym));
        });
      });
      if (!spc) {
        const W = 30, ma = pts.map((_, i) => { const s = pts.slice(Math.max(0, i - W + 1), i + 1).map((p) => p.v); return SH.mean(s); });
        traces.push({ type: "scatter", mode: "lines", name: `${W}건 이동평균`, x: pts.map((p) => p.t), y: ma, line: { color: "#0f172a", width: 2 }, hoverinfo: "skip" });
        hline(lim.target, green, "목표 " + lim.target); hline(lim.lsl, red, "하한 " + lim.lsl); hline(lim.usl, red, "상한 " + lim.usl);
        ex.appendChild(el("div", { class: "hint" }, ["● 단독 시험(1모선) · ◆ 복수 모선 평균 · 색 = 첨가재. 선 = 30건 이동평균."]));
      } else {
        hline(st.mean, gray, "CL " + fmt(st.mean, it.dec + 1), "solid"); hline(st.ucl, amber, "UCL(+3σ) " + fmt(st.ucl, it.dec + 1)); hline(st.lcl, amber, "LCL(−3σ) " + fmt(st.lcl, it.dec + 1));
        hline(lim.lsl, red, "하한 " + lim.lsl, "dot"); hline(lim.usl, red, "상한 " + lim.usl, "dot");
        ex.appendChild(el("div", { class: "hint", html: `🔴 3σ 밖 · 🟠 같은 쪽 9점 연속(Nelson 규칙 2). 관리한계는 선택 기간 평균±3×표준편차. 배합(첨가재·비율)이 바뀐 구간은 평균이 달라 관리한계 밖으로 보일 수 있으니 ‘첨가재’ 필터로 나눠 보세요.` }));
      }
    } else if (SUI.view === "hist") {
      const v = pts.map((p) => p.v), lo = st.min, hi = st.max, k = Math.max(8, Math.min(30, Math.round(Math.sqrt(v.length) * 1.6)));
      const w = (hi - lo) / k || 1, cnt = new Array(k).fill(0); v.forEach((x) => { cnt[Math.min(k - 1, Math.floor((x - lo) / w))]++; });
      traces = [{ type: "bar", x: cnt.map((_, i) => lo + w * (i + 0.5)), y: cnt, width: w * 0.95, marker: { color: blue }, hovertemplate: "%{x:.2f} 부근: %{y}건<extra></extra>" }];
      layout.showlegend = false; layout.yaxis = { title: "건수" }; layout.xaxis = { title: it.unit || "" };
      [["lsl", "하한", red], ["usl", "상한", red], ["target", "목표", green]].forEach(([f, lab, col]) => { if (isNum(lim[f])) layout.shapes.push({ type: "line", yref: "paper", y0: 0, y1: 1, x0: lim[f], x1: lim[f], line: { color: col, width: 1.5, dash: "dash" } }); });
      layout.shapes.push({ type: "line", yref: "paper", y0: 0, y1: 1, x0: st.mean, x1: st.mean, line: { color: gray, width: 1.5 } });
    } else if (SUI.view === "month") {
      const g = {}; pts.forEach((p) => { (g[p.t.slice(0, 7)] = g[p.t.slice(0, 7)] || []).push(p.v); });
      const ms = Object.keys(g).sort();
      traces = [{ type: "bar", x: ms, y: ms.map((k) => SH.mean(g[k])), error_y: { type: "data", array: ms.map((k) => (isFinite(SH.sd(g[k])) ? SH.sd(g[k]) : 0)), visible: true, color: "#94a3b8" }, marker: { color: blue }, text: ms.map((k) => `n=${g[k].length}`), hovertemplate: "%{x} 평균 %{y:.2f} (%{text})<extra></extra>" }];
      layout.showlegend = false; layout.xaxis = { type: "category", tickangle: -45 };
      const mn = Math.min(...ms.map((k) => SH.mean(g[k]))), mx = Math.max(...ms.map((k) => SH.mean(g[k])));
      const pad = (mx - mn) * 0.6 || 1; layout.yaxis = { title: it.unit || "", range: [mn - pad, mx + pad] };
      hline(lim.lsl, red, "하한 " + lim.lsl); hline(lim.usl, red, "상한 " + lim.usl);
      ex.appendChild(el("div", { class: "hint" }, ["막대 = 월 평균, 선 = ±1 표준편차(월 내 변동). 세로축은 평균 근처로 확대해 표시합니다."]));
    } else if (SUI.view === "ship") {
      const rows = SH.byShip(recs, it.key);
      const base = pts.filter((p) => isSingle(p.r)).map((p) => p.v); const bm = SH.mean(base), bs = SH.sd(base);
      const shown = rows.filter((r) => r.n >= 3);
      if (!shown.length) { Plotly.purge(div); div.innerHTML = ""; ex.appendChild(el("div", { class: "note warn" }, ["1모선 단독 시험이 3건 이상인 선박이 없습니다. ‘모선 수’ 필터를 ‘전체’로 하거나 기간을 늘려 보세요."])); return; }
      traces = [{ type: "bar", x: shown.map((r) => r.ship), y: shown.map((r) => r.mean), error_y: { type: "data", array: shown.map((r) => (isFinite(r.sd) ? r.sd : 0)), visible: true, color: "#94a3b8" }, marker: { color: shown.map((r) => (Math.abs(r.mean - bm) >= 2 * bs / Math.sqrt(r.n) ? amber : blue)) }, text: shown.map((r) => `n=${r.n}`), hovertemplate: "%{x} 평균 %{y:.2f} (%{text})<extra></extra>" }];
      layout.showlegend = false; layout.xaxis = { type: "category" };
      const mn = Math.min(...shown.map((r) => r.mean)), mx = Math.max(...shown.map((r) => r.mean)), pad = (mx - mn) * 0.8 || 1; layout.yaxis = { title: it.unit || "", range: [mn - pad, mx + pad] };
      hline(bm, gray, "단독 시험 전체 평균 " + fmt(bm, it.dec + 1), "solid"); hline(lim.lsl, red, "하한 " + lim.lsl); hline(lim.usl, red, "상한 " + lim.usl);
      const t = el("table"); t.appendChild(el("tr", {}, ["선박", "단독 시험 건수", "평균", "표준편차", "최소 ~ 최대", "전체 평균 대비", "판단"].map((h, i) => el("th", { class: i === 0 || i === 6 ? "txt" : "" }, [h]))));
      rows.forEach((r) => {
        const d = r.mean - bm, z = isFinite(bs) && bs > 0 ? d / (bs / Math.sqrt(r.n)) : 0;
        t.appendChild(el("tr", {}, [el("td", { class: "txt" }, [r.ship]), el("td", {}, [String(r.n)]), el("td", {}, [shipFmt(it, r.mean)]), el("td", {}, [isFinite(r.sd) ? fmt(r.sd, it.dec + 1) : "—"]), el("td", {}, [shipFmt(it, r.min) + " ~ " + shipFmt(it, r.max)]),
          el("td", {}, [(d >= 0 ? "+" : "") + fmt(d, it.dec + 1)]), el("td", { class: "txt small" }, [r.n < 3 ? "건수 부족" : Math.abs(z) >= 2 ? "🔶 차이 있어 보임(추정)" : "차이 없음"])]));
      });
      ex.appendChild(el("div", { class: "hint", html: "<b>1모선만 출항한 날</b>의 값을 그 선박의 시험값으로 봅니다(2모선 이상인 날은 평균값이라 선박별로 나눌 수 없어 제외). 판단 🔶는 평균 차이가 표준오차의 2배 이상일 때(추정). <b>선박 차이는 같은 시기의 배합·원료 변화와 섞여 있을 수 있어</b>, 원인으로 단정하지 말고 기간·첨가재 필터를 바꿔 재확인하세요." }));
      ex.appendChild(el("div", { class: "tablewrap" }, [t]));
    } else {
      const g = {}; pts.forEach((p) => { const r = p.r; const k = `${r.additive || "미표기"} · 석회석 ${r.v.ls ?? "-"}% · 첨가재 ${r.v.addr ?? "-"}%`; (g[k] = g[k] || { vals: [], d0: p.t, d1: p.t }).vals.push(p.v); g[k].d1 = p.t; if (p.t < g[k].d0) g[k].d0 = p.t; });
      const ks = Object.keys(g).sort((a, b) => (g[a].d0 < g[b].d0 ? -1 : 1));
      traces = [{ type: "bar", x: ks, y: ks.map((k) => SH.mean(g[k].vals)), error_y: { type: "data", array: ks.map((k) => (isFinite(SH.sd(g[k].vals)) ? SH.sd(g[k].vals) : 0)), visible: true, color: "#94a3b8" }, marker: { color: blue }, text: ks.map((k) => `n=${g[k].vals.length}`), hovertemplate: "%{x}<br>평균 %{y:.2f} (%{text})<extra></extra>" }];
      layout.showlegend = false; layout.xaxis = { type: "category", tickangle: -30, automargin: true }; layout.margin.b = 120;
      const mm = ks.map((k) => SH.mean(g[k].vals)); const mn = Math.min(...mm), mx = Math.max(...mm), pad = (mx - mn) * 0.8 || 1; layout.yaxis = { title: it.unit || "", range: [mn - pad, mx + pad] };
      hline(lim.lsl, red, "하한 " + lim.lsl); hline(lim.usl, red, "상한 " + lim.usl);
      const t = el("table"); t.appendChild(el("tr", {}, ["배합(첨가재·석회석·첨가재 비율)", "사용 기간", "건수", "평균", "표준편차"].map((h, i) => el("th", { class: i === 0 || i === 1 ? "txt" : "" }, [h]))));
      ks.forEach((k) => t.appendChild(el("tr", {}, [el("td", { class: "txt" }, [k]), el("td", { class: "txt small" }, [g[k].d0 + " ~ " + g[k].d1]), el("td", {}, [String(g[k].vals.length)]), el("td", {}, [shipFmt(it, SH.mean(g[k].vals))]), el("td", {}, [isFinite(SH.sd(g[k].vals)) ? fmt(SH.sd(g[k].vals), it.dec + 1) : "—"])])));
      ex.appendChild(el("div", { class: "hint" }, ["첨가재 종류·석회석 비율·첨가재 비율 조합별 평균입니다. 배합이 바뀐 시점의 품질 변화를 확인할 때 사용합니다."]));
      ex.appendChild(el("div", { class: "tablewrap" }, [t]));
    }
    Plotly.react(div, traces, layout, { displayModeBar: false, responsive: true, scrollZoom: false });
  }

  // ── 출하시멘트 파일 불러오기 ──
  function shipSig(headers) { return hashStr("ship|" + headers.map((h) => SH.norm(h)).join("|")).replace("qmsmap_", "qmsshipov_"); }
  function shipIngest(sheet, fileName, overrides) {
    const det = SH.detect(sheet.aoa);
    const headers = (sheet.aoa[det.headerRow] || []).map((c) => (c == null ? "" : String(c).trim()));
    const sig = shipSig(headers);
    const ov = overrides || lsGet(sig) || {};
    let res = SH.parse(sheet.aoa, { overrides: ov, headerRow: det.headerRow });
    if (!res || res.error) { STATE.loadError = (res && res.error) || "출하시멘트 표를 읽지 못했습니다."; renderLoadResult(); return; }
    STATE.shipPending = { sheet, fileName, sig, overrides: ov, res };
    const old = STATE.ship ? STATE.ship.records : [];
    const oldKeys = new Set(old.map((r) => r.lot || r.date));
    const added = res.records.filter((r) => !oldKeys.has(r.lot || r.date)).length;
    const records = SH.merge(old, res.records);
    const itemMap = new Map(); (STATE.ship ? STATE.ship.items : []).forEach((i) => itemMap.set(i.key, i)); res.items.forEach((i) => itemMap.set(i.key, i));
    STATE.ship = { records, items: [...itemMap.values()], info: { file: fileName, report: res.report, added, replaced: res.records.length - added, sig } };
    STATE.loadedInfo = { kind: "ship", file: fileName }; STATE.loadError = null;
    if (!STATE.ship.items.find((i) => i.key === SUI.key)) SUI.key = (STATE.ship.items.find((i) => i.key === "s28") || STATE.ship.items[0]).key;
    if (lsGet("qmsship_persist")) persistShip();
    refreshBadge(); renderLoadResult(); refreshCurrentData(); $("#map-panel").style.display = "none";
    if (active === "data") show("ship");
  }
  function persistShip() { if (STATE.ship) lsSet(SDATA_KEY, { records: STATE.ship.records, items: STATE.ship.items, info: STATE.ship.info }); }
  function renderShipLoadCard(res) {
    const S = STATE.ship; if (!S) return;
    const card = el("div", { class: "card", style: "border:2px solid var(--green)" });
    card.appendChild(el("h3", {}, [`✅ ${S.info.file} — 출하시멘트 형식으로 인식`]));
    card.appendChild(el("div", { class: "small", style: "margin:6px 0;line-height:1.7", html: shipInfoHtml(S.info) }));
    const R = S.info.report;
    if (R.missing.length && STATE.shipPending) {
      const box = el("div", { class: "note warn" }); box.appendChild(el("div", {}, ["아래 항목은 열 이름으로 찾지 못했습니다. 파일의 어느 열인지 고르면 추가로 읽고, 다음부터 기억합니다(없으면 그대로 두세요)."]));
      const picks = {};
      R.missing.forEach((k) => {
        const s = el("select", { style: "min-width:12rem" }); s.appendChild(el("option", { value: "-1" }, ["— 없음 —"]));
        R.headers.forEach((h, j) => { if (h && !Object.values(R.idx).includes(j)) s.appendChild(el("option", { value: j }, [h])); });
        picks[k] = s; box.appendChild(el("label", { class: "field", style: "display:inline-block;margin:6px 12px 0 0" }, [el("span", {}, [SH.BY[k].name]), s]));
      });
      box.appendChild(el("div", { class: "btnrow" }, [el("button", { class: "btn", onclick: () => { const ov = Object.assign({}, STATE.shipPending.overrides); for (const k in picks) if (+picks[k].value >= 0) ov[k] = +picks[k].value; lsSet(STATE.shipPending.sig, ov); shipIngest(STATE.shipPending.sheet, STATE.shipPending.fileName, ov); } }, ["선택한 열로 다시 읽기"])]));
      card.appendChild(box);
    }
    const cb = el("input", { type: "checkbox", ...(lsGet("qmsship_persist") ? { checked: "checked" } : {}) });
    cb.addEventListener("change", () => { if (cb.checked) { lsSet("qmsship_persist", true); persistShip(); } else { lsDel("qmsship_persist"); lsDel(SDATA_KEY); } });
    card.appendChild(el("label", { class: "chk small", style: "margin:4px 0" }, [cb, " 다음에 열 때 자동으로 보이게 이 PC 브라우저에 저장(공용 PC에서는 끄세요)"]));
    card.appendChild(el("div", { class: "btnrow" }, [el("button", { class: "btn", onclick: () => show("ship") }, ["🚢 출하시멘트 모니터링 보기"]), el("button", { class: "btn ghost", onclick: () => { if (!confirm("불러온 출하시멘트 자료를 모두 지울까요?")) return; STATE.ship = null; lsDel(SDATA_KEY); STATE.loadedInfo = null; refreshBadge(); renderLoadResult(); } }, ["출하시멘트 자료 지우기"])]));
    return card;
  }
  // 저장된 자료 복원
  (function restoreShip() { const d = lsGet(SDATA_KEY); if (d && d.records && d.records.length) { STATE.ship = d; } })();

  // ── 엑셀 내보내기 ──
  function sheetFromAoa(aoa) { return XLSX.utils.aoa_to_sheet(aoa); }
  function exportDataExcel() {
    const wb = XLSX.utils.book_new();
    for (const t in STATE.data) {
      const T = STATE.data[t]; const sp = SPEC.tables[t];
      const header = ["일시"].concat(T.byProduct ? ["품종"] : []).concat(T.columns.map((c) => (ITEM[c] ? ITEM[c].name : c)));
      const aoa = [header].concat(T.rows);
      XLSX.utils.book_append_sheet(wb, sheetFromAoa(aoa), (sp ? sp.sheet : t).slice(0, 31));
    }
    XLSX.writeFile(wb, "Blue365_QMS_데이터.xlsx");
  }
  function downloadTemplate() {
    const wb = XLSX.utils.book_new();
    for (const t in SPEC.tables) {
      const T = SPEC.tables[t];
      const keys = ["timestamp"].concat(T.byProduct ? ["product"] : []).concat(T.columns);
      const labels = ["일시"].concat(T.byProduct ? ["품종"] : []).concat(T.columns.map((c) => (ITEM[c] ? ITEM[c].name : c)));
      XLSX.utils.book_append_sheet(wb, sheetFromAoa([keys, labels]), T.sheet.slice(0, 31));
    }
    XLSX.writeFile(wb, "Blue365_QMS_입력템플릿.xlsx");
  }
  function exportMixExcel() {
    const r = STATE.lastMix; if (!r) return;
    const wb = XLSX.utils.book_new();
    const mat = [["사용", "원료", "구분", ...MATOX, "강열감량", "수분", "총Cr", "배합비%"]];
    MATS.forEach((m) => mat.push([m.use ? "Y" : "", m.name, m.category, ...MATOX.map((o) => +m[o] || 0), +m.LOI || 0, +m.H2O || 0, +m.Cr || 0, +m.ratio || 0]));
    XLSX.utils.book_append_sheet(wb, sheetFromAoa(mat), "원료성분");
    const comp = [["성분", "생료(건조)%", "클링커예측%"]];
    MATOX.forEach((o) => comp.push([MATOXL[o], round(r.raw[o], 3), round(r.clinker[o], 3)]));
    comp.push(["강열감량", round(r.raw.LOI, 3), ""]);
    XLSX.utils.book_append_sheet(wb, sheetFromAoa(comp), "생료·클링커");
    const mod = [["항목", "값"], ["생료 LSF", round(r.rawLsf, 1)], ["클링커 LSF", round(r.LSF, 1)], ["클링커 SM", round(r.SM, 2)], ["클링커 IM", round(r.IM, 2)], ["C3S(Bogue)", round(r.C3S, 1)], ["C2S", round(r.C2S, 1)], ["C3A", round(r.C3A, 1)], ["C4AF", round(r.C4AF, 1)], ["액상량1450", round(r.liquid, 1)], ["Na2Oeq", round(r.na2oeq, 2)], ["f-CaO(입력)", round(r.fcao, 2)], ["생료/클링커(t/t)", round(r.kilnFactor, 3)]];
    XLSX.utils.book_append_sheet(wb, sheetFromAoa(mod), "클링커예측");
    XLSX.writeFile(wb, "배합설계서.xlsx");
  }
  function round(v, d) { return isNum(v) ? Math.round(v * 10 ** d) / 10 ** d : null; }
  function numField(label, value, onChange, step) {
    const inp = el("input", { type: "number", value: value, step: step || "any" });
    inp.addEventListener("input", () => onChange(inp.value === "" ? 0 : +inp.value));
    return el("label", { class: "field" }, [el("span", {}, [label]), inp]);
  }

  // ── 부팅 ──
  function boot() {
    document.querySelector("style").textContent = document.querySelector("style").textContent; // noop
    const nav = $("#tabs");
    TABS.forEach((t) => nav.appendChild(el("button", { "data-id": t.id, onclick: () => show(t.id) }, [t.label])));
    $("#buildinfo").textContent = `샘플 ${RAW.sampleEnd || ""} · 생성 ${RAW.generated || ""}`;
    $("#subtitle").textContent = "오프라인 단일 파일 · 설치 불필요 · 데이터는 이 PC 안에서만 처리";
    setData(deepCopy(RAW.sample), "sample");
    refreshBadge();
    show("overview");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
