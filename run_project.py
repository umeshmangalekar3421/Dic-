#!/usr/bin/env python3
"""One-command Digital IC Design course project.

Usage (Windows)
    python -m venv .venv
    .venv\\Scripts\\pip install -r requirements.txt
    .venv\\Scripts\\python run_project.py

Usage (Linux / macOS)
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python run_project.py

Add --quick for a smaller DOE / shorter NSGA-II (demo in a couple of minutes).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from dic_mlopt import config as C  # noqa: E402
from dic_mlopt import __version__  # noqa: E402
from dic_mlopt.data.generate import generate_dataset, generate_yield_table, reference_points  # noqa: E402
from dic_mlopt.liberty.writer import write_liberty  # noqa: E402
from dic_mlopt.ml.train import load_models, predict_df, train_models  # noqa: E402
from dic_mlopt.opt.sizing import optimize_library  # noqa: E402
from dic_mlopt.physics.sanity import run_sanity  # noqa: E402
from dic_mlopt.report.build import write_report, write_slides  # noqa: E402
from dic_mlopt.sta.adder import monte_carlo_fmax, run_sta  # noqa: E402
from dic_mlopt.viz.plots import make_all_plots  # noqa: E402


def _j(x):
    if isinstance(x, dict):
        return {k: _j(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_j(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, Path):
        return str(x)
    return x


def banner():
    print("=" * 72)
    print("  CellForge  ·  PVT-robust standard-cell lab")
    print("  SKY130-calibrated  ·  characterization · ML sizing · Liberty · STA")
    print("=" * 72)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true", help="smaller DOE / fewer NSGA generations")
    args = p.parse_args(argv)
    t0 = time.time()
    banner()

    n_samples = C.N_SAMPLES_QUICK if args.quick else C.N_SAMPLES_FULL
    n_mc = C.N_MC_QUICK if args.quick else C.N_MC_FULL
    pop = C.NSGA_POP_QUICK if args.quick else C.NSGA_POP_FULL
    n_gen = C.NSGA_GEN_QUICK if args.quick else C.NSGA_GEN_FULL

    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    C.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    C.FIG_DIR.mkdir(parents=True, exist_ok=True)
    C.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    C.LIB_DIR.mkdir(parents=True, exist_ok=True)
    C.STA_DIR.mkdir(parents=True, exist_ok=True)
    C.DOCS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n[1/8] Physics sanity checks  (FO4 target {C.FO4_TARGET_PS:.1f} ps)")
    physics = run_sanity()
    print(f"      FO4 tt/1.8V/25C = {physics['fo4_ps']:.2f} ps")
    print(f"      FO4 ss/1.62V/125C = {physics['fo4_ss_hot_lowv_ps']:.2f} ps")
    print(f"      FO4 ff/1.98V/-40C = {physics['fo4_ff_cold_highv_ps']:.2f} ps")
    print(f"      Ion n/p = {physics['ion']['ion_n_uA_per_um']:.0f} / "
          f"{physics['ion']['ion_p_uA_per_um']:.0f} µA/µm")

    print(f"\n[2/8] Generating characterization dataset  (N = {n_samples})")
    df = generate_dataset(n_samples, seed=C.RNG_SEED)
    df.to_csv(C.DATA_DIR / "pvt_characterization.csv", index=False)
    ref = reference_points()
    ref.to_csv(C.DATA_DIR / "reference_corners.csv", index=False)
    ytab = generate_yield_table(n_designs=24 if args.quick else 40, n_mc=n_mc)
    ytab.to_csv(C.DATA_DIR / "yield_mc.csv", index=False)
    print(f"      rows = {len(df)}  cells = {sorted(df['cell'].unique().tolist())}")
    print(f"      delay ps  min/median/max = {df['delay_ps'].min():.1f} / "
          f"{df['delay_ps'].median():.1f} / {df['delay_ps'].max():.1f}")

    print("\n[3/8] Training surrogates  (Ridge / RF / HistGB)")
    ml_report = train_models(df, C.MODEL_DIR)
    dly = ml_report["targets"]["delay_ps"]["hgb"]["test"]
    print(f"      delay  HGB  R²={dly['r2']:.3f}  MAE={dly['mae']:.2f} ps  MAPE={dly['mape_pct']:.1f}%")
    print(f"      delay  Ridge R²={ml_report['targets']['delay_ps']['ridge']['test']['r2']:.3f}")
    print(f"      leak   HGB  R²={ml_report['targets']['p_leak_nw']['hgb']['test']['r2']:.3f}")

    print(f"\n[4/8] NSGA-II yield-aware sizing  (pop={pop}, gen={n_gen})")
    pack = load_models(C.MODEL_DIR / "surrogates.joblib")
    libopt = optimize_library(pack, pop=pop, n_gen=n_gen)
    signoff: pd.DataFrame = libopt["signoff"]
    signoff.to_csv(C.RESULTS_DIR / "library_signoff.csv", index=False)
    opt = signoff[signoff["sizing"] == "ml_opt"]
    print("      ML-opt cells:")
    for _, r in opt.iterrows():
        print(f"        {r['cell']:6s}  Wn={r['wn_um']:.2f}  Wp={r['wp_um']:.2f}  "
              f"tt={r['delay_tt_ps']:.1f}ps  wc={r['delay_wc_ps']:.1f}ps  "
              f"Y={100*r['yield']:.0f}%")

    sizing = {r["cell"]: {"wn_um": float(r["wn_um"]), "wp_um": float(r["wp_um"])}
              for _, r in opt.iterrows()}

    print("\n[5/8] Writing NLDM Liberty (tt, ss, ff)")
    libs = {}
    for corner, vdd, temp in (("tt", 1.80, 25.0), ("ss", 1.62, 125.0), ("ff", 1.98, -40.0)):
        path = C.LIB_DIR / f"dic_mlopt_sky130_{corner}.lib"
        write_liberty(sizing, path, corner=corner, vdd=vdd, temp_c=temp)
        libs[corner] = str(path)
        print(f"      {path.name}  ({path.stat().st_size} bytes)")

    print("\n[6/8] Static timing — registered 8-bit ripple-carry adder")
    sta_rows = []
    for label, corner, vdd, temp in (
        ("tt 1.8V 25C", "tt", 1.80, 25.0),
        ("tt 1.8V 125C", "tt", 1.80, 125.0),
        ("ss 1.62V 125C", "ss", 1.62, 125.0),
        ("ff 1.98V -40C", "ff", 1.98, -40.0),
    ):
        r = run_sta(sizing, corner=corner, vdd=vdd, temp_c=temp, period_ns=C.ADDER_PERIOD_NS)
        sta_rows.append({
            "corner_label": label, "corner": corner, "vdd": vdd, "temp_c": temp,
            "t_combo_ns": r.t_combo_ns, "t_cq_ns": r.t_cq_ns, "t_setup_ns": r.t_setup_ns,
            "wns_ns": r.wns_ns, "fmax_mhz": r.fmax_mhz, "n_gates": r.n_gates,
        })
        print(f"      {label:16s}  t_combo={r.t_combo_ns*1e3:.1f} ps  "
              f"Fmax={r.fmax_mhz:.0f} MHz  WNS@{1000/C.ADDER_PERIOD_NS:.0f}MHz={r.wns_ns:.3f} ns")
    sta_table = pd.DataFrame(sta_rows)
    sta_table.to_csv(C.STA_DIR / "adder_sta.csv", index=False)
    mc = monte_carlo_fmax(sizing, n=250 if not args.quick else 120, seed=C.RNG_SEED)
    np.save(C.STA_DIR / "fmax_mc.npy", mc["fmax_mhz"])
    print(f"      MC yield @ {1000/C.ADDER_PERIOD_NS:.0f} MHz = {100*mc['yield']:.1f}%   "
          f"Fmax P5/mean/P95 = {mc['fmax_p5']:.0f}/{mc['fmax_mean']:.0f}/{mc['fmax_p95']:.0f} MHz")
    print(f"      critical path: {' → '.join(mc['base']['critical_path'][:12])} …")

    print("\n[7/8] Figures")
    test = pd.read_csv(C.MODEL_DIR / "test.csv")
    yhat_d = predict_df(pack, test, "delay_ps", "hgb")
    yhat_l = predict_df(pack, test, "p_leak_nw", "hgb")
    make_all_plots(C.FIG_DIR, df, ml_report, libopt, test, yhat_d, yhat_l, sta_table, mc)
    nfig = len(list(C.FIG_DIR.glob("*.png")))
    print(f"      wrote {nfig} figures → {C.FIG_DIR}")

    print("\n[8/8] Report + slides")
    tt_row = sta_table[sta_table["corner_label"] == "tt 1.8V 25C"].iloc[0]
    ss_row = sta_table[sta_table["corner_label"] == "ss 1.62V 125C"].iloc[0]
    metrics = {
        "version": __version__,
        "date": str(date.today()),
        "mode": "quick" if args.quick else "full",
        "physics": physics,
        "dataset": {"n_rows": int(len(df)), "n_requested": n_samples},
        "ml": ml_report,
        "opt": {"pop": pop, "n_gen": n_gen},
        "library": {
            "opt_rows": opt.to_dict(orient="records"),
            "comparison": signoff.to_dict(orient="records"),
        },
        "liberty_files": libs,
        "sta": {
            "n_gates": int(tt_row["n_gates"]),
            "period_ns": C.ADDER_PERIOD_NS,
            "target_mhz": 1000.0 / C.ADDER_PERIOD_NS,
            "tt_fmax_mhz": float(tt_row["fmax_mhz"]),
            "tt_tcombo_ns": float(tt_row["t_combo_ns"]),
            "ss_fmax_mhz": float(ss_row["fmax_mhz"]),
            "ss_wns_ns": float(ss_row["wns_ns"]),
            "mc_yield": float(mc["yield"]),
            "mc_fmax_p5": float(mc["fmax_p5"]),
            "critical_path": mc["base"]["critical_path"],
            "cell_counts": mc["base"]["cell_counts"],
        },
        "runtime_s": time.time() - t0,
    }
    # drop huge importance already in ml_report
    (C.RESULTS_DIR / "metrics.json").write_text(
        json.dumps(_j(metrics), indent=2), encoding="utf-8"
    )
    rpt = write_report(metrics, C.DOCS_DIR)
    sld = write_slides(metrics, C.DOCS_DIR)
    print(f"      {rpt}")
    print(f"      {sld}")

    dt = time.time() - t0
    print("\n" + "=" * 72)
    print(f"  DONE in {dt:.1f} s")
    print(f"  Report : {rpt}")
    print(f"  Slides : {sld}")
    print(f"  Metrics: {C.RESULTS_DIR / 'metrics.json'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
