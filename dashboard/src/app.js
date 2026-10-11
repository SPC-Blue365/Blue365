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
    $("#databadge").textContent = `${src}${p[0] ? ` · ${p[0].slice(0, 10)} ~ ${p[1].slice(0, 10)}` : ""}`;
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
  function renderData(root) {
    root.appendChild(el("h2", {}, ["데이터 불러오기"]));
    root.appendChild(el("div", { class: "note" }, [el("span", { html: "LIMS·실험실에서 <b>내보낸 엑셀·CSV</b>를 올리거나, 엑셀에서 복사해 <b>붙여넣기</b>하면 반영됩니다. 열 이름이 달라도 아래 <b>열 수동 지정</b>으로 맞출 수 있습니다. 모든 처리는 이 PC 브라우저 안에서만 일어나고 외부로 전송되지 않습니다." })]));
    const fz = el("div", { class: "filezone", id: "filezone", html: "📂 <b>엑셀·CSV 파일 선택</b> 또는 여기로 끌어다 놓기<div class='small'>여러 시트(생료·클링커·물성…)도, 한 장짜리 표도 가능</div>" });
    const fin = el("input", { type: "file", accept: ".xlsx,.xls,.csv", style: "display:none" });
    fin.addEventListener("change", (e) => { if (e.target.files[0]) loadFile(e.target.files[0]); e.target.value = ""; });
    fz.addEventListener("click", () => fin.click());
    fz.addEventListener("dragover", (e) => { e.preventDefault(); fz.classList.add("drag"); });
    fz.addEventListener("dragleave", () => fz.classList.remove("drag"));
    fz.addEventListener("drop", (e) => { e.preventDefault(); fz.classList.remove("drag"); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); });
    root.appendChild(fz); root.appendChild(fin);
    // 붙여넣기(파일 선택이 막힌 PC 대비)
    const pcard = el("div", { class: "card", style: "margin-top:12px" });
    pcard.appendChild(el("div", { class: "small", html: "또는 <b>엑셀에서 표를 복사(Ctrl+C) → 아래에 붙여넣기(Ctrl+V)</b> — 첫 줄은 열 이름" }));
    const ta = el("textarea", { id: "paste-box", rows: "4", style: "width:100%;margin-top:6px;border:1px solid var(--line);border-radius:8px;padding:8px;font-family:inherit", placeholder: "일시\t클링커 자유석회\t클링커 LSF\n2026-11-01 08:00\t0.9\t95.1\n2026-11-01 16:00\t1.1\t94.6" });
    pcard.appendChild(ta);
    pcard.appendChild(el("div", { class: "btnrow" }, [el("button", { class: "btn sec", onclick: () => loadPaste(ta.value) }, ["붙여넣은 표 불러오기"])]));
    root.appendChild(pcard);
    root.appendChild(el("div", { id: "load-result" }));
    root.appendChild(el("div", { id: "map-panel", style: "display:none;margin-top:4px" }));
    renderLoadResult();
    root.appendChild(el("div", { class: "btnrow" }, [
      el("button", { class: "btn sec", onclick: () => { setData(deepCopy(RAW.sample), "sample"); STATE.loadedInfo = null; STATE.loadError = null; STATE.pending = null; refreshBadge(); renderLoadResult(); refreshCurrentData(); $("#map-panel").style.display = "none"; } }, ["샘플 데이터로 보기"]),
      el("button", { class: "btn ghost", onclick: downloadTemplate }, ["⬇️ 입력 템플릿(엑셀)"]),
      el("button", { class: "btn ghost", onclick: exportDataExcel }, ["⬇️ 현재 데이터 내보내기(엑셀)"]),
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
  function renderLoadResult() {
    const res = $("#load-result"); if (!res) return; res.innerHTML = "";
    if (STATE.loadError) { res.appendChild(el("div", { class: "note warn" }, [STATE.loadError])); return; }
    const info = STATE.loadedInfo; if (!info) return;
    res.appendChild(el("div", { class: "note", html: `<b>${esc(info.file)}</b> 불러오기 완료:<br>• ${info.report.map(esc).join("<br>• ")}` + (info.ignored && info.ignored.length ? `<br><span class="small">인식하지 못한 열: ${info.ignored.slice(0, 15).map(esc).join(", ")} — 필요하면 ‘열 수동 지정’으로 추가하세요.</span>` : "") }));
    const btns = [el("button", { class: "btn", onclick: () => show("overview") }, ["종합 현황 보기"]), el("button", { class: "btn sec", onclick: () => show("monitor") }, ["공정 모니터링 보기"])];
    if (STATE.pending && STATE.pending.length) btns.push(el("button", { class: "btn ghost", onclick: () => openMapping("") }, ["열 수동 지정"]));
    res.appendChild(el("div", { class: "btnrow" }, btns));
  }

  // ── 열 이름 매핑 ──
  function nkey(s) { return String(s == null ? "" : s).trim().toLowerCase().replace(/\s+/g, "").replace(/[()₂₃₄·%\-_/,]/g, ""); }
  const LABEL2KEY = {}; SPEC.items.forEach((it) => { LABEL2KEY[nkey(it.key)] = it.key; LABEL2KEY[nkey(it.name)] = it.key; });
  const ALIASES = {
    clk_fcao: ["fcao", "자유석회", "유리석회", "freelime", "clinkerfcao"], clk_lsf: ["lsf", "석회포화도", "clinkerlsf"], clk_sm: ["sm", "규산율"], clk_im: ["im", "철률", "알루미나율", "am"],
    clk_c3s: ["c3s", "알라이트", "alite", "에이라이트"], clk_c2s: ["c2s", "벨라이트", "belite"], clk_c3a: ["c3a"], clk_c4af: ["c4af"], clk_mgo: ["clinkermgo"],
    rm_lsf: ["생료lsf"], rm_sm: ["생료sm"], rm_im: ["생료im"], rm_r90: ["r90", "90um", "90μm", "분말잔사", "생료잔사"],
    phy_s1: ["cs1", "1일강도", "1일압축강도"], phy_s3: ["cs3", "3일강도", "3일압축강도"], phy_s7: ["cs7", "7일강도", "7일압축강도"], phy_s28: ["cs28", "28일강도", "28일압축강도", "압축강도28"],
    phy_ist: ["초결", "초결시간", "ist", "initialset"], phy_fst: ["종결", "종결시간", "fst", "finalset"], phy_autoclave: ["오토클레이브", "팽창도", "autoclave"],
    phy_crvi: ["6가크롬", "수용성6가크롬", "육가크롬", "cr6", "crvi", "수용성크롬", "cr6plus"], cem_blaine: ["분말도", "비표면적", "blaine", "ssa"], cem_so3: ["so3", "삼산화황"], cem_loi: ["강열감량", "loi", "ig손실"],
    kiln_bzt: ["소성대온도", "버닝존온도", "bzt", "버닝존"], kiln_o2: ["o2", "산소"], kiln_co: ["co", "일산화탄소"],
  };
  const ALIAS2KEY = {}; for (const k in ALIASES) ALIASES[k].forEach((a) => { ALIAS2KEY[nkey(a)] = k; });
  const TS_ALIASES = new Set(["timestamp", "일시", "시료일시", "채취일시", "시험일시", "sampledat", "date", "날짜", "일자", "시각", "생산일", "측정일"].map(nkey));
  const PROD_ALIASES = new Set(["product", "품종", "종류", "제품", "type"].map(nkey));
  const SHEET2TABLE = {}; for (const t in SPEC.tables) { SHEET2TABLE[nkey(SPEC.tables[t].sheet)] = t; SHEET2TABLE[nkey(t)] = t; SHEET2TABLE[nkey(SPEC.tables[t].label)] = t; }
  function guessKey(h) { const n = nkey(h); return n ? (LABEL2KEY[n] || ALIAS2KEY[n] || null) : null; }
  function roleOf(h) { const n = nkey(h); if (TS_ALIASES.has(n)) return "ts"; if (PROD_ALIASES.has(n)) return "product"; return guessKey(h) || ""; }

  function toISO(v) {
    if (v == null || v === "") return null;
    if (typeof v === "number") { const d = new Date(Math.round((v - 25569) * 86400 * 1000)); return isNaN(d) ? null : d.toISOString().slice(0, 16); }
    const d = new Date(String(v).trim().replace(/\./g, "-").replace(/\//g, "-").replace(/-+$/, ""));
    return isNaN(d) ? null : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  function detectHeader(aoa) {
    let best = -1, bestScore = 0, bestTs = -1;
    const lim = Math.min(aoa.length, 14);
    for (let r = 0; r < lim; r++) {
      const row = aoa[r] || []; let ts = -1, items = 0;
      row.forEach((c, i) => { const n = nkey(c); if (ts < 0 && TS_ALIASES.has(n)) ts = i; if (guessKey(c) || PROD_ALIASES.has(n)) items++; });
      const score = (ts >= 0 ? 4 : 0) + items;
      if (score > bestScore) { bestScore = score; best = r; bestTs = ts; }
    }
    return { row: best < 0 ? 0 : best, score: bestScore, tsIdx: bestTs };
  }
  function buildFromAssign(aoa, headerRow, assign) {
    const tsIdx = assign.indexOf("ts"); if (tsIdx < 0) return { tables: {}, report: [], unmatched: [] };
    const prodIdx = assign.indexOf("product");
    const groups = {};
    assign.forEach((a, i) => { if (a && a !== "ts" && a !== "product" && ITEM[a]) { const t = ITEM[a].table; (groups[t] = groups[t] || []).push({ i, k: a }); } });
    const tables = {}, report = [];
    for (const t in groups) {
      const byProduct = SPEC.tables[t].byProduct && prodIdx >= 0;
      const cols = groups[t].map((g) => g.k);
      const rows = [];
      for (let r = headerRow + 1; r < aoa.length; r++) {
        const row = aoa[r]; if (!row) continue; const ts = toISO(row[tsIdx]); if (!ts) continue;
        const out = [ts]; if (byProduct) out.push(String(row[prodIdx] == null ? "" : row[prodIdx]).trim() || "-");
        let any = false;
        groups[t].forEach(({ i, k }) => { const raw = row[i]; let v = null; if (raw != null && raw !== "") { const s = String(raw).replace(/,/g, ""); v = TEXTCOLS.has(k) ? String(raw) : (isFinite(+s) ? +s : null); } if (v != null) any = true; out.push(v); });
        if (any) rows.push(out);
      }
      if (rows.length) { tables[t] = { byProduct, columns: cols, rows }; report.push(`${SPEC.tables[t].label} — ${rows.length}행, 항목 ${cols.length}개`); }
    }
    const hdr = aoa[headerRow] || [];
    const unmatched = assign.map((a, i) => (a ? null : hdr[i])).filter((h) => h != null && String(h).trim());
    return { tables, report, unmatched };
  }
  function autoSheet(name, aoa) {
    const d = detectHeader(aoa); if (d.score < 2) return null;
    const header = (aoa[d.row] || []).map((h) => String(h == null ? "" : h));
    const assign = header.map(roleOf);
    if (assign.indexOf("ts") < 0 && d.tsIdx >= 0) assign[d.tsIdx] = "ts";
    if (assign.indexOf("ts") < 0) return null;
    const built = buildFromAssign(aoa, d.row, assign);
    return Object.keys(built.tables).length ? built : null;
  }
  function sheetsFromBuffer(buf) {
    const wb = XLSX.read(new Uint8Array(buf), { type: "array", cellDates: false });
    return wb.SheetNames.map((sn) => ({ name: sn, aoa: XLSX.utils.sheet_to_json(wb.Sheets[sn], { header: 1, raw: true, defval: null, blankrows: false }) }));
  }
  function loadFile(file) {
    STATE.pendingName = file.name;
    const reader = new FileReader();
    reader.onload = (e) => { try { ingest(sheetsFromBuffer(e.target.result)); } catch (err) { STATE.loadError = "파일을 읽지 못했습니다: " + err.message + " (손상되었거나 지원하지 않는 형식이면 ‘붙여넣기’를 사용해 보세요.)"; renderLoadResult(); } };
    reader.onerror = () => { STATE.loadError = "파일을 읽지 못했습니다 — 회사 PC가 브라우저의 파일 접근을 막았을 수 있습니다. 위의 ‘붙여넣기’(엑셀에서 복사 → 붙여넣기)를 사용해 보세요."; renderLoadResult(); };
    reader.readAsArrayBuffer(file);
  }
  function loadPaste(text) {
    if (!text || !text.trim()) { STATE.loadError = "붙여넣은 내용이 없습니다. 엑셀에서 표를 선택해 복사한 뒤 붙여넣으세요."; renderLoadResult(); return; }
    const sep = text.indexOf("\t") >= 0 ? "\t" : (text.indexOf(",") < 0 && text.indexOf(";") >= 0 ? ";" : ",");
    const aoa = text.replace(/\r/g, "").split("\n").filter((l) => l.length).map((l) => l.split(sep));
    STATE.pendingName = "붙여넣은 표";
    ingest([{ name: "붙여넣기", aoa }]);
  }
  function ingest(sheets) {
    STATE.pending = sheets.filter((s) => s.aoa && s.aoa.length >= 2);
    const loaded = {}, report = [];
    STATE.pending.forEach((s) => { const b = autoSheet(s.name, s.aoa); if (b) { Object.assign(loaded, b.tables); report.push(...b.report); } });
    if (Object.keys(loaded).length) {
      setData(loaded, "file"); STATE.loadError = null; STATE.loadedInfo = { file: STATE.pendingName, report, ignored: [] };
      refreshBadge(); renderLoadResult(); refreshCurrentData(); $("#map-panel").style.display = "none";
      window.scrollTo({ top: 0 });
    } else {
      STATE.loadedInfo = null; STATE.loadError = null; renderLoadResult();
      openMapping("자동 인식이 안 됐습니다. 각 열이 무엇인지 아래에서 직접 지정하세요(‘📅 일시’ 열은 꼭 포함).");
    }
  }
  function roleSelect(val) {
    const sel = el("select", { style: "min-width:12rem" });
    sel.appendChild(el("option", { value: "", ...(val === "" ? { selected: "selected" } : {}) }, ["— 무시 —"]));
    sel.appendChild(el("option", { value: "ts", ...(val === "ts" ? { selected: "selected" } : {}) }, ["📅 일시"]));
    sel.appendChild(el("option", { value: "product", ...(val === "product" ? { selected: "selected" } : {}) }, ["품종"]));
    [...new Set(SPEC.items.map((it) => it.stage))].forEach((stg) => {
      const og = el("optgroup", { label: stg });
      SPEC.items.filter((it) => it.stage === stg).forEach((it) => og.appendChild(el("option", { value: it.key, ...(val === it.key ? { selected: "selected" } : {}) }, [it.name + (it.unit ? ` (${it.unit})` : "")])));
      sel.appendChild(og);
    });
    return sel;
  }
  function openMapping(msg) {
    const sheets = STATE.pending || [];
    const panel = $("#map-panel"); if (!panel) return;
    if (!sheets.length) { panel.style.display = "none"; return; }
    panel.style.display = ""; panel.innerHTML = "";
    const card = el("div", { class: "card" });
    card.appendChild(el("h3", {}, ["열 수동 지정"]));
    if (msg) card.appendChild(el("div", { class: "note warn" }, [msg]));
    card.appendChild(el("p", { class: "hint" }, ["파일의 각 열이 무엇인지 골라 주세요. ‘📅 일시’ 1개는 꼭 필요하고, 품종은 시멘트·물성에만 씁니다. 한 장짜리 표에 여러 공정 항목이 섞여 있어도 공정별로 나눠 저장합니다."]));
    let si = 0;
    const body = el("div", { id: "map-body" });
    if (sheets.length > 1) {
      card.appendChild(el("label", { class: "field" }, [el("span", {}, ["시트"]), el("select", { style: "width:auto", onchange: (e) => { si = +e.target.value; drawMap(); } }, sheets.map((s, i) => el("option", { value: i }, [s.name])))]));
    }
    card.appendChild(body); panel.appendChild(card);
    function drawMap() {
      const aoa = sheets[si].aoa; body.innerHTML = "";
      const det = detectHeader(aoa); let headerRow = det.row;
      const hrOpts = aoa.slice(0, Math.min(aoa.length, 12)).map((r, i) => el("option", { value: i, ...(i === headerRow ? { selected: "selected" } : {}) }, [`${i + 1}행: ${(r || []).slice(0, 6).map((x) => String(x == null ? "" : x)).join(" | ").slice(0, 70)}`]));
      body.appendChild(el("label", { class: "field" }, [el("span", {}, ["머리글(열 이름) 행"]), el("select", { style: "width:100%", onchange: (e) => { headerRow = +e.target.value; renderCols(); } }, hrOpts)]));
      const colsWrap = el("div", { id: "map-cols" }); body.appendChild(colsWrap);
      renderCols();
      function renderCols() {
        colsWrap.innerHTML = "";
        const header = (aoa[headerRow] || []).map((h) => String(h == null ? "" : h));
        const assign = header.map(roleOf);
        if (assign.indexOf("ts") < 0) { const d2 = detectHeader(aoa); if (d2.tsIdx >= 0 && d2.row === headerRow) assign[d2.tsIdx] = "ts"; }
        const t = el("table"); t.appendChild(el("tr", {}, [el("th", { class: "txt" }, ["파일의 열"]), el("th", { class: "txt" }, ["지정"]), el("th", { class: "txt" }, ["미리보기"])]));
        const selects = [];
        header.forEach((h, i) => {
          const sel = roleSelect(assign[i]); selects.push(sel);
          const sample = []; for (let r = headerRow + 1; r < Math.min(aoa.length, headerRow + 4); r++) sample.push(String((aoa[r] || [])[i] == null ? "" : (aoa[r] || [])[i]));
          t.appendChild(el("tr", {}, [el("td", { class: "txt" }, [h || `(열 ${i + 1})`]), el("td", { class: "txt" }, [sel]), el("td", { class: "txt small" }, [sample.join(", ")])]));
        });
        colsWrap.appendChild(el("div", { class: "tablewrap" }, [t]));
        colsWrap.appendChild(el("div", { class: "btnrow" }, [
          el("button", { class: "btn", onclick: () => applyMapping(aoa, headerRow, selects.map((s) => s.value)) }, ["이 설정으로 불러오기"]),
          el("button", { class: "btn ghost", onclick: () => { STATE.pending = null; $("#map-panel").style.display = "none"; } }, ["닫기"]),
        ]));
      }
    }
    drawMap();
  }
  function applyMapping(aoa, headerRow, assign) {
    const b = buildFromAssign(aoa, headerRow, assign);
    if (!Object.keys(b.tables).length) { STATE.loadError = "‘📅 일시’ 열 1개와 항목 1개 이상을 지정해야 합니다."; renderLoadResult(); return; }
    setData(b.tables, "file"); STATE.loadError = null; STATE.loadedInfo = { file: STATE.pendingName || "수동 지정", report: b.report, ignored: b.unmatched };
    refreshBadge(); renderLoadResult(); refreshCurrentData(); $("#map-panel").style.display = "none";
    window.scrollTo({ top: 0 });
  }

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
