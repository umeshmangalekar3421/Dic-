/* CellForge lab frontend. All API calls are relative — never localhost. */
const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];

const state = {
  manifest: null,
  metrics: null,
  library: [],
  sta: [],
  industry: null,
};

function fmt(n, d=1) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
}

async function j(url, opt) {
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/* -------------------- charts (no CDN) -------------------- */
function lineChart(canvas, series, opts={}) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth * 2;
  const H = canvas.height = (opts.h || 220) * 2;
  ctx.scale(2, 2);
  const w = W/2, h = H/2;
  ctx.clearRect(0,0,w,h);
  const pad = {l: 46, r: 12, t: 12, b: 28};
  const xs = series.flatMap(s => s.x);
  const ys = series.flatMap(s => s.y).filter(v => v != null && isFinite(v));
  if (!ys.length) return;
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { y0 *= 0.9; y1 *= 1.1; }
  if (opts.log) { y0 = Math.max(y0, 1e-16); }
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const X = x => pad.l + (x - x0) / (x1 - x0 || 1) * (w - pad.l - pad.r);
  const Y = y => {
    if (opts.log) {
      const a = Math.log10(y0), b = Math.log10(y1);
      return pad.t + (1 - (Math.log10(Math.max(y, y0)) - a) / (b - a || 1)) * (h - pad.t - pad.b);
    }
    return pad.t + (1 - (y - y0) / (y1 - y0 || 1)) * (h - pad.t - pad.b);
  };
  ctx.strokeStyle = "#223044"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h-pad.b); ctx.lineTo(w-pad.r, h-pad.b); ctx.stroke();
  ctx.fillStyle = "#8aa0b8"; ctx.font = "11px Segoe UI, sans-serif";
  ctx.fillText(opts.ylab || "", 4, 12);
  ctx.fillText(fmt(y1, opts.yd || 1), 4, pad.t + 8);
  ctx.fillText(fmt(y0, opts.yd || 1), 4, h - pad.b);
  ctx.fillText(fmt(x0, opts.xd || 2), pad.l, h - 8);
  ctx.fillText(fmt(x1, opts.xd || 2), w - 40, h - 8);
  series.forEach(s => {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
    s.x.forEach((x,i) => {
      const y = s.y[i]; if (y == null) return;
      const px = X(x), py = Y(y);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    });
    ctx.stroke();
  });
  if (series.length > 1) {
    series.forEach((s, i) => {
      ctx.fillStyle = s.color;
      ctx.fillRect(pad.l + i*70, 6, 8, 8);
      ctx.fillStyle = "#8aa0b8";
      ctx.fillText(s.label, pad.l + i*70 + 12, 14);
    });
  }
}

function barChart(canvas, labels, groups) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth * 2;
  const H = canvas.height = 260 * 2;
  ctx.scale(2, 2);
  const w = W/2, h = H/2;
  ctx.clearRect(0,0,w,h);
  const pad = {l: 40, r: 10, t: 24, b: 40};
  const ys = groups.flatMap(g => g.y);
  const y1 = Math.max(...ys) * 1.12;
  const n = labels.length, g = groups.length;
  const bw = (w - pad.l - pad.r) / n;
  labels.forEach((lb, i) => {
    groups.forEach((gr, j) => {
      const barw = bw / (g + 0.6);
      const x = pad.l + i*bw + (j+0.3)*barw;
      const bh = (gr.y[i] / y1) * (h - pad.t - pad.b);
      ctx.fillStyle = gr.color;
      ctx.fillRect(x, h - pad.b - bh, barw * 0.9, bh);
    });
    ctx.save();
    ctx.fillStyle = "#8aa0b8"; ctx.font = "10px Segoe UI";
    ctx.translate(pad.l + i*bw + bw/2, h - 26);
    ctx.rotate(-0.35);
    ctx.fillText(lb, -12, 0);
    ctx.restore();
  });
  groups.forEach((gr, i) => {
    ctx.fillStyle = gr.color; ctx.fillRect(pad.l + i*80, 6, 8, 8);
    ctx.fillStyle = "#8aa0b8"; ctx.font = "11px Segoe UI";
    ctx.fillText(gr.label, pad.l + i*80 + 12, 14);
  });
}

/* -------------------- nav -------------------- */
$$(".nav button").forEach(b => b.addEventListener("click", () => show(b.dataset.view)));
$$("[data-go]").forEach(b => b.addEventListener("click", () => show(b.dataset.go)));
function show(name) {
  $$(".view").forEach(v => v.classList.toggle("on", v.id === "view-" + name));
  $$(".nav button").forEach(b => b.classList.toggle("on", b.dataset.view === name));
  if (name === "lab") refreshLab();
  if (name === "devices") loadDevices();
}

function kpi(title, value, sub) {
  return `<div class="kpi"><div class="k">${title}</div><div class="v">${value}</div><div class="s">${sub||""}</div></div>`;
}

/* -------------------- boot -------------------- */
async function boot() {
  try {
    state.manifest = await j("/api/manifest");
    state.metrics = await j("/api/metrics");
    state.library = (await j("/api/library")).rows || [];
    state.sta = (await j("/api/sta")).rows || [];
    state.industry = await j("/api/industry");
  } catch (e) {
    console.error(e);
  }
  const m = state.manifest || {};
  const fo4 = m.sanity?.fo4_ps;
  $("#fo4-pill").textContent = fo4 ? `FO4  ${fmt(fo4,1)} ps` : "FO4 —";
  $("#ver-pill").textContent = "v" + (m.version || "2.0");
  $("#cell").innerHTML = (m.cells || ["INV"]).map(c => `<option>${c}</option>`).join("");
  renderOverview();
  renderIndustry();
  renderLibrary();
  renderModels();
  renderSTA();
  bindLab();
}

function renderOverview() {
  const m = state.metrics || {};
  const phy = m.physics || {};
  const ml = m.ml?.targets?.delay_ps?.hgb?.test || {};
  const sta = m.sta || {};
  $("#kpis").innerHTML = [
    kpi("FO4 tt", fmt(phy.fo4_ps, 1) + " ps", "1.8 V · 25 °C · pinned"),
    kpi("Delay R²", fmt(ml.r2, 3), `MAE ${fmt(ml.mae,1)} ps  vs Ridge ${fmt(m.ml?.targets?.delay_ps?.ridge?.test?.r2,2)}`),
    kpi("Adder Fmax tt", fmt(sta.tt_fmax_mhz, 0) + " MHz", `ss ${fmt(sta.ss_fmax_mhz,0)} MHz`),
    kpi("Block yield", fmt(100*(sta.mc_yield||0), 1) + "%", `@ ${fmt(sta.target_mhz,0)} MHz slow corner`),
  ].join("");
  const fmap = (state.industry?.flow_map) || [];
  $("#flow-map").innerHTML = `<tr><th class="l">Step</th><th class="l">Industry</th><th class="l">CellForge</th></tr>` +
    fmap.map(r => `<tr><td class="l">${r.step}</td><td class="l">${r.industry}</td><td class="l">${r.here}</td></tr>`).join("");
  loadFo4Chart();
}

async function loadFo4Chart() {
  const corners = ["ss", "tt", "ff"];
  const colors = {ss:"#6aa4ff", tt:"#3ee0c5", ff:"#e8b84a"};
  const vdds = [];
  for (let v=1.44; v<=1.98+1e-9; v+=0.06) vdds.push(+v.toFixed(2));
  const series = await Promise.all(corners.map(async c => {
    const y = await Promise.all(vdds.map(async v => {
      const r = await j(`/api/fo4?vdd=${v}&temp_c=25&corner=${c}`);
      return r.fo4_ps;
    }));
    return {x: vdds, y, color: colors[c], label: c.toUpperCase()};
  }));
  lineChart($("#fo4-chart"), series, {h: 220, ylab: "ps", xd: 2, yd: 0});
}

function renderIndustry() {
  const ind = state.industry || {};
  $("#roles").innerHTML = (ind.roles||[]).map(r => `
    <div class="role">
      <h3>${r.title}</h3>
      <p><b>Where:</b> ${r.companies}</p>
      <p><b>Talk about:</b> ${r.you_can_talk_about}</p>
    </div>`).join("");
  $("#limits").innerHTML = (ind.honest_limits||[]).map(x => `<li>${x}</li>`).join("");
  $("#sky-table").innerHTML = `<tr><th class="l">Metric</th><th class="l">CellForge</th><th class="l">SKY130 / 130 nm</th><th class="l"></th></tr>` +
    (ind.sky130_correlation||[]).map(r =>
      `<tr><td class="l">${r.metric}</td><td class="l">${r.cellforge}</td><td class="l">${r.sky130}</td><td class="ok">${r.status}</td></tr>`
    ).join("");
}

function renderLibrary() {
  const rows = state.library || [];
  if (!rows.length) { $("#lib-table").innerHTML = "<tr><td>Run the pipeline to fill the library.</td></tr>"; return; }
  const hdr = ["cell","sizing","wn_um","wp_um","delay_tt_ps","delay_wc_ps","energy_tt_fj","area_um2","yield"];
  const names = {cell:"Cell", sizing:"Policy", wn_um:"Wn", wp_um:"Wp", delay_tt_ps:"tt ps", delay_wc_ps:"WC ps",
                 energy_tt_fj:"E fJ", area_um2:"µm²", yield:"Yield"};
  $("#lib-table").innerHTML = `<tr>${hdr.map(h=>`<th class="${h==='cell'||h==='sizing'?'l':''}">${names[h]}</th>`).join("")}</tr>` +
    rows.map(r => `<tr>${hdr.map(h => {
      let v = r[h];
      if (h==="yield") v = fmt(100*v,1)+"%";
      else if (typeof v === "number") v = fmt(v, h.includes("wn")||h.includes("wp")?2:1);
      return `<td class="${h==='cell'||h==='sizing'?'l':''}">${v}</td>`;
    }).join("")}</tr>`).join("");
  const cells = [...new Set(rows.map(r => r.cell))];
  const policies = ["min","balanced","ml_opt"];
  const colors = {min:"#6aa4ff", balanced:"#e8b84a", ml_opt:"#3ee0c5"};
  const groups = policies.map(p => ({
    label: p, color: colors[p],
    y: cells.map(c => {
      const hit = rows.find(r => r.cell===c && r.sizing===p);
      return hit ? hit.delay_wc_ps : 0;
    })
  }));
  barChart($("#lib-chart"), cells, groups);
}

function renderModels() {
  const t = state.metrics?.ml?.targets?.delay_ps;
  if (!t) return;
  $("#ml-kpis").innerHTML = [
    kpi("HistGB R²", fmt(t.hgb.test.r2, 3), `MAPE ${fmt(t.hgb.test.mape_pct,1)} %`),
    kpi("Random forest R²", fmt(t.rf.test.r2, 3), `MAE ${fmt(t.rf.test.mae,1)} ps`),
    kpi("Ridge R²", fmt(t.ridge.test.r2, 3), "linear baseline"),
    kpi("Train / test", `${state.metrics.ml.n_train} / ${state.metrics.ml.n_test}`, "stratified by cell"),
  ].join("");
  barChart($("#r2-chart"), ["Ridge","RF","HistGB"], [{
    label: "test R²", color: "#3ee0c5",
    y: [t.ridge.test.r2, t.rf.test.r2, t.hgb.test.r2],
  }]);
}

function renderSTA() {
  const s = state.metrics?.sta || {};
  $("#sta-kpis").innerHTML = [
    kpi("t_combo tt", fmt((s.tt_tcombo_ns||0)*1000, 0) + " ps", "8-bit carry chain"),
    kpi("Fmax tt", fmt(s.tt_fmax_mhz,0) + " MHz", "1.8 V 25 °C"),
    kpi("Fmax ss", fmt(s.ss_fmax_mhz,0) + " MHz", "1.62 V 125 °C"),
    kpi("Yield", fmt(100*(s.mc_yield||0),1) + "%", `P5 ${fmt(s.mc_fmax_p5,0)} MHz`),
  ].join("");
  const rows = state.sta || [];
  if (rows.length) {
    barChart($("#sta-chart"), rows.map(r => r.corner_label), [{
      label: "Fmax MHz", color: "#6aa4ff", y: rows.map(r => r.fmax_mhz)
    }]);
    $("#sta-table").innerHTML = `<table><tr><th class="l">Corner</th><th>t_combo ps</th><th>t_cq ps</th><th>t_su ps</th><th>WNS ns</th><th>Fmax</th></tr>` +
      rows.map(r => `<tr><td class="l">${r.corner_label}</td><td>${fmt(r.t_combo_ns*1000,0)}</td><td>${fmt(r.t_cq_ns*1000,0)}</td>
        <td>${fmt(r.t_setup_ns*1000,0)}</td><td>${fmt(r.wns_ns,3)}</td><td>${fmt(r.fmax_mhz,0)}</td></tr>`).join("") + `</table>`;
  }
}

/* -------------------- live lab -------------------- */
function labBody() {
  return {
    cell: $("#cell").value,
    wn_um: +$("#wn").value,
    wp_um: +$("#wp").value,
    vdd: +$("#vdd").value,
    temp_c: +$("#temp").value,
    cload_ff: +$("#cload").value,
    slew_ps: +$("#slew").value,
    corner: $("#corner").value,
  };
}
function paintLabels() {
  $("#wnv").textContent = fmt(+$("#wn").value, 2) + " µm";
  $("#wpv").textContent = fmt(+$("#wp").value, 2) + " µm  (ratio " + fmt(+$("#wp").value/+$("#wn").value, 2) + ")";
  $("#vddv").textContent = fmt(+$("#vdd").value, 2) + " V";
  $("#tempv").textContent = fmt(+$("#temp").value, 0) + " °C";
  $("#clv").textContent = fmt(+$("#cload").value, 1) + " fF";
  $("#slv").textContent = fmt(+$("#slew").value, 0) + " ps";
}
let labTimer = 0;
function scheduleLab() {
  paintLabels();
  clearTimeout(labTimer);
  labTimer = setTimeout(refreshLab, 80);
}
async function refreshLab() {
  paintLabels();
  const body = labBody();
  const r = await j("/api/characterize", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify(body),
  });
  $("#cell-desc").textContent = r.description || "";
  const pass = r.delay_ps < r.delay_spec_ps && r.p_leak_nw < r.leak_spec_nw;
  $("#live-metrics").innerHTML = [
    kpi("Delay", fmt(r.delay_ps,1)+" ps", `rise ${fmt(r.delay_rise_ps,1)} / fall ${fmt(r.delay_fall_ps,1)}`),
    kpi("Energy", fmt(r.e_dyn_fj,2)+" fJ", `Cin ${fmt(r.cin_ff,2)} fF`),
    kpi("Leakage", fmt(r.p_leak_nw,2)+" nW", `Vm ${fmt(r.vm_v,2)} V`),
    kpi("Area", fmt(r.area_um2,2)+" µm²", `LE ${fmt(r.logical_effort,2)} · ${fmt(r.fo4_ratio,2)} FO4`),
    kpi("Yield est.", fmt(100*r.yield_est,1)+"%", pass ? "meets delay+leak spec" : "fails spec at this PVT"),
    kpi("Seq.", r.is_sequential ? `tCQ ${fmt(r.t_cq_ps,1)} ps` : "combinational",
        r.is_sequential ? `tsu ${fmt(r.t_setup_ps,1)}  th ${fmt(r.t_hold_ps,1)}` : `slew out ${fmt(r.slew_out_ps,1)} ps`),
  ].join("");
  const sw = await j(`/api/sweep?cell=${body.cell}&axis=${$("#axis").value}&wn_um=${body.wn_um}&wp_um=${body.wp_um}&corner=${body.corner}`);
  lineChart($("#sweep-chart"), [
    {x: sw.x, y: sw.delay_ps, color: "#3ee0c5", label: "delay ps"}
  ], {h: 260, ylab: "ps", xd: 2, yd: 1});
}
function bindLab() {
  ["cell","corner","wn","wp","vdd","temp","cload","slew","axis"].forEach(id => {
    $("#"+id).addEventListener("input", scheduleLab);
    $("#"+id).addEventListener("change", scheduleLab);
  });
}

async function loadDevices() {
  const iv = await j("/api/iv?device=nmos");
  lineChart($("#iv-chart"), iv.curves.map((c,i) => ({
    x: c.vds, y: c.ids_mA, color: ["#3ee0c5","#6aa4ff","#e8b84a","#ff6b7a","#c084fc"][i],
    label: `Vgs ${c.vgs}`
  })), {h: 280, ylab: "mA", xd: 2, yd: 2});
  const sub = await j("/api/subthreshold?device=nmos");
  lineChart($("#sub-chart"), sub.series.map((s,i) => ({
    x: s.vgs, y: s.ids_A, color: ["#6aa4ff","#3ee0c5","#e8b84a","#ff6b7a"][i],
    label: `${s.temp_c}°C`
  })), {h: 280, ylab: "A", log: true, xd: 2, yd: 0});
}

boot().catch(console.error);
