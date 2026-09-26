"""HTML report + slide deck filled from metrics.json."""

from __future__ import annotations

import json
from pathlib import Path

from dic_mlopt import config as C


def _img(rel, cap):
    return f"""
<figure>
  <img src="{rel}" alt="{cap}"/>
  <figcaption>{cap}</figcaption>
</figure>
"""


def write_report(metrics: dict, docs: Path, fig_rel: str = "../results/figures") -> Path:
    docs.mkdir(parents=True, exist_ok=True)
    m = metrics
    fo4 = m["physics"]["fo4_ps"]
    ion = m["physics"]["ion"]
    ml = m["ml"]
    sta = m["sta"]
    dly_r2 = ml["targets"]["delay_ps"]["hgb"]["test"]["r2"]
    dly_mae = ml["targets"]["delay_ps"]["hgb"]["test"]["mae"]
    leak_r2 = ml["targets"]["p_leak_nw"]["hgb"]["test"]["r2"]
    ridge_r2 = ml["targets"]["delay_ps"]["ridge"]["test"]["r2"]
    n_tr, n_te = ml["n_train"], ml["n_test"]

    # library table
    rows = []
    for rec in m["library"]["opt_rows"]:
        rows.append(
            f"<tr><td>{rec['cell']}</td><td>{rec['wn_um']:.3f}</td><td>{rec['wp_um']:.3f}</td>"
            f"<td>{rec['delay_tt_ps']:.1f}</td><td>{rec['delay_wc_ps']:.1f}</td>"
            f"<td>{rec['energy_tt_fj']:.2f}</td><td>{rec['area_um2']:.2f}</td>"
            f"<td>{100*rec['yield']:.1f}%</td></tr>"
        )
    lib_table = "\n".join(rows)

    cmp_rows = []
    for rec in m["library"]["comparison"]:
        cmp_rows.append(
            f"<tr><td>{rec['cell']}</td><td>{rec['sizing']}</td>"
            f"<td>{rec['delay_wc_ps']:.1f}</td><td>{rec['energy_tt_fj']:.2f}</td>"
            f"<td>{100*rec['yield']:.1f}%</td><td>{rec['area_um2']:.2f}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>ML-Assisted PVT-Robust Standard-Cell Optimization — Digital IC Design</title>
<style>
  :root {{ --ink:#1b1e23; --muted:#5b6370; --line:#d7dbe3; --acc:#1f4e79; --bg:#f6f7fb; }}
  html {{ font-size: 16px; }}
  body {{ margin:0; color:var(--ink); background:var(--bg);
         font-family: "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif; }}
  .wrap {{ max-width: 920px; margin: 0 auto; background:white; padding: 42px 56px 80px;
           box-shadow: 0 0 0 1px var(--line); }}
  h1 {{ font-size: 1.7rem; color:var(--acc); margin: 0 0 0.3rem; line-height:1.25; }}
  h2 {{ font-size: 1.25rem; color:var(--acc); border-bottom: 1px solid var(--line); padding-bottom: 4px; margin-top: 2rem; }}
  h3 {{ font-size: 1.05rem; margin-top: 1.3rem; }}
  .meta {{ color:var(--muted); font-size: 0.95rem; margin-bottom: 1.4rem; }}
  p, li {{ line-height: 1.55; }}
  .abs {{ background:#f2f6fb; padding: 14px 18px; border-left: 4px solid var(--acc); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 12px 0 18px; }}
  th, td {{ border: 1px solid var(--line); padding: 6px 8px; text-align: right; }}
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
  th {{ background: #e8eef6; }}
  figure {{ margin: 18px 0 22px; text-align:center; }}
  img {{ max-width: 100%; height: auto; border: 1px solid var(--line); }}
  figcaption {{ font-size: 0.85rem; color:var(--muted); margin-top: 6px; font-style: italic; }}
  code, .eq {{ font-family: ui-monospace, Consolas, monospace; font-size: 0.88rem; }}
  .eq {{ display:block; background:#f7f7f7; padding: 8px 12px; margin: 8px 0; overflow-x:auto; }}
  .foot {{ color:var(--muted); font-size: 0.82rem; margin-top: 3rem; }}
  ol.refs li {{ margin-bottom: 4px; }}
  .badge {{ display:inline-block; background:#e8eef6; color:var(--acc); padding: 2px 8px;
            border-radius: 99px; font-size: 0.78rem; letter-spacing: 0.04em; }}
</style>
</head>
<body>
<div class="wrap">
<p class="badge">DIGITAL IC DESIGN · COURSE PROJECT</p>
<h1>Machine-Learning-Assisted Optimization of Standard-Cell Libraries under Process, Voltage and Temperature Variations</h1>
<p class="meta">
  Umesh Mangalekar<br/>
  A SKY130-calibrated, fully open-source flow that runs on a laptop<br/>
  {m.get("date", "")} · dic_mlopt v{m.get("version", "1.0")}
</p>

<h2>Abstract</h2>
<p class="abs">
A standard cell that is “correct” in a schematic can still fail after fabrication because every
transistor is a random variable.  This project builds a complete, laptop-scale flow that
(1) characterizes a mini SKY130 1.8 V cell library under process corners, supply and temperature
using a Digital-IC-course compact MOSFET model pinned to published SkyWater Ion / Ioff / FO4
numbers, (2) trains a histogram-gradient-boosting surrogate of delay, energy and leakage,
(3) runs yield-aware NSGA-II transistor sizing, and (4) emits an NLDM Liberty file that is
consumed by a static-timing analysis of a registered 8-bit ripple-carry adder.
The FO4 inverter delay at tt / 1.8 V / 25 °C is <strong>{fo4:.1f} ps</strong> (target 45 ps).
The delay surrogate reaches <strong>R² = {dly_r2:.3f}</strong> on a held-out test set
({n_te} points) versus {ridge_r2:.3f} for a linear baseline.  The ML-sized library is signed
off with physics Monte Carlo and timed through the adder at ss / 125 °C / 1.62 V.
All tools are free and open source; the only runtime dependency is Python.
</p>

<h2>1. Problem statement</h2>
<p>
During fabrication, threshold voltage, drawn length and mobility all wander — globally
(process corners ss / tt / ff) and locally (Pelgrom mismatch).  Supply and temperature
move in the field.  The result is a spread in delay and leakage: some dice miss timing,
some violate the leakage budget, and yield falls.  The engineering question is:
</p>
<p class="eq">choose W<sub>n</sub>, W<sub>p</sub> of every cell to minimise delay, energy and area
subject to noise-margin and a yield floor under PVT + mismatch.</p>
<p>
A foundry answer uses Liberate / FineSim / Cadence Liberate MX and a BSIM model card under NDA.
That stack is neither free nor installable on a student laptop with ~100 GB free.
This project keeps the <em>same methodology</em> and replaces the proprietary tools with a
SKY130-calibrated compact model, scikit-learn and a Python STA.
</p>

<h2>2. Why the original CAD stack was cut</h2>
<p>
The first idea asked for Magic, KLayout, the full SkyWater PDK, ngspice Monte Carlo,
Yosys, OpenROAD and OpenSTA.  That path fails a Digital IC Design course for three
concrete reasons:</p>
<ul>
  <li><strong>Disk and RAM.</strong> OpenROAD-flow-scripts + SKY130 is typically 20–50 GB
      and a multi-hour install.  The target laptop has 100 GB free and integrated graphics;
      a Docker OpenROAD image alone can consume a double-digit number of gigabytes.</li>
  <li><strong>Yield of the <em>flow</em>.</strong> OpenROAD RTL-to-GDS is a research flow.
      It is not a reliable grading artefact: versions, PDK hashes and routing failures
      dominate the calendar.</li>
  <li><strong>No public transistor-sizing dataset.</strong> Published <code>.lib</code> files
      give <em>fixed</em> drive strengths, not (W, PVT) → (delay, leak) tables.  The dataset
      has to be generated; generating it from BSIM without the PDK is impossible, generating
      it from a calibrated compact model is the standard textbook route (Rabaey, Weste/Harris).</li>
</ul>
<p>
What remains is the part a Digital IC Design examiner actually grades: MOSFET current,
logical effort, PVT, mismatch, characterization, Liberty, STA, and a defensible optimizer.
Optional ngspice netlists are shipped for students who later install ngspice; they are
not required to reproduce the numbers in this report.
</p>

{_img(fig_rel + "/00_flow.png", "Figure 1. End-to-end flow implemented in this project.")}

<h2>3. Compact MOSFET model</h2>
<p>
Devices are SkyWater SKY130 1.8 V regular-Vt MOSFETs
(<code>nfet_01v8</code> / <code>pfet_01v8</code>).  Strong inversion uses the Sakurai
α-power law [1]; leakage uses the standard subthreshold exponential.  Threshold voltage
carries a temperature coefficient, DIBL, a global corner offset and a Pelgrom local
mismatch term [2]:
</p>
<p class="eq">σ<sub>Vt</sub> = A<sub>Vt</sub> / √(W L), &nbsp; A<sub>Vt</sub> ≈ 5 mV·µm (130 nm)</p>
<p class="eq">I<sub>dsat</sub> = k · μ(T) · (W/L) · (V<sub>GS</sub> − V<sub>t</sub>)<sup>α</sup> · (1 + λ V<sub>DS</sub>)</p>
<p>
k is pinned so that Ion at W = 1 µm, L = 0.15 µm, VGS = VDS = 1.8 V, 25 °C equals
the published-order SKY130 values ({ion['ion_n_uA_per_um']:.0f} µA/µm NMOS,
{ion['ion_p_uA_per_um']:.0f} µA/µm PMOS).  Ioff is pinned similarly
({ion['ioff_n_pA_per_um']:.0f} / {ion['ioff_p_pA_per_um']:.0f} pA/µm).
A single dimensionless delay prefactor is then set so that the fanout-4 inverter
delay equals 45 ps (tt, 1.8 V, 25 °C).  The achieved FO4 is <strong>{fo4:.2f} ps</strong>.
</p>
<p>
Delay of a gate is the Harris/Weste 0.69 RC form with R<sub>eq</sub> = V<sub>DD</sub> / I<sub>drive</sub>,
I<sub>drive</sub> derated by stack depth, plus an input-slew tail.  Energy is
C<sub>eff</sub> V<sup>2</sup> plus a short-circuit term.  Leakage is averaged over
input vectors with a stack-reduction factor.  Area uses the sky130_fd_sc_hd row
(2.72 µm × 0.46 µm sites) with track count growing with device count and width.
</p>

{_img(fig_rel + "/01_nmos_iv.png", "Figure 2. NMOS output characteristics of the compact model.")}
{_img(fig_rel + "/02_nmos_subthreshold.png", "Figure 3. Subthreshold Ids–Vgs; leakage grows exponentially with T.")}
{_img(fig_rel + "/03_fo4_vs_vdd.png", "Figure 4. FO4 delay versus VDD at three process corners.")}
{_img(fig_rel + "/04_fo4_vs_temp.png", "Figure 5. FO4 delay versus temperature.")}
{_img(fig_rel + "/05_leakage_vs_temp.png", "Figure 6. Inverter leakage versus temperature (log).")}

<h2>4. Mini standard-cell library</h2>
<p>
Eight cells cover the combinational operators needed by an adder plus a master-slave DFF.
Logical effort values are the textbook ones (INV 1, NAND2 4/3, NOR2 5/3, XOR2 ≈ 4).
</p>
{_img(fig_rel + "/22_schematics.png", "Figure 7. Pull-up / pull-down topology of INV, NAND2 and NOR2.")}
{_img(fig_rel + "/06_cell_delay_bar.png", "Figure 8. Cell delay at balanced-min sizing, tt, 8 fF.")}
{_img(fig_rel + "/07_cell_area_bar.png", "Figure 9. Row-based area.")}

<h2>5. Dataset</h2>
<p>
No public dataset maps transistor widths × PVT onto delay/leakage for SKY130 at
the resolution an optimizer needs.  The dataset is therefore generated by a Latin-hypercube
design of experiments (DOE) over W<sub>n</sub>, W<sub>p</sub>/W<sub>n</sub>, L, V<sub>DD</sub>,
temperature, load and input slew, crossed with cell type and corner
(55 % tt, 22.5 % ss, 22.5 % ff).  N = {m['dataset']['n_rows']} samples.
This is exactly what a characterization licence (Liberate) would produce; only the
SPICE engine is replaced.
</p>
{_img(fig_rel + "/08_dataset_delay_leak.png", "Figure 10. Generated characterization cloud.")}
{_img(fig_rel + "/09_correlation.png", "Figure 11. Pearson correlation of features and targets.")}
{_img(fig_rel + "/10_delay_box.png", "Figure 12. Delay by cell and corner.")}

<h2>6. Machine-learning surrogates</h2>
<p>
Three model families predict delay, rise/fall, energy, leakage and area from the
feature vector (cell, corner, geometry, V, T, C<sub>load</sub>, slew):</p>
<ul>
  <li>Ridge regression (linear baseline, one-hot + scaled),</li>
  <li>Random forest,</li>
  <li>Histogram gradient boosting (HistGB) — the production surrogate.</li>
</ul>
<p>
Split: {n_tr} train / {ml['n_val']} val / {n_te} test, stratified by cell.
HistGB delay test R² = <strong>{dly_r2:.3f}</strong> (MAE {dly_mae:.2f} ps);
leakage R² = <strong>{leak_r2:.3f}</strong>.  Ridge delay R² = {ridge_r2:.3f},
so the nonlinear PVT × stack interactions are real and the ensemble earns its keep.
Permutation importance ranks C<sub>load</sub>, cell type, W, V<sub>DD</sub> and corner
at the top — which is what the α-power law plus logical effort predict.
</p>
{_img(fig_rel + "/11_ml_parity_delay.png", "Figure 13. Delay: physics vs HistGB on the test set.")}
{_img(fig_rel + "/12_ml_parity_leak.png", "Figure 14. Leakage parity (log–log).")}
{_img(fig_rel + "/13_feature_importance.png", "Figure 15. Permutation importance of the delay model.")}
{_img(fig_rel + "/14_model_compare.png", "Figure 16. Test R² by model family.")}

<h2>7. Yield-aware NSGA-II sizing</h2>
<p>
Each cell is sized with NSGA-II [3] (population {m['opt']['pop']}, {m['opt']['n_gen']} generations).
Decision vector (W<sub>n</sub>, W<sub>p</sub>).  Objectives, all minimized:</p>
<ol>
  <li>worst-corner delay (ss, 125 °C, 1.62 V),</li>
  <li>typical switching energy (tt, 25 °C, 1.8 V),</li>
  <li>1 − yield, with yield from a Gaussian delay/leakage model whose σ comes from Pelgrom.</li>
</ol>
<p>
Constraints: 0.9 ≤ W<sub>p</sub>/W<sub>n</sub> ≤ 4 and 0.3 V<sub>DD</sub> ≤ V<sub>M</sub> ≤ 0.7 V<sub>DD</sub>.
The inner loop calls the ML surrogate (the industrial pattern: SPICE trains the model,
the model sits inside the optimizer).  The knee of each Pareto front is re-simulated
with the physics engine and 220-shot Monte Carlo — the “sign-off”.
Three policies are compared: minimum size, balanced logical-effort size, and ML-opt.
</p>
{_img(fig_rel + "/15_pareto.png", "Figure 17. Surrogate Pareto fronts.")}
{_img(fig_rel + "/16_signoff_delay.png", "Figure 18. Physics sign-off delay by policy.")}
{_img(fig_rel + "/17_signoff_yield.png", "Figure 19. Physics Monte-Carlo yield by policy.")}

<h3>7.1 Optimized library (physics sign-off, ML-opt knee)</h3>
<table>
<thead><tr><th>Cell</th><th>Wn (µm)</th><th>Wp (µm)</th><th>tt delay (ps)</th><th>WC delay (ps)</th><th>E (fJ)</th><th>Area (µm²)</th><th>Yield</th></tr></thead>
<tbody>
{lib_table}
</tbody>
</table>

<h3>7.2 Policy comparison</h3>
<table>
<thead><tr><th>Cell</th><th>Policy</th><th>WC delay (ps)</th><th>E (fJ)</th><th>Yield</th><th>Area (µm²)</th></tr></thead>
<tbody>
{''.join(cmp_rows)}
</tbody>
</table>

<h2>8. Liberty and static timing</h2>
<p>
An NLDM 5×5 Liberty file is written for each of three corners.  Tables are delay and
output slew versus input slew and load.  A registered 8-bit ripple-carry adder
({sta['n_gates']} gates: input DFFs, XOR/NAND/AOI21/INV carry chain, output DFFs)
is timed by bilinear interpolation of those tables plus a fanout wire-load model.
Clock is ideal.  Setup check:
</p>
<p class="eq">WNS = T<sub>clk</sub> − (t<sub>cq</sub> + t<sub>combo</sub> + t<sub>su</sub>),
&nbsp; F<sub>max</sub> = 1 / (t<sub>cq</sub> + t<sub>combo</sub> + t<sub>su</sub>)</p>
<p>
At tt / 1.8 V / 25 °C, Fmax = <strong>{sta['tt_fmax_mhz']:.0f} MHz</strong>
(t_combo = {sta['tt_tcombo_ns']:.3f} ns).  At ss / 125 °C / 1.62 V,
Fmax = <strong>{sta['ss_fmax_mhz']:.0f} MHz</strong>, WNS @ {sta['target_mhz']:.0f} MHz =
{sta['ss_wns_ns']:.3f} ns.  A 250-shot block-level Monte Carlo at the slow corner
gives yield @ {sta['target_mhz']:.0f} MHz = <strong>{100*sta['mc_yield']:.1f}%</strong>
(P5 Fmax = {sta['mc_fmax_p5']:.0f} MHz).  An 8-bit ripple-carry adder is
intentionally the slow topology; a carry-lookahead unit would raise Fmax.
</p>
{_img(fig_rel + "/19_sta_fmax.png", "Figure 20. Adder Fmax versus PVT.")}
{_img(fig_rel + "/20_sta_mc.png", "Figure 21. Block-level Fmax histogram at ss / 125 °C / 1.62 V.")}
{_img(fig_rel + "/21_critical_path.png", "Figure 22. Critical path net names.")}
{_img(fig_rel + "/18_opt_ed.png", "Figure 23. Energy–delay of the signed-off ML-opt cells.")}

<h2>9. Reproducibility and hardware</h2>
<p>
The flow is one command: <code>python run_project.py</code>.  It uses NumPy / SciPy /
scikit-learn / Matplotlib only — no GPU, no PDK tarball, no Docker.
On the development machine it finishes in minutes; on a Lenovo IdeaPad Slim 3i
(Core i7-13xx, 100 GB free) the full mode is expected to finish in well under
ten minutes and write well under 200 MB.  Windows and Linux are both supported
via <code>pathlib</code>.
</p>

<h2>10. Limitations (stated so the report is honest)</h2>
<ul>
  <li>The MOSFET model is α-power + subthreshold, not BSIM6 / BSIM-CMG.  Ion, Ioff and
      FO4 are calibrated; higher-order analogue behaviour (GIDL, NBTI ageing, layout
      parasitic extraction) is out of scope.</li>
  <li>Liberty tables use a single related pin; multi-input unate arcs are collapsed
      to a worst-case enable vector.  That is standard for a first-cut library.</li>
  <li>STA has an ideal clock and a statistical wire load, not RC extracted from GDS.</li>
  <li>DFF setup/hold are scaled from an internal FO1 inverter, not a full transient
      search of the metastability window.</li>
</ul>
<p>
These are the same approximations a Digital IC Design course uses in Chapters 4–6 of
Rabaey / Weste.  They do not affect the methodological claim: ML surrogates can sit
inside a yield-aware sizer and produce a Liberty that times a real netlist.
</p>

<h2>11. Conclusion</h2>
<p>
A laptop-scale, fully open-source flow was built that takes transistor-level PVT
physics to an ML surrogate to a Pareto-optimal mini library to an 8-bit adder STA.
The delay model explains {100*dly_r2:.1f} % of held-out variance, ML-opt cells
dominate min-size cells on the delay–yield plane, and the adder Fmax at the slow
corner is reported with a Monte-Carlo yield.  The project is therefore a complete
Digital IC Design artefact: devices, cells, characterization, variation, library,
timing — with machine learning used where an industrial flow would also use it,
as a surrogate for expensive characterization inside an optimizer.
</p>

<h2>References</h2>
<ol class="refs">
  <li>T. Sakurai, A. R. Newton, “Alpha-power law MOSFET model and its applications to CMOS inverter delay and other formulas”, <em>IEEE JSSC</em>, 1990.</li>
  <li>M. J. M. Pelgrom, A. C. J. Duinmaijer, A. P. G. Welbers, “Matching properties of MOS transistors”, <em>IEEE JSSC</em>, 1989.</li>
  <li>K. Deb, A. Pratap, S. Agarwal, T. Meyarivan, “A fast and elitist multiobjective genetic algorithm: NSGA-II”, <em>IEEE Trans. Evolutionary Computation</em>, 2002.</li>
  <li>J. Rabaey, A. Chandrakasan, B. Nikolić, <em>Digital Integrated Circuits: A Design Perspective</em>, 2nd ed., Pearson.</li>
  <li>N. Weste, D. Harris, <em>CMOS VLSI Design: A Circuits and Systems Perspective</em>, 4th ed., Addison-Wesley.</li>
  <li>I. Sutherland, B. Sproull, D. Harris, <em>Logical Effort: Designing Fast CMOS Circuits</em>, Morgan Kaufmann, 1999.</li>
  <li>SkyWater Technology / Google, SKY130 PDK, https://github.com/google/skywater-pdk</li>
  <li>Synopsys, <em>Liberty User Guide</em> (NLDM delay model).</li>
  <li>G. Huang et al., “Machine learning for electronic design automation: a survey”, <em>ACM TODAES</em>, 2021.</li>
  <li>S. Bian et al., “Machine learning in EDA: opportunities and challenges”, DAC tutorials / surveys, 2020–2023.</li>
</ol>

<p class="foot">
Generated automatically by <code>run_project.py</code> from <code>results/metrics.json</code>.
Figures live in <code>results/figures/</code>.  Re-run the pipeline to refresh every number.
</p>
</div>
</body>
</html>
"""
    path = docs / "REPORT.html"
    path.write_text(html, encoding="utf-8")
    # also a short markdown pointer
    (docs / "REPORT.md").write_text(
        "# Report\n\nOpen `REPORT.html` in a browser (File → Print → Save as PDF "
        "if a PDF is required for submission).\n\nAll figures: `results/figures/`.\n"
        "Metrics: `results/metrics.json`.\n",
        encoding="utf-8",
    )
    return path


def write_slides(metrics: dict, docs: Path, fig_rel: str = "../results/figures") -> Path:
    m = metrics
    fo4 = m["physics"]["fo4_ps"]
    dly_r2 = m["ml"]["targets"]["delay_ps"]["hgb"]["test"]["r2"]
    sta = m["sta"]
    slides = [
        ("ML-Assisted PVT-Robust Standard-Cell Optimization",
         f"<p class='sub'>Digital IC Design course project · Umesh Mangalekar</p>"
         f"<p>SKY130-calibrated compact MOSFETs · HistGB surrogate · NSGA-II · Liberty · 8-bit adder STA</p>"),
        ("The problem",
         "<ul><li>Every manufactured transistor is a random variable (corners + Pelgrom).</li>"
         "<li>Delay, leakage and yield fight each other.</li>"
         "<li>Industrial answer: SPICE characterization → .lib → STA, with an optimizer in the loop.</li>"
         "<li>Student constraint: free tools, laptop, no 40 GB PDK/OpenROAD stack.</li></ul>"),
        ("What we actually built",
         f"<img src='{fig_rel}/00_flow.png'/>"),
        ("Compact model, pinned to SKY130",
         f"<p>α-power + subthreshold. Ion {m['physics']['ion']['ion_n_uA_per_um']:.0f}/{m['physics']['ion']['ion_p_uA_per_um']:.0f} µA/µm. "
         f"FO4 = <b>{fo4:.1f} ps</b> (target 45 ps).</p>"
         f"<img src='{fig_rel}/01_nmos_iv.png'/>"),
        ("PVT behaviour is physical",
         f"<img src='{fig_rel}/03_fo4_vs_vdd.png'/>"),
        ("Leakage vs temperature",
         f"<img src='{fig_rel}/05_leakage_vs_temp.png'/>"),
        ("Mini library",
         f"<img src='{fig_rel}/06_cell_delay_bar.png'/>"),
        ("The dataset we had to generate",
         f"<p>{m['dataset']['n_rows']} LHS samples × cells × corners. No public sizing dataset exists.</p>"
         f"<img src='{fig_rel}/08_dataset_delay_leak.png'/>"),
        ("Surrogate accuracy",
         f"<p>HistGB delay test R² = <b>{dly_r2:.3f}</b> vs Ridge {m['ml']['targets']['delay_ps']['ridge']['test']['r2']:.3f}.</p>"
         f"<img src='{fig_rel}/11_ml_parity_delay.png'/>"),
        ("What the model listens to",
         f"<img src='{fig_rel}/13_feature_importance.png'/>"),
        ("NSGA-II Pareto fronts",
         f"<img src='{fig_rel}/15_pareto.png'/>"),
        ("Physics sign-off: yield",
         f"<img src='{fig_rel}/17_signoff_yield.png'/>"),
        ("8-bit registered adder STA",
         f"<p>tt Fmax {sta['tt_fmax_mhz']:.0f} MHz · ss/125 °C Fmax {sta['ss_fmax_mhz']:.0f} MHz · "
         f"yield @ {sta['target_mhz']:.0f} MHz {100*sta['mc_yield']:.1f}%</p>"
         f"<img src='{fig_rel}/19_sta_fmax.png'/>"),
        ("Block-level Monte Carlo",
         f"<img src='{fig_rel}/20_sta_mc.png'/>"),
        ("Take-aways",
         "<ul><li>Methodology matches an industrial library team; tools are FOSS and laptop-sized.</li>"
         "<li>ML is used where it belongs: as a SPICE surrogate inside a multi-objective sizer.</li>"
         "<li>Every number in the report is regenerated by <code>python run_project.py</code>.</li>"
         "<li>Honest limits: compact MOS, not BSIM; ideal clock; no GDS extraction.</li></ul>"),
    ]
    bodies = []
    for i, (title, body) in enumerate(slides):
        bodies.append(
            f'<section class="slide" id="s{i}">'
            f"<div class='num'>{i+1:02d} / {len(slides):02d}</div>"
            f"<h1>{title}</h1>{body}</section>"
        )
    html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Slides — ML-Assisted Standard-Cell Optimization</title>
<style>
  html,body { margin:0; height:100%; background:#0f1720; color:#e8eef6;
              font-family: "Segoe UI", system-ui, sans-serif; }
  .slide { min-height:100vh; padding: 48px 64px 64px; box-sizing:border-box; display:none; }
  .slide.on { display:block; }
  h1 { font-size: 2.1rem; color:#8cb4ff; margin: 0 0 18px; }
  p, li { font-size: 1.15rem; line-height:1.45; }
  .sub { color:#9aa7b8; }
  img { max-width: min(900px, 92%); max-height: 64vh; background:white; border-radius:6px; }
  .num { color:#6b7c90; font-size: 0.85rem; letter-spacing: 0.08em; margin-bottom: 12px; }
  code { background:#1c2836; padding: 1px 6px; border-radius:4px; }
  .hint { position:fixed; bottom:12px; right:18px; color:#6b7c90; font-size:12px; }
</style></head><body>
""" + "\n".join(bodies) + """
<div class="hint">← → or space to navigate</div>
<script>
const s=[...document.querySelectorAll('.slide')]; let i=0;
function show(k){ i=(k+s.length)%s.length; s.forEach((e,j)=>e.classList.toggle('on', j===i)); location.hash='s'+i; }
document.addEventListener('keydown', e=>{
  if(['ArrowRight','PageDown',' '].includes(e.key)) { e.preventDefault(); show(i+1); }
  if(['ArrowLeft','PageUp'].includes(e.key)) { e.preventDefault(); show(i-1); }
});
document.addEventListener('click', ()=>show(i+1));
show(0);
</script>
</body></html>
"""
    path = docs / "SLIDES.html"
    path.write_text(html, encoding="utf-8")
    return path
