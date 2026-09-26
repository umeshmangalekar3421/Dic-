"""
Live dashboard for FabAware-Opt.

A small Flask app that runs the real simulation engine in the browser:
press "Run optimization" and it performs the baseline evaluation, the
AI search and the variation stress test live, then renders the results.

    fabaware-web            # then open the preview URL
    fabaware-web --port 8000

Design notes
------------
* binds 0.0.0.0 so it is reachable through the sandbox preview proxy
* works with any Host header (no host allowlist)
* the browser only ever talks to this same origin via relative URLs
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import threading
import time

import matplotlib
matplotlib.use("Agg")

from flask import Flask, jsonify, render_template_string, request

from . import sta
from . import optimizer
from . import figure as figmod
from .design import build_fab32
from .library import LIBRARY, RESIZABLE_TYPES
from .pd import Trial

app = Flask(__name__)

# ---------------------------------------------------------------------------
# shared state
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_state = {
    "running": False,
    "log": [],
    "result": None,
    "design": None,
    "netlist": None,
    "baseline": None,
    "started": None,
    "elapsed": None,
    "error": None,
}

# the design is built once at startup - it is deterministic and cheap
_NETLIST = None
_DESIGN = None


def _ensure_design() -> None:
    global _NETLIST, _DESIGN
    if _NETLIST is None:
        _NETLIST = build_fab32()
        _DESIGN = _NETLIST.stats()
    _state["netlist"] = _NETLIST
    _state["design"] = _DESIGN


def _log(msg: str) -> None:
    with _lock:
        _state["log"].append(msg)
        if len(_state["log"]) > 400:
            _state["log"] = _state["log"][-400:]


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor="#0e1420")
    buf.seek(0)
    s = base64.b64encode(buf.read()).decode("ascii")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return s


# ---------------------------------------------------------------------------
# the actual work (runs in a background thread)
# ---------------------------------------------------------------------------
def _run(chips: int, seed: int, doe: int, iters: int) -> None:
    try:
        t0 = time.time()
        _state["error"] = None
        _state["result"] = None
        _state["log"] = []
        _state["started"] = t0
        nl = _state["netlist"]

        _log("[1/4] design: %d gates, %d flops, %d transistors" % (
                 _state["design"]["gates"], _state["design"]["dffs"],
                 _state["design"]["transistors"]))

        _log(f"[2/4] baseline evaluation ({chips} Monte-Carlo chips) ...")
        base_trial = optimizer.BASELINE_TRIAL
        base_r = sta.evaluate(nl, base_trial, K=chips, seed=seed)
        _state["baseline"] = base_r
        _log(f"    yield {100*base_r.yield_nom:.1f}%   "
             f"worst slack {base_r.worst_slack_nom:+.1f} ps   "
             f"area {base_r.cell_area:.0f} um2   DRC {base_r.drc}")

        _log("[3/4] AI optimization (GP + expected improvement) ...")
        opt = optimizer.optimize(
            nl, K=chips, seed=seed, n_doe=doe, n_iter=iters,
            time_budget=150.0, progress=_log)
        r = opt.result

        _log("[4/4] rendering figures ...")
        figs = {}
        figs["yield"] = _png(_mpl(figmod.fig_yield_dist, base_r, r))
        figs["vmin"] = _png(_mpl(figmod.fig_vmin, base_r, r))
        figs["metrics"] = _png(_mpl(figmod.fig_metrics_compare, base_r, r))
        figs["learning"] = _png(_mpl(figmod.fig_learning, opt.history))
        figs["paths"] = _png(_mpl(figmod.fig_path, base_r, r))
        figs["iv"] = _png(_mpl(figmod.fig_iv))
        figs["corners"] = _png(
            _mpl(figmod.fig_corners,
                 sta.evaluate_corners(nl, base_trial),
                 sta.evaluate_corners(nl, opt.trial)))
        pts = list(zip(opt.history.areas, opt.history.yields,
                       opt.history.powers))
        figs["pareto"] = _png(
            _mpl(figmod.fig_pareto, pts,
                 (base_r.cell_area, base_r.yield_nom),
                 (r.cell_area, r.yield_nom)))

        _state["result"] = {
            "baseline": _summ(base_trial, base_r),
            "optimized": _summ(opt.trial, r),
            "score": opt.score,
            "evals": opt.n_evals,
            "history": [
                {"tag": t, "score": s, "yield": y, "area": a, "power": p,
                 "drc": d}
                for t, s, y, a, p, d in zip(
                    opt.history.tags, opt.history.scores, opt.history.yields,
                    opt.history.areas, opt.history.powers, opt.history.drcs)
            ],
            "figs": figs,
            "corners": {
                "baseline": sta.evaluate_corners(nl, base_trial),
                "optimized": sta.evaluate_corners(nl, opt.trial),
            },
        }
        _state["elapsed"] = time.time() - t0
        _log(f"done in {_state['elapsed']:.1f} s")
    except Exception as exc:  # pragma: no cover
        import traceback
        _state["error"] = "".join(traceback.format_exception_only(
            type(exc), exc)).strip()
        _log("ERROR: " + _state["error"])
    finally:
        _state["running"] = False


def _mpl(fn, *a, **kw):
    """Call a figure function with a temp path and return the matplotlib fig."""
    import tempfile
    import matplotlib.pyplot as plt
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        fn(*a, path=path, **kw)
        img = matplotlib.image.imread(path)
        fig = plt.figure(figsize=(img.shape[1] / 100.0, img.shape[0] / 100.0),
                         dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")
        ax.imshow(img)
        return fig
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _summ(trial: Trial, r) -> dict:
    return {
        "drives": {k: v for k, v in trial.drives.items()},
        "ratio": round(trial.ratio, 3),
        "nbuf": trial.nbuf,
        "layers": [trial.layer_short, trial.layer_mid, trial.layer_long],
        "density": round(trial.density, 3),
        "yield": r.yield_nom,
        "slack_nom": r.worst_slack_nom,
        "slack_mean": r.mean_worst_slack,
        "slack_sigma": r.std_worst_slack,
        "area": r.cell_area,
        "die_area": r.die_area,
        "p_dyn": r.p_dyn,
        "p_leak": r.p_leak,
        "p_total": r.p_total,
        "drc": r.drc,
        "drc_detail": r.drc_detail,
        "vmin_mean": r.vmin_mean,
        "mean_delay": r.mean_path_delay,
    }


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.after_request
def _cors_and_no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    _ensure_design()
    return render_template_string(
        PAGE,
        chips=int(request.args.get("chips", 200)),
        design=_state["design"],
        spec=sta.T_SPEC,
        freq=sta.freq_ghz(),
        vdd=sta.VDD_NOM,
        cells=list(RESIZABLE_TYPES),
    )


@app.route("/api/state")
def api_state():
    with _lock:
        payload = {
            "running": _state["running"],
            "log": _state["log"][-80:],
            "elapsed": _state["elapsed"],
            "error": _state["error"],
            "result": _state["result"],
        }
    return jsonify(payload)


@app.route("/api/run", methods=["POST"])
def api_run():
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "error": "already running"}), 409
        _state["running"] = True
    body = request.get_json(silent=True) or {}
    chips = int(body.get("chips", 200))
    seed = int(body.get("seed", 42))
    doe = int(body.get("doe", 8))
    iters = int(body.get("iters", 20))
    chips = max(32, min(chips, 2000))
    _ensure_design()
    threading.Thread(target=_run, args=(chips, seed, doe, iters),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/design")
def api_design():
    _ensure_design()
    nl = _state["netlist"]
    return jsonify({
        "stats": _state["design"],
        "endpoints": len(nl.dff_d) + len(nl.primary_outputs),
        "spec_ps": sta.T_SPEC,
        "freq_GHz": sta.freq_ghz(),
        "vdd": sta.VDD_NOM,
        "library": {n: {"a": c.a, "b": c.b, "cin": c.cin, "area": c.area0,
                        "ileak": c.ilink, "ntr": c.ntr}
                    for n, c in LIBRARY.items()},
    })


# ---------------------------------------------------------------------------
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FabAware-Opt · live dashboard</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;background:#0a0f18;color:#d6dbe3;font-family:-apple-system,
       BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       line-height:1.55}
  .wrap{max-width:1200px;margin:0 auto;padding:0 22px 70px}
  header{padding:34px 0 22px;border-bottom:1px solid #1d2739;margin-bottom:24px}
  .eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:11px;
           color:#6d7c93;margin-bottom:8px}
  h1{margin:0 0 8px;font-size:28px;color:#fff;letter-spacing:-.02em}
  h1 span{color:#2b8aef}
  .sub{color:#8b97ab;font-size:14px;max-width:800px;margin:0}
  h2{font-size:18px;margin:34px 0 10px;color:#fff;font-weight:650}
  .ctl{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;
       background:#111a29;border:1px solid #1d2739;border-radius:10px;
       padding:16px;margin:22px 0}
  .fld{display:flex;flex-direction:column;gap:5px}
  .fld label{font-size:10px;text-transform:uppercase;letter-spacing:.09em;
             color:#6d7c93}
  .fld input{background:#0d1522;border:1px solid #243149;color:#d6dbe3;
             border-radius:6px;padding:8px 10px;width:104px;font-size:13px;
             font-family:ui-monospace,Menlo,monospace}
  button{background:#2b8aef;color:#fff;border:0;border-radius:7px;padding:10px 20px;
         font-size:14px;font-weight:600;cursor:pointer}
  button:hover{background:#3d97f5}
  button:disabled{background:#243149;color:#5c6a80;cursor:not-allowed}
  .hint{font-size:12px;color:#66748c;margin-left:auto;text-align:right}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
         gap:11px;margin:18px 0}
  .card{background:#111a29;border:1px solid #1d2739;border-radius:10px;padding:14px}
  .card.good{border-left:3px solid #2b8aef}.card.bad{border-left:3px solid #e05252}
  .clabel{font-size:10px;text-transform:uppercase;letter-spacing:.1em;
          color:#6d7c93;margin-bottom:7px}
  .cvals{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap}
  .cb{font-size:17px;color:#8b97ab;text-decoration:line-through;
      text-decoration-color:#4b5568}
  .carr{color:#4b5568;font-size:13px}
  .co{font-size:21px;font-weight:700;color:#fff}
  .cdelta{margin-top:5px;font-size:12px;font-weight:600}
  .card.good .cdelta{color:#4cc38a}.card.bad .cdelta{color:#e05252}
  .log{background:#0d1522;border:1px solid #1d2739;border-radius:8px;padding:12px;
       font-family:ui-monospace,Menlo,monospace;font-size:11.5px;
       color:#8b97ab;height:230px;overflow-y:auto;white-space:pre-wrap;
       margin:10px 0}
  table{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0}
  th{text-align:left;font-weight:600;color:#8b97ab;font-size:10.5px;
     text-transform:uppercase;letter-spacing:.07em;padding:8px 9px;
     border-bottom:1px solid #243149}
  td{padding:8px 9px;border-bottom:1px solid #172130}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;
                font-family:ui-monospace,Menlo,monospace}
  td.good{color:#4cc38a}td.bad{color:#e05252}
  figure{margin:16px 0}
  figure img{width:100%;border-radius:9px;border:1px solid #1d2739;display:block;
             background:#0e1420}
  figcaption{font-size:11.5px;color:#6d7c93;margin-top:7px}
  .two{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:860px){.two{grid-template-columns:1fr}}
  .pill{display:inline-block;background:#17233a;color:#9dc4f5;padding:2px 8px;
        border-radius:11px;font-size:11.5px;margin:2px 3px 2px 0;
        font-family:ui-monospace,Menlo,monospace}
  .status{font-size:12.5px;padding:9px 13px;border-radius:7px;margin:12px 0}
  .status.run{background:#17233a;color:#9dc4f5}
  .status.done{background:#123024;color:#4cc38a}
  .status.err{background:#33161a;color:#e05252}
  .hidden{display:none}
  .spin{display:inline-block;width:9px;height:9px;border:2px solid #9dc4f5;
        border-top-color:transparent;border-radius:50%;
        animation:sp .8s linear infinite;margin-right:7px;vertical-align:middle}
  @keyframes sp{to{transform:rotate(360deg)}}
  footer{margin-top:44px;padding-top:18px;border-top:1px solid #1d2739;
         font-size:11.5px;color:#5c6a80}
  code{background:#17233a;padding:1px 5px;border-radius:4px;font-size:11.5px;
       color:#9dc4f5}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">FabAware-Opt · live simulation dashboard</div>
  <h1>Process-Variation-Aware <span>Standard-Cell &amp; Physical-Design</span> Optimization</h1>
  <p class="sub">
    Runs the real engine in your browser: build the netlist, evaluate the
    baseline, inject manufacturing variation over thousands of simulated chips,
    let a Gaussian-process optimizer search the design space, and compare every
    headline metric.
  </p>
</header>

<div class="ctl">
  <div class="fld"><label>Monte-Carlo chips</label>
    <input id="chips" type="number" value="{{ chips }}" min="32" max="2000" step="32"></div>
  <div class="fld"><label>DOE size</label>
    <input id="doe" type="number" value="8" min="2" max="24"></div>
  <div class="fld"><label>GP iterations</label>
    <input id="iters" type="number" value="20" min="0" max="60"></div>
  <div class="fld"><label>Seed</label>
    <input id="seed" type="number" value="42" min="0"></div>
  <button id="go">Run optimization</button>
  <div class="hint">
    design: <b>{{ design.gates }}</b> gates · <b>{{ design.dffs }}</b> flops ·
    <b>{{ design.transistors }}</b> transistors<br>
    target {{ "%.0f"|format(spec) }} ps ({{ "%.2f"|format(freq) }} GHz) @
    {{ "%.2f"|format(vdd) }} V
  </div>
</div>

<div id="status" class="status hidden"></div>

<div id="results" class="hidden">
  <h2>Result</h2>
  <div class="cards" id="cards"></div>
  <table>
    <thead><tr><th>Metric</th><th class="num">Baseline</th>
      <th class="num">AI-optimized</th><th class="num">Change</th></tr></thead>
    <tbody id="metrics"></tbody>
  </table>

  <h2>Configuration chosen by the AI</h2>
  <div id="cfg"></div>

  <h2>Figures</h2>
  <figure><img id="f-yield"><figcaption><b>Fig 1.</b> Worst-case slack
    distribution across all Monte-Carlo chips. The dashed line is the timing
    spec — chips to the right of it pass.</figcaption></figure>
  <div class="two">
    <figure><img id="f-metrics"><figcaption><b>Fig 2.</b> All headline metrics;
      outward is always better.</figcaption></figure>
    <figure><img id="f-vmin"><figcaption><b>Fig 3.</b> Per-chip minimum operating
      voltage — lower means more voltage margin.</figcaption></figure>
  </div>
  <figure><img id="f-learning"><figcaption><b>Fig 4.</b> AI search convergence;
    the blue line is the running best score.</figcaption></figure>
  <figure><img id="f-paths"><figcaption><b>Fig 5.</b> Slack of the worst timing
    endpoints, before and after.</figcaption></figure>
  <div class="two">
    <figure><img id="f-pareto"><figcaption><b>Fig 6.</b> Design space explored —
      area vs yield, coloured by power.</figcaption></figure>
    <figure><img id="f-corners"><figcaption><b>Fig 7.</b> Deterministic PVT-corner
      analysis.</figcaption></figure>
  </div>

  <h2>Transistor model</h2>
  <figure><img id="f-iv"><figcaption><b>Fig 8.</b> nMOS I–V family from the
    compact model; bands show the ±40 mV threshold spread.</figcaption></figure>

  <h2>Evaluation log</h2>
  <div class="scroll" style="max-height:300px;overflow-y:auto;border:1px solid #1d2739;border-radius:8px">
  <table>
    <thead><tr><th class="num">#</th><th>Phase</th><th class="num">Score</th>
      <th class="num">Yield</th><th class="num">Area µm²</th>
      <th class="num">Power mW</th><th class="num">DRC</th></tr></thead>
    <tbody id="hist"></tbody>
  </table>
  </div>
</div>

<h2>Engine log</h2>
<div class="log" id="log">Press "Run optimization" to start.</div>

<footer>
  FabAware-Opt — a fabrication-aware, open-source EDA optimization framework
  evaluated through transistor simulation and RTL-to-gate netlist experiments.
  It does not fabricate a chip.
</footer>
</div>

<script>
const $ = id => document.getElementById(id);
let timer = null;

function fmt(v, d=2){ return (v===null||v===undefined||isNaN(v)) ? '—' : Number(v).toFixed(d); }

async function poll(){
  try{
    const r = await fetch('/api/state');
    const s = await r.json();
    $('log').textContent = s.log.join('\n') || 'waiting…';
    $('log').scrollTop = $('log').scrollHeight;

    if(s.running){
      $('status').className = 'status run';
      $('status').innerHTML = '<span class="spin"></span>simulating…';
      $('status').classList.remove('hidden');
    } else if(s.error){
      $('status').className = 'status err';
      $('status').textContent = 'Error: ' + s.error;
      clearInterval(timer); timer = null; $('go').disabled = false;
    } else if(s.result){
      $('status').className = 'status done';
      $('status').textContent = 'Complete in ' + s.elapsed.toFixed(1) + ' s — '
        + s.result.evals + ' statistical-timing evaluations';
      render(s.result);
      clearInterval(timer); timer = null; $('go').disabled = false;
    }
  }catch(e){ /* transient */ }
}

function card(label, b, o, d, better){
  return `<div class="card ${better?'good':'bad'}">
    <div class="clabel">${label}</div>
    <div class="cvals"><span class="cb">${b}</span><span class="carr">→</span>
      <span class="co">${o}</span></div>
    <div class="cdelta">${d}</div></div>`;
}

function render(R){
  const b = R.baseline, o = R.optimized;
  $('results').classList.remove('hidden');

  const dy = (o.yield-b.yield)*100;
  $('cards').innerHTML = [
    card('Timing yield', (b.yield*100).toFixed(1)+'%', (o.yield*100).toFixed(1)+'%',
         (dy>=0?'+':'')+dy.toFixed(1)+' pp', dy>0),
    card('Worst slack', (b.slack_nom>=0?'+':'')+b.slack_nom.toFixed(1)+' ps',
         (o.slack_nom>=0?'+':'')+o.slack_nom.toFixed(1)+' ps',
         ((o.slack_nom-b.slack_nom)>=0?'+':'')+(o.slack_nom-b.slack_nom).toFixed(1)+' ps',
         o.slack_nom>b.slack_nom),
    card('Cell area', b.area.toFixed(0), o.area.toFixed(0),
         ((o.area-b.area)/b.area*100>=0?'+':'')+((o.area-b.area)/b.area*100).toFixed(1)+'%',
         o.area<=b.area),
    card('Total power', b.p_total.toFixed(3), o.p_total.toFixed(3),
         ((o.p_total-b.p_total)/b.p_total*100>=0?'+':'')+((o.p_total-b.p_total)/b.p_total*100).toFixed(1)+'%',
         o.p_total<=b.p_total),
    card('DRC violations', ''+b.drc, ''+o.drc, (o.drc-b.drc>=0?'+':'')+(o.drc-b.drc),
         o.drc<=b.drc),
    card('Mean Vmin', (b.vmin_mean*1000).toFixed(0)+' mV',
         (o.vmin_mean*1000).toFixed(0)+' mV',
         ((o.vmin_mean-b.vmin_mean)*1000>=0?'+':'')+((o.vmin_mean-b.vmin_mean)*1000).toFixed(0)+' mV',
         o.vmin_mean<b.vmin_mean),
  ].join('');

  const rows = [
    ['Timing yield', (b.yield*100).toFixed(1)+' %', (o.yield*100).toFixed(1)+' %',
     ((o.yield-b.yield)*100).toFixed(1)+' pp', o.yield>=b.yield],
    ['Worst slack (nominal)', b.slack_nom.toFixed(1)+' ps', o.slack_nom.toFixed(1)+' ps',
     (o.slack_nom-b.slack_nom).toFixed(1)+' ps', o.slack_nom>=b.slack_nom],
    ['Worst slack (mean)', b.slack_mean.toFixed(1)+' ps', o.slack_mean.toFixed(1)+' ps',
     (o.slack_mean-b.slack_mean).toFixed(1)+' ps', o.slack_mean>=b.slack_mean],
    ['Worst slack (σ)', b.slack_sigma.toFixed(2)+' ps', o.slack_sigma.toFixed(2)+' ps',
     (o.slack_sigma-b.slack_sigma).toFixed(2)+' ps', o.slack_sigma<=b.slack_sigma],
    ['Standard-cell area', b.area.toFixed(1)+' µm²', o.area.toFixed(1)+' µm²',
     ((o.area-b.area)/b.area*100).toFixed(1)+' %', o.area<=b.area],
    ['Die area', b.die_area.toFixed(1)+' µm²', o.die_area.toFixed(1)+' µm²',
     ((o.die_area-b.die_area)/b.die_area*100).toFixed(1)+' %', o.die_area<=b.die_area],
    ['Dynamic power', b.p_dyn.toFixed(3)+' mW', o.p_dyn.toFixed(3)+' mW',
     ((o.p_dyn-b.p_dyn)/b.p_dyn*100).toFixed(1)+' %', o.p_dyn<=b.p_dyn],
    ['Leakage power', b.p_leak.toFixed(4)+' mW', o.p_leak.toFixed(4)+' mW',
     ((o.p_leak-b.p_leak)/b.p_leak*100).toFixed(1)+' %', o.p_leak<=b.p_leak],
    ['Total power', b.p_total.toFixed(3)+' mW', o.p_total.toFixed(3)+' mW',
     ((o.p_total-b.p_total)/b.p_total*100).toFixed(1)+' %', o.p_total<=b.p_total],
    ['DRC violations', ''+b.drc, ''+o.drc, ''+(o.drc-b.drc), o.drc<=b.drc],
    ['Mean Vmin', (b.vmin_mean*1000).toFixed(0)+' mV', (o.vmin_mean*1000).toFixed(0)+' mV',
     ((o.vmin_mean-b.vmin_mean)*1000).toFixed(0)+' mV', o.vmin_mean<=b.vmin_mean],
    ['Mean path delay', b.mean_delay.toFixed(1)+' ps', o.mean_delay.toFixed(1)+' ps',
     ((o.mean_delay-b.mean_delay)/b.mean_delay*100).toFixed(1)+' %', o.mean_delay<=b.mean_delay],
  ];
  $('metrics').innerHTML = rows.map(r=>
    `<tr><td>${r[0]}</td><td class="num">${r[1]}</td><td class="num">${r[2]}</td>
     <td class="num ${r[4]?'good':'bad'}">${r[3]}</td></tr>`).join('');

  const lay = o.layers.map(l=>'M'+l).join(' / ');
  $('cfg').innerHTML =
    `<div><b>Cell drive strengths</b><br>` +
    Object.entries(o.drives).map(([k,v])=>`<span class="pill">${k} ${v}×</span>`).join('') +
    `</div><div style="margin-top:10px"><b>Physical design</b><br>` +
    `<span class="pill">Wp/Wn ${o.ratio}</span>` +
    `<span class="pill">buffers ${o.nbuf}</span>` +
    `<span class="pill">metal ${lay}</span>` +
    `<span class="pill">density ${o.density}</span></div>`;

  for(const k of ['yield','metrics','vmin','learning','paths','pareto','corners','iv']){
    const el = $('f-'+k);
    if(R.figs && R.figs[k]) el.src = 'data:image/png;base64,' + R.figs[k];
  }

  $('hist').innerHTML = R.history.map((h,i)=>
    `<tr><td class="num">${i+1}</td><td>${h.tag}</td>
     <td class="num">${h.score.toFixed(3)}</td>
     <td class="num">${(h.yield*100).toFixed(1)}%</td>
     <td class="num">${h.area.toFixed(0)}</td>
     <td class="num">${h.power.toFixed(3)}</td>
     <td class="num">${h.drc}</td></tr>`).join('');
}

$('go').onclick = async () => {
  $('go').disabled = true;
  $('status').classList.remove('hidden');
  $('status').className = 'status run';
  $('status').innerHTML = '<span class="spin"></span>starting…';
  $('log').textContent = '';
  await fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({chips:+$('chips').value, seed:+$('seed').value,
                          doe:+$('doe').value, iters:+$('iters').value})});
  if(timer) clearInterval(timer);
  timer = setInterval(poll, 400);
  poll();
};

poll();
</script>
</body>
</html>
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fabaware-web",
                                 description="FabAware-Opt live dashboard")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)
    _ensure_design()
    print(f"FabAware-Opt dashboard → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug,
            threaded=True, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
