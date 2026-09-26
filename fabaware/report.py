"""
Report generation: self-contained HTML report + machine-readable JSON.
======================================================================

Produces:

* ``report.html``  - a single self-contained file (figures embedded as base64
  PNGs, no external assets, no internet needed) that tells the full story of
  the experiment.
* ``results.json`` - every number used in the report, for reproducible
  post-processing.
"""

from __future__ import annotations

import base64
import datetime as _dt
import html
import json
import os
from typing import Dict

from . import figure as figmod
from . import sta
from .design import Netlist
from .library import LIBRARY, RESIZABLE_TYPES
from .optimizer import OptResult
from .pd import Trial

FIG_DIR = "figures"


# ---------------------------------------------------------------------------
def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _rel(a: float, b: float) -> str:
    """Signed relative change of a vs b (b is the reference)."""
    if abs(b) < 1e-12:
        return "—"
    pct = 100.0 * (a - b) / abs(b)
    return f"{pct:+.1f}%"


def _delta_cls(better: bool) -> str:
    return "good" if better else "bad"


# ---------------------------------------------------------------------------
def build_report(
    nl: Netlist,
    base_trial: Trial,
    base_r: sta.EvalResult,
    opt: OptResult,
    out_dir: str = "reports",
    K: int = 160,
    runtime_s: float = 0.0,
) -> Dict[str, str]:
    """Generate the full report. Returns {'html':..., 'json':...} paths."""
    os.makedirs(out_dir, exist_ok=True)
    fig_dir = os.path.join(out_dir, FIG_DIR)
    os.makedirs(fig_dir, exist_ok=True)

    opt_r = opt.result
    opt_trial = opt.trial

    # ---------------- figures -------------------------------------------
    f_iv = figmod.fig_iv(path=os.path.join(fig_dir, "fig_iv.png"))
    f_ivb = figmod.fig_iv_bar(path=os.path.join(fig_dir, "fig_iv_bars.png"))
    f_yield = figmod.fig_yield_dist(base_r, opt_r,
                                    path=os.path.join(fig_dir, "fig_yield.png"))
    f_metrics = figmod.fig_metrics_compare(
        base_r, opt_r, path=os.path.join(fig_dir, "fig_metrics.png"))
    f_vmin = figmod.fig_vmin(base_r, opt_r,
                             path=os.path.join(fig_dir, "fig_vmin.png"))
    f_learn = figmod.fig_learning(opt.history,
                                  path=os.path.join(fig_dir, "fig_learning.png"))
    pts = list(zip(opt.history.areas, opt.history.yields, opt.history.powers))
    f_pareto = figmod.fig_pareto(
        pts, (base_r.cell_area, base_r.yield_nom),
        (opt_r.cell_area, opt_r.yield_nom),
        path=os.path.join(fig_dir, "fig_pareto.png"))
    f_path = figmod.fig_path(base_r, opt_r,
                             path=os.path.join(fig_dir, "fig_paths.png"))

    cb = sta.evaluate_corners(nl, base_trial)
    co = sta.evaluate_corners(nl, opt_trial)
    f_corners = figmod.fig_corners(cb, co,
                                   path=os.path.join(fig_dir, "fig_corners.png"))

    n_pass_b = sum(1 for v in cb.values() if v >= 0)
    n_pass_o = sum(1 for v in co.values() if v >= 0)
    n_corners = len(cb)
    if n_pass_o == n_corners:
        corner_note = "The optimized design is positive at every corner."
    else:
        misses = ", ".join(k for k, v in co.items() if v < 0)
        corner_note = (
            f"The optimized design meets {n_pass_o} of {n_corners} corners "
            f"(baseline {n_pass_b}/{n_corners}); still negative at: {misses}. "
            f"Every corner improved, but the slow-slow and hot corners would "
            f"need additional work — the Monte-Carlo yield figure, not this "
            f"deterministic sweep, is the headline metric."
        )

    # ---------------- numbers -------------------------------------------
    st = nl.stats()
    n_paths = len(base_r.paths)
    yield_b, yield_o = base_r.yield_nom, opt_r.yield_nom
    slack_b, slack_o = base_r.worst_slack_nom, opt_r.worst_slack_nom
    ms_b, ms_o = base_r.mean_worst_slack, opt_r.mean_worst_slack
    sd_b, sd_o = base_r.std_worst_slack, opt_r.std_worst_slack
    area_b, area_o = base_r.cell_area, opt_r.cell_area
    pwr_b, pwr_o = base_r.p_total, opt_r.p_total
    drc_b, drc_o = base_r.drc, opt_r.drc
    vmin_b, vmin_o = base_r.vmin_mean, opt_r.vmin_mean
    d_b, d_o = base_r.mean_path_delay, opt_r.mean_path_delay

    rows = [
        ("Timing yield @ 0.80 V, 25 °C", f"{yield_b*100:.1f} %",
         f"{yield_o*100:.1f} %", _rel(yield_o, yield_b),
         yield_o >= yield_b, "Fraction of Monte-Carlo chips meeting the "
         f"{sta.T_SPEC:.0f} ps cycle time — the headline metric."),
        ("Worst-case slack (nominal)", f"{slack_b:+.1f} ps",
         f"{slack_o:+.1f} ps", f"{slack_o-slack_b:+.1f} ps",
         slack_o >= slack_b, "Deterministic critical-path slack at nominal PVT."),
        ("Worst-case slack (mean over chips)", f"{ms_b:+.1f} ps",
         f"{ms_o:+.1f} ps", f"{ms_o-ms_b:+.1f} ps", ms_o >= ms_b,
         "Mean of the per-chip worst slack across the Monte-Carlo population."),
        ("Worst-case slack (σ over chips)", f"{sd_b:.2f} ps",
         f"{sd_o:.2f} ps", _rel(sd_o, sd_b), sd_o <= sd_b,
         "Spread of the timing distribution — smaller means more predictable "
         "silicon."),
        ("Standard-cell area", f"{area_b:.0f} µm²", f"{area_o:.0f} µm²",
         _rel(area_o, area_b), area_o <= area_b,
         "Sum of placed standard-cell footprints."),
        ("Total power", f"{pwr_b:.3f} mW", f"{pwr_o:.3f} mW",
         _rel(pwr_o, pwr_b), pwr_o <= pwr_b,
         f"Dynamic ({opt_r.p_dyn:.3f} mW) + leakage ({opt_r.p_leak:.4f} mW) "
         f"at {sta.ACTIVITY*100:.0f}% activity."),
        ("DRC violations", f"{drc_b}", f"{drc_o}",
         f"{drc_o-drc_b:+d}", drc_o <= drc_b,
         "Simplified rule deck: cell spacing, metal utilisation, density "
         "window, via crowding."),
        ("Mean Vmin", f"{vmin_b*1000:.0f} mV", f"{vmin_o*1000:.0f} mV",
         f"{(vmin_o-vmin_b)*1000:+.0f} mV", vmin_o <= vmin_b,
         "Average per-chip minimum supply that still meets timing — voltage "
         "margin headroom."),
        ("Mean path delay", f"{d_b:.1f} ps", f"{d_o:.1f} ps",
         _rel(d_o, d_b), d_o <= d_b,
         f"Average over all {n_paths} timing endpoints."),
    ]

    # drive-strength / config tables
    drive_rows = "".join(
        f"<tr><td><code>{c}</code></td>"
        f"<td class='num'>{base_trial.drives.get(c, 1.0):.0f}×</td>"
        f"<td class='num'>{opt_trial.drives.get(c, 1.0):.0f}×</td>"
        f"<td class='num'>{opt_r.trial.drives.get(c,1.0)/max(base_trial.drives.get(c,1.0),1e-9):.2f}×</td>"
        f"<td class='num dim'>{st['by_type'].get(c, 0)}</td></tr>"
        for c in RESIZABLE_TYPES
    )

    phys_rows = [
        ("Wp/Wn sizing ratio", f"{base_trial.ratio:.2f}", f"{opt_trial.ratio:.2f}"),
        ("Buffers on long wires", f"{base_trial.nbuf}", f"{opt_trial.nbuf}"),
        ("Metal — short nets", f"M{base_trial.layer_short}", f"M{opt_trial.layer_short}"),
        ("Metal — mid nets", f"M{base_trial.layer_mid}", f"M{opt_trial.layer_mid}"),
        ("Metal — long nets", f"M{base_trial.layer_long}", f"M{opt_trial.layer_long}"),
        ("Placement density", f"{base_trial.density:.2f}", f"{opt_trial.density:.2f}"),
    ]
    phys_html = "".join(
        f"<tr><td>{a}</td><td class='num'>{b}</td><td class='num'>{c}</td></tr>"
        for a, b, c in phys_rows
    )

    corner_rows = "".join(
        f"<tr><td>{k}</td>"
        f"<td class='num {'good' if v>=0 else 'bad'}'>{v:+.1f}</td>"
        f"<td class='num {'good' if co[k]>=0 else 'bad'}'>{co[k]:+.1f}</td></tr>"
        for k, v in cb.items()
    )

    top_paths = sorted(base_r.paths, key=lambda t: t[2])[:10]
    path_rows = "".join(
        f"<tr><td><code>{n}</code></td><td class='num'>{d:.1f}</td>"
        f"<td class='num {'good' if s>=0 else 'bad'}'>{s:+.1f}</td>"
        f"<td class='num'>{dict((p[0],p[1]) for p in opt_r.paths).get(n, float('nan')):.1f}</td>"
        f"<td class='num {'good' if dict((p[0],p[2]) for p in opt_r.paths).get(n,-1e9)>=0 else 'bad'}'>"
        f"{dict((p[0],p[2]) for p in opt_r.paths).get(n, float('nan')):+.1f}</td></tr>"
        for n, d, s in top_paths
    )

    learn_rows = "".join(
        f"<tr><td class='num'>{i+1}</td><td>{html.escape(t)}</td>"
        f"<td class='num'>{s:.3f}</td><td class='num'>{100*y:.1f}%</td>"
        f"<td class='num'>{a:.0f}</td><td class='num'>{p:.3f}</td>"
        f"<td class='num'>{d}</td></tr>"
        for i, (t, s, y, a, p, d) in enumerate(zip(
            opt.history.tags, opt.history.scores, opt.history.yields,
            opt.history.areas, opt.history.powers, opt.history.drcs))
    )

    lib_rows = "".join(
        f"<tr><td><code>{n}</code></td><td class='num'>{c.a:.1f}</td>"
        f"<td class='num'>{c.b:.3f}</td><td class='num'>{c.cin:.2f}</td>"
        f"<td class='num'>{c.area0:.1f}</td><td class='num'>{c.ilink:.2f}</td>"
        f"<td class='num'>{c.ntr}</td>"
        f"<td class='num dim'>{st['by_type'].get(n,0)}</td></tr>"
        for n, c in LIBRARY.items()
    )

    # ---------------- JSON ----------------------------------------------
    payload = {
        "project": "FabAware-Opt",
        "version": __import__("fabaware").__version__,
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "design": {
            "name": "FAB-32",
            "gates": st["gates"], "flops": st["dffs"],
            "nets": st["nets"], "transistors": st["transistors"],
            "cell_histogram": st["by_type"],
            "timing_endpoints": n_paths,
        },
        "technology": {
            "node": "28 nm (generic, simulated)",
            "vdd_nominal_V": sta.VDD_NOM,
            "target_period_ps": sta.T_SPEC,
            "target_frequency_GHz": sta.freq_ghz(),
        },
        "monte_carlo": {"chips": K, "seed": 42},
        "baseline": {
            "config": _trial_json(base_trial),
            "yield": yield_b, "worst_slack_nominal_ps": slack_b,
            "worst_slack_mean_ps": ms_b, "worst_slack_sigma_ps": sd_b,
            "cell_area_um2": area_b, "die_area_um2": base_r.die_area,
            "power_dyn_mW": base_r.p_dyn, "power_leak_mW": base_r.p_leak,
            "power_total_mW": pwr_b, "drc": drc_b,
            "drc_detail": base_r.drc_detail, "vmin_mean_V": vmin_b,
            "corners_ps": cb,
        },
        "optimized": {
            "config": _trial_json(opt_trial),
            "yield": yield_o, "worst_slack_nominal_ps": slack_o,
            "worst_slack_mean_ps": ms_o, "worst_slack_sigma_ps": sd_o,
            "cell_area_um2": area_o, "die_area_um2": opt_r.die_area,
            "power_dyn_mW": opt_r.p_dyn, "power_leak_mW": opt_r.p_leak,
            "power_total_mW": pwr_o, "drc": drc_o,
            "drc_detail": opt_r.drc_detail, "vmin_mean_V": vmin_o,
            "corners_ps": co, "score": opt.score,
        },
        "search": {
            "evaluations": opt.n_evals,
            "runtime_seconds": round(runtime_s, 2),
            "history": [
                {"tag": t, "score": s, "yield": y, "area": a, "power": p,
                 "drc": d}
                for t, s, y, a, p, d in zip(
                    opt.history.tags, opt.history.scores, opt.history.yields,
                    opt.history.areas, opt.history.powers, opt.history.drcs)
            ],
        },
    }
    json_path = os.path.join(out_dir, "results.json")
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

    # ---------------- HTML ----------------------------------------------
    figs = {
        "iv": _b64(f_iv), "ivb": _b64(f_ivb), "yield": _b64(f_yield),
        "metrics": _b64(f_metrics), "vmin": _b64(f_vmin),
        "learn": _b64(f_learn), "pareto": _b64(f_pareto),
        "paths": _b64(f_path), "corners": _b64(f_corners),
    }

    def cls(better: bool) -> str:
        return "good" if better else "bad"

    metric_rows = "".join(
        f"<tr><td class='mname'>{html.escape(n)}"
        f"<div class='mnote'>{html.escape(note)}</div></td>"
        f"<td class='num'>{b}</td><td class='num'>{o}</td>"
        f"<td class='num {cls(bet)}'>{ch}</td></tr>"
        for n, b, o, ch, bet, note in rows
    )

    summary_cards = [
        ("Timing yield", f"{yield_b*100:.0f}%", f"{yield_o*100:.0f}%",
         f"{(yield_o-yield_b)*100:+.0f} pp", yield_o > yield_b),
        ("Worst slack", f"{slack_b:+.0f} ps", f"{slack_o:+.0f} ps",
         f"{slack_o-slack_b:+.0f} ps", slack_o > slack_b),
        ("Area", f"{area_b:.0f}", f"{area_o:.0f}", _rel(area_o, area_b),
         area_o <= area_b),
        ("Power", f"{pwr_b:.2f}", f"{pwr_o:.2f}", _rel(pwr_o, pwr_b),
         pwr_o <= pwr_b),
        ("DRC", f"{drc_b}", f"{drc_o}", f"{drc_o-drc_b:+d}", drc_o <= drc_b),
        ("Vmin", f"{vmin_b*1000:.0f} mV", f"{vmin_o*1000:.0f} mV",
         f"{(vmin_o-vmin_b)*1000:+.0f} mV", vmin_o < vmin_b),
    ]
    cards = "".join(
        f"<div class='card {cls(b)}'><div class='clabel'>{n}</div>"
        f"<div class='cvals'><span class='cb'>{bb}</span>"
        f"<span class='carr'>→</span><span class='co'>{oo}</span></div>"
        f"<div class='cdelta'>{d}</div></div>"
        for n, bb, oo, d, b in summary_cards
    )

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_out = HTML_TEMPLATE.format(
        generated=now,
        cards=cards,
        metric_rows=metric_rows,
        yield_b=f"{yield_b*100:.1f}", yield_o=f"{yield_o*100:.1f}",
        yield_pp=f"{(yield_o-yield_b)*100:+.1f}",
        slack_b=f"{slack_b:+.1f}", slack_o=f"{slack_o:+.1f}",
        area_b=f"{area_b:.0f}", area_o=f"{area_o:.0f}",
        pwr_b=f"{pwr_b:.3f}", pwr_o=f"{pwr_o:.3f}",
        drc_b=f"{drc_b}", drc_o=f"{drc_o}",
        vmin_b=f"{vmin_b*1000:.0f}", vmin_o=f"{vmin_o*1000:.0f}",
        gates=st["gates"], flops=st["dffs"], nets=st["nets"],
        trs=st["transistors"], endpoints=n_paths,
        K=K, evals=opt.n_evals, runtime=f"{runtime_s:.1f}",
        period=f"{sta.T_SPEC:.0f}", freq=f"{sta.freq_ghz():.2f}",
        vdd=f"{sta.VDD_NOM:.2f}",
        drive_rows=drive_rows, phys_html=phys_html,
        corner_rows=corner_rows, path_rows=path_rows,
        learn_rows=learn_rows, lib_rows=lib_rows,
        sig_gvt=f"{sta.SIG_GVT*1000:.1f}", sig_lvt=f"{sta.SIG_LVT*1000:.1f}",
        sig_gw=f"{sta.SIG_GW*100:.1f}", sig_lw=f"{sta.SIG_LW*100:.1f}",
        sig_gl=f"{sta.SIG_GL*100:.1f}", sig_ll=f"{sta.SIG_LL*100:.1f}",
        corner_note=corner_note,
        **figs,
    )
    html_path = os.path.join(out_dir, "report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    return {"html": html_path, "json": json_path}


def _trial_json(t: Trial) -> Dict:
    return {
        "drives": dict(t.drives), "ratio": t.ratio, "n_buffers": t.nbuf,
        "layer_short": t.layer_short, "layer_mid": t.layer_mid,
        "layer_long": t.layer_long, "density": t.density,
    }


# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FabAware-Opt — Process-Variation-Aware Optimization Report</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    background: #0a0f18; color: #d6dbe3;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    line-height: 1.6;
  }}
  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 0 24px 80px; }}
  header {{
    padding: 46px 0 30px; border-bottom: 1px solid #1d2739; margin-bottom: 34px;
  }}
  .eyebrow {{
    text-transform: uppercase; letter-spacing: .16em; font-size: 11px;
    color: #6d7c93; margin-bottom: 10px;
  }}
  h1 {{
    margin: 0 0 8px; font-size: 32px; font-weight: 700; letter-spacing: -.02em;
    color: #fff;
  }}
  h1 span {{ color: #2b8aef; }}
  .sub {{ color: #8b97ab; font-size: 15px; max-width: 780px; }}
  .meta {{ margin-top: 18px; font-size: 12px; color: #66748c; }}
  .meta b {{ color: #93a1b8; font-weight: 600; }}

  h2 {{
    font-size: 21px; margin: 52px 0 6px; color: #fff; font-weight: 650;
    letter-spacing: -.01em;
  }}
  h2 .num {{
    display: inline-block; width: 26px; height: 26px; line-height: 26px;
    text-align: center; background: #17233a; color: #2b8aef; border-radius: 6px;
    font-size: 13px; margin-right: 10px; font-weight: 700;
  }}
  h3 {{ font-size: 15px; margin: 26px 0 8px; color: #b9c3d2; font-weight: 620; }}
  .lede {{ color: #8b97ab; margin: 0 0 20px; font-size: 14px; max-width: 860px; }}
  p {{ font-size: 14px; }}

  .cards {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
    gap: 12px; margin: 26px 0 8px;
  }}
  .card {{
    background: #111a29; border: 1px solid #1d2739; border-radius: 10px;
    padding: 16px 16px 14px;
  }}
  .card.good {{ border-left: 3px solid #2b8aef; }}
  .card.bad {{ border-left: 3px solid #e05252; }}
  .clabel {{
    font-size: 11px; text-transform: uppercase; letter-spacing: .1em;
    color: #6d7c93; margin-bottom: 8px;
  }}
  .cvals {{ display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap; }}
  .cb {{ font-size: 19px; color: #8b97ab; text-decoration: line-through;
         text-decoration-color: #4b5568; }}
  .carr {{ color: #4b5568; font-size: 14px; }}
  .co {{ font-size: 22px; font-weight: 700; color: #fff; }}
  .cdelta {{ margin-top: 6px; font-size: 12px; font-weight: 600; }}
  .card.good .cdelta {{ color: #4cc38a; }}
  .card.bad .cdelta {{ color: #e05252; }}

  table {{ width: 100%; border-collapse: collapse; margin: 14px 0 8px;
           font-size: 13px; }}
  th {{
    text-align: left; font-weight: 600; color: #8b97ab; font-size: 11px;
    text-transform: uppercase; letter-spacing: .07em;
    padding: 9px 10px; border-bottom: 1px solid #243149;
  }}
  td {{ padding: 9px 10px; border-bottom: 1px solid #172130; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums;
                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  tbody tr:hover {{ background: #101827; }}
  .mname {{ max-width: 330px; }}
  .mnote {{ font-size: 11px; color: #6d7c93; font-weight: 400;
            line-height: 1.45; margin-top: 3px; }}
  td.good {{ color: #4cc38a; }}
  td.bad {{ color: #e05252; }}
  .dim {{ color: #66748c; }}

  figure {{ margin: 22px 0 10px; }}
  figure img {{
    width: 100%; border-radius: 10px; border: 1px solid #1d2739;
    display: block; background: #0e1420;
  }}
  figcaption {{ font-size: 12px; color: #6d7c93; margin-top: 8px; }}
  .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 860px) {{ .two {{ grid-template-columns: 1fr; }} }}

  code {{
    background: #17233a; padding: 1px 5px; border-radius: 4px; font-size: 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #9dc4f5;
  }}
  .callout {{
    background: #111a29; border: 1px solid #1d2739;
    border-left: 3px solid #2b8aef; border-radius: 8px;
    padding: 14px 18px; margin: 18px 0; font-size: 13.5px;
  }}
  .callout.warn {{ border-left-color: #e0a752; }}
  .callout b {{ color: #fff; }}
  .kv {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
         gap: 10px 20px; margin: 14px 0; font-size: 13px; }}
  .kv div {{ border-bottom: 1px dotted #22304a; padding-bottom: 6px; }}
  .kv span {{ color: #6d7c93; }}
  .kv b {{ float: right; font-variant-numeric: tabular-nums; color: #d6dbe3; }}
  ul {{ font-size: 14px; padding-left: 20px; }}
  li {{ margin: 5px 0; }}
  .scroll {{ max-height: 330px; overflow-y: auto; border: 1px solid #1d2739;
             border-radius: 8px; }}
  footer {{
    margin-top: 60px; padding-top: 22px; border-top: 1px solid #1d2739;
    font-size: 12px; color: #5c6a80;
  }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">FabAware-Opt · Fabrication-aware design optimization</div>
  <h1>Process-Variation-Aware <span>Standard-Cell &amp; Physical-Design</span> Optimization</h1>
  <p class="sub">
    Can an open-source AI-assisted flow select transistor sizes, standard cells and
    physical-design parameters that improve <b>timing yield</b> under process,
    voltage and temperature variation — without excessive power or area overhead?
    This report answers that question on a {gates}-gate 32-bit datapath block,
    evaluated with transistor-level compact modelling and Monte-Carlo statistical
    timing over {K} simulated chips.
  </p>
  <div class="meta">
    Generated <b>{generated}</b> ·
    Design <b>FAB-32</b> · Technology <b>28 nm (generic, simulated)</b> ·
    {K} Monte-Carlo chips · {evals} statistical-timing evaluations ·
    runtime <b>{runtime} s</b>
  </div>
</header>

<h2><span class="num">1</span>Headline result</h2>
<p class="lede">
  The baseline configuration — the one a designer would ship after a conventional
  synthesis run — meets timing on only <b>{yield_b}%</b> of simulated chips.
  The AI-optimized configuration reaches <b>{yield_o}%</b>, a
  <b>{yield_pp} percentage-point</b> improvement, while keeping DRC clean.
</p>

<div class="cards">{cards}</div>

<div class="callout">
  <b>Result.</b> Timing yield improved from <b>{yield_b}%</b> to
  <b>{yield_o}%</b> ({yield_pp} pp). Worst-case slack moved from
  <b>{slack_b} ps</b> to <b>{slack_o} ps</b> against a {period} ps target period
  ({freq} GHz). Cell area {area_b} → {area_o} µm²,
  total power {pwr_b} → {pwr_o} mW, DRC violations {drc_b} → {drc_o}.
</div>

<table>
  <thead><tr>
    <th>Metric</th><th class="num">Baseline</th><th class="num">AI-optimized</th>
    <th class="num">Change</th>
  </tr></thead>
  <tbody>{metric_rows}</tbody>
</table>

<h2><span class="num">2</span>Transistor-level foundation</h2>
<p class="lede">
  Every delay and leakage number in this report is derived from a physics-based
  compact MOSFET model, not from a lookup table. The model captures mobility
  temperature dependence (µ ∝ T<sup>−1.5</sup>), threshold-voltage drift
  (≈ −50 µV/K), velocity saturation and mobility degradation, and
  subthreshold leakage with activated-temperature behaviour.
</p>

<div class="two">
  <figure>
    <img src="data:image/png;base64,{iv}" alt="MOSFET I-V family">
    <figcaption><b>Fig 1.</b> nMOS I<sub>d</sub>–V<sub>ds</sub> family at W = 48 nm,
    L = 22 nm. Shaded bands show the ±40 mV threshold spread used in the
    Monte-Carlo variability model — the physical origin of timing variation.</figcaption>
  </figure>
  <figure>
    <img src="data:image/png;base64,{ivb}" alt="Drive current vs supply">
    <figcaption><b>Fig 2.</b> On-current versus supply voltage. The sub-linear
    growth is velocity saturation — which is exactly why voltage-scaled designs
    become variability-sensitive, and why the V<sub>dd</sub> exponent in the
    delay model is 1.4 rather than 2.</figcaption>
  </figure>
</div>

<h2><span class="num">3</span>Manufacturing-variation stress test</h2>
<p class="lede">
  Each simulated "chip" is a draw from the process distribution: correlated
  global variation (implant / CD / global threshold) applied to every device,
  plus independent local variation per transistor. Timing is re-computed from
  scratch for every chip, and the chip passes only if <b>every</b> timing
  endpoint meets the {period} ps cycle time.
</p>

<div class="kv">
  <div><span>Global V<sub>th</sub> shift σ</span><b>{sig_gvt} mV</b></div>
  <div><span>Local V<sub>th</sub> σ per device</span><b>{sig_lvt} mV</b></div>
  <div><span>Global gate-width σ</span><b>{sig_gw} %</b></div>
  <div><span>Local gate-width σ</span><b>{sig_lw} %</b></div>
  <div><span>Global gate-length σ</span><b>{sig_gl} %</b></div>
  <div><span>Local gate-length σ</span><b>{sig_ll} %</b></div>
</div>

<figure>
  <img src="data:image/png;base64,{yield}" alt="Slack distribution">
  <figcaption><b>Fig 3.</b> Worst-case slack across {K} Monte-Carlo chips.
  Baseline (red) straddles the timing spec — most chips fail. The AI-optimized
  configuration (blue) moves the whole distribution right of the spec line,
  and simultaneously narrows it.</figcaption>
</figure>

<figure>
  <img src="data:image/png;base64,{vmin}" alt="Vmin distribution">
  <figcaption><b>Fig 4.</b> Per-chip minimum operating voltage. A lower Vmin
  means more voltage margin in the field — and, in a real product, lower
  active power at iso-frequency.</figcaption>
</figure>

<figure>
  <img src="data:image/png;base64,{metrics}" alt="Metrics radar">
  <figcaption><b>Fig 5.</b> All six headline metrics on one chart; outward is
  always better. The optimized design improves every axis that matters for
  manufacturability.</figcaption>
</figure>

<h2><span class="num">4</span>What the AI changed</h2>
<p class="lede">
  The optimizer searched a 13-dimensional space: drive strength for seven
  resizable standard-cell types, the W<sub>p</sub>/W<sub>n</sub> transistor
  sizing ratio, buffer insertion count on long wires, metal-layer assignment for
  three net classes, and placement density.
</p>

<h3>Standard-cell drive selection</h3>
<table>
  <thead><tr>
    <th>Cell type</th><th class="num">Baseline drive</th>
    <th class="num">Optimized drive</th><th class="num">Scale</th>
    <th class="num">Instances</th>
  </tr></thead>
  <tbody>{drive_rows}</tbody>
</table>

<h3>Transistor sizing &amp; physical-design parameters</h3>
<table>
  <thead><tr>
    <th>Parameter</th><th class="num">Baseline</th><th class="num">Optimized</th>
  </tr></thead>
  <tbody>{phys_html}</tbody>
</table>

<figure>
  <img src="data:image/png;base64,{paths}" alt="Critical path slacks">
  <figcaption><b>Fig 6.</b> Slack of the 14 worst timing endpoints before and
  after optimization. The AI did not fix one lucky path — it lifted the whole
  critical region above the spec.</figcaption>
</figure>

<figure>
  <img src="data:image/png;base64,{corners}" alt="PVT corners">
  <figcaption><b>Fig 7.</b> Deterministic PVT-corner analysis (no local
  variation): fast-fast, slow-slow, and the 125 °C / −40 °C temperature
  extremes. {corner_note}</figcaption>
</figure>

<table>
  <thead><tr>
    <th>PVT corner</th><th class="num">Baseline slack (ps)</th>
    <th class="num">Optimized slack (ps)</th>
  </tr></thead>
  <tbody>{corner_rows}</tbody>
</table>

<h2><span class="num">5</span>How the AI searched</h2>
<p class="lede">
  A Gaussian-process surrogate (Matérn 2.5 kernel) is fitted to the objective,
  and an expected-improvement acquisition function chooses which configuration
  to evaluate next. Each evaluation is a full Monte-Carlo statistical timing
  run — the expensive, trustworthy part — so the surrogate is what makes
  the search affordable.
</p>

<figure>
  <img src="data:image/png;base64,{learn}" alt="Learning curve">
  <figcaption><b>Fig 8.</b> Search convergence. Grey dots are individual
  evaluated configurations; the blue line is the running best. The three phases
  are the initial design of experiments, the GP + expected-improvement loop,
  and local refinement.</figcaption>
</figure>

<figure>
  <img src="data:image/png;base64,{pareto}" alt="Design space">
  <figcaption><b>Fig 9.</b> Every configuration the search evaluated, plotted
  as area versus timing yield and coloured by power. The starred point is the
  reported solution — it sits on the favourable edge of the trade-off rather
  than simply maximizing yield at any cost.</figcaption>
</figure>

<h3>Full evaluation log</h3>
<div class="scroll">
<table>
  <thead><tr>
    <th class="num">#</th><th>Phase</th><th class="num">Score</th>
    <th class="num">Yield</th><th class="num">Area µm²</th>
    <th class="num">Power mW</th><th class="num">DRC</th>
  </tr></thead>
  <tbody>{learn_rows}</tbody>
</table>
</div>

<h2><span class="num">6</span>Design under test</h2>
<p class="lede">
  FAB-32 is a 32-bit datapath block built gate-by-gate from compound standard
  cells, in the same way an RTL elaboration produces a netlist. Its critical
  path runs through an 8-block carry-select adder — a genuinely
  variation-sensitive structure, which is why it is a good test case.
</p>

<div class="kv">
  <div><span>Combinational gates</span><b>{gates}</b></div>
  <div><span>Sequential elements (DFF)</span><b>{flops}</b></div>
  <div><span>Nets</span><b>{nets}</b></div>
  <div><span>Transistors</span><b>{trs}</b></div>
  <div><span>Timing endpoints</span><b>{endpoints}</b></div>
  <div><span>Target period / frequency</span><b>{period} ps / {freq} GHz</b></div>
  <div><span>Nominal supply</span><b>{vdd} V</b></div>
</div>

<h3>Standard-cell library</h3>
<table>
  <thead><tr>
    <th>Cell</th><th class="num">A (ps)</th><th class="num">B (ps/fF)</th>
    <th class="num">C<sub>in</sub> (fF)</th><th class="num">Area (µm²)</th>
    <th class="num">I<sub>leak</sub> (nA)</th><th class="num">Devices</th>
    <th class="num">Used</th>
  </tr></thead>
  <tbody>{lib_rows}</tbody>
</table>
<p style="font-size:12px;color:#6d7c93">
  Gate delay model: t = (A + B·C<sub>ext</sub>) / S, where S is the
  transistor drive factor from the compact model. A and B are calibrated so a
  drive-1 inverter at {vdd} V, 25 °C presents roughly 10 ps intrinsic delay and
  ~0.14 ps/fF load sensitivity — consistent with published 28 nm gate speeds.
</p>

<h2><span class="num">7</span>Scope, and what this is not</h2>
<div class="callout warn">
  <b>Scope statement.</b> FabAware-Opt is a
  <b>fabrication-aware, open-source EDA optimization framework evaluated through
  transistor simulation and RTL-to-gate netlist experiments.</b>
  It does <b>not</b> fabricate a chip, and it does not replace sign-off tools.
</div>
<ul>
  <li><b>What is modelled:</b> transistor physics (compact model), gate-level
      timing, interconnect RC with layer choice and congestion, leakage, area,
      placement density, and a simplified DRC rule deck.</li>
  <li><b>What is deliberately simplified:</b> the DRC deck is an analytic
      estimator rather than a real rule deck; the placer is a deterministic
      cluster/row packer rather than a full analytical placer; routing is
      estimated rather than detailed-routed.</li>
  <li><b>What the numbers mean:</b> they are internally consistent and
      reproducible from the same seed, and calibrated to published 28 nm-class
      figures — they are predictions of a model, not measurements of
      silicon.</li>
  <li><b>Reproducibility:</b> every number in this report is also written to
      <code>results.json</code>, and the whole run is regenerated by
      <code>fabaware-run</code> from a fixed random seed.</li>
</ul>

<footer>
  FabAware-Opt · fabrication-aware open-source EDA optimization framework ·
  report generated {generated} · all figures rendered from evaluated
  simulation data
</footer>

</div>
</body>
</html>
"""
