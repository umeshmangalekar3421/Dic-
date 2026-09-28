"""
Command-line entry points for FabAware-Opt.

Installed scripts
-----------------
fabaware-run   full flow: build design → baseline → AI optimize → report
fabaware-demo  quick terminal demonstration of the stress test
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from .design import build_fab32
from .library import RESIZABLE_TYPES
from . import sta
from . import optimizer
from . import report as report_mod


def _banner() -> None:
    print("=" * 78)
    print("  FabAware-Opt  —  Fabrication-aware standard-cell & physical-design")
    print("                   optimization for improved ASIC timing yield")
    print("=" * 78)


def _print_config(tag: str, t, r) -> None:
    print(f"\n  {tag}")
    print("    " + "-" * 70)
    d = "  ".join(f"{c}:{t.drives.get(c,1.0):.0f}x" for c in RESIZABLE_TYPES)
    print(f"    drives   {d}")
    print(f"    Wp/Wn {t.ratio:.2f}   buffers {t.nbuf}   "
          f"metal M{t.layer_short}/M{t.layer_mid}/M{t.layer_long}   "
          f"density {t.density:.2f}")
    print(f"    yield {100*r.yield_nom:6.1f}%   worst slack {r.worst_slack_nom:+8.1f} ps   "
          f"area {r.cell_area:7.1f} um2")
    print(f"    power {r.p_total:6.3f} mW   DRC {r.drc:3d}   "
          f"Vmin {r.vmin_mean*1000:5.0f} mV")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="fabaware-run",
        description="Run the full FabAware-Opt flow and generate the report.",
    )
    ap.add_argument("-K", "--chips", type=int, default=160,
                    help="Monte-Carlo chips per evaluation (default 160)")
    ap.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    ap.add_argument("--doe", type=int, default=8,
                    help="initial design-of-experiments size (default 8)")
    ap.add_argument("--iter", dest="n_iter", type=int, default=20,
                    help="GP expected-improvement iterations (default 20)")
    ap.add_argument("--budget", type=float, default=180.0,
                    help="optimization time budget in seconds (default 180)")
    ap.add_argument("-o", "--out", default="reports",
                    help="output directory (default reports)")
    ap.add_argument("--real", action="store_true",
                    help="synthesize the RTL with the real Yosys tool "
                         "instead of the built-in Python netlist")
    ap.add_argument("--liberty", default=None,
                    help="optional .lib file: map onto a real cell library "
                         "with Yosys+ABC instead of the virtual 28nm library")
    ap.add_argument("--no-calibrate", action="store_true",
                    help="keep the default clock period instead of "
                         "auto-calibrating it to the loaded netlist")
    ap.add_argument("--quiet", action="store_true", help="suppress progress output")
    args = ap.parse_args(argv)

    _banner()
    t_all = time.time()

    from .backends import tools as _tools
    print("\n" + _tools.summary())

    print("\n[1/4] Building the design netlist ...")
    if args.real:
        from .backends.yosys import build_from_verilog
        try:
            nl = build_from_verilog(liberty=args.liberty)
            print("      source: rtl/fab32.v synthesized by REAL Yosys")
        except Exception as exc:
            print(f"      Yosys unavailable ({exc}); "
                  f"falling back to the Python netlist")
            nl = build_fab32()
    else:
        nl = build_fab32()
        print("      source: built-in Python netlist "
              "(pass --real to synthesize with Yosys)")

    if not args.no_calibrate:
        period, y0 = sta.calibrate_target(nl, target_yield=0.35, K=args.chips,
                                          seed=args.seed)
        print(f"      calibrated clock period {period:.0f} ps "
              f"({sta.freq_ghz():.2f} GHz) -> baseline yield {100*y0:.1f}%")

    st = nl.stats()
    print(f"      {st['gates']} gates, {st['dffs']} flip-flops, {st['nets']} nets,")
    print("      %d transistors, %d timing endpoints" % (
        st["transistors"], len(nl.dff_d) + len(nl.primary_outputs)))
    print("      cell mix: " + "  ".join(f"{k}={v}" for k, v in sorted(st["by_type"].items())))

    print("\n[2/4] Baseline evaluation (%d Monte-Carlo chips) ..." % args.chips)
    base_trial = optimizer.BASELINE_TRIAL
    base_r = sta.evaluate(nl, base_trial, K=args.chips, seed=args.seed)
    _print_config("BASELINE", base_trial, base_r)

    print("\n[3/4] AI optimization (GP surrogate + expected improvement) ...")
    t0 = time.time()
    opt = optimizer.optimize(
        nl, K=args.chips, seed=args.seed, n_doe=args.doe, n_iter=args.n_iter,
        time_budget=args.budget,
        progress=None if args.quiet else (lambda m: print("    " + m)),
    )
    t_opt = time.time() - t0
    _print_config("AI-OPTIMIZED", opt.trial, opt.result)
    print(f"\n    {opt.n_evals} statistical-timing evaluations in {t_opt:.1f} s")

    print("\n[4/4] Generating report ...")
    paths = report_mod.build_report(
        nl, base_trial, base_r, opt, out_dir=args.out,
        K=args.chips, runtime_s=time.time() - t_all,
    )

    yb, yo = base_r.yield_nom, opt.result.yield_nom
    print(f"\n      HTML report : {os.path.abspath(paths['html'])}")
    print(f"      JSON results: {os.path.abspath(paths['json'])}")

    print("\n" + "=" * 78)
    print(f"  RESULT   timing yield  {100*yb:5.1f}%  →  {100*yo:5.1f}%   "
          f"({100*(yo-yb):+.1f} pp)")
    print(f"           worst slack   {base_r.worst_slack_nom:+6.1f}  →  "
          f"{opt.result.worst_slack_nom:+6.1f} ps")
    print(f"           area / power  {base_r.cell_area:.0f}→{opt.result.cell_area:.0f} um2"
          f"   {base_r.p_total:.3f}→{opt.result.p_total:.3f} mW")
    print(f"           DRC          {base_r.drc} → {opt.result.drc}")
    print(f"           total runtime {time.time()-t_all:.1f} s")
    print("=" * 78)
    return 0


def demo(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="fabaware-demo",
        description="Terminal demonstration of the manufacturing-variation stress test.")
    ap.add_argument("-K", "--chips", type=int, default=400,
                    help="Monte-Carlo chips (default 400)")
    args = ap.parse_args(argv)

    _banner()
    nl = build_fab32()
    st = nl.stats()
    print(f"\nDesign: FAB-32  ({st['gates']} gates, {st['dffs']} flops, "
          f"{st['transistors']} transistors)")
    print(f"Target: {sta.T_SPEC:.0f} ps period  ({sta.freq_ghz():.2f} GHz) "
          f"at {sta.VDD_NOM:.2f} V, 25 C")

    base = optimizer.BASELINE_TRIAL
    rb = sta.evaluate(nl, base, K=args.chips, seed=7)
    print("\n(1) NORMAL standard-cell configuration")
    print(f"    worst slack {rb.worst_slack_nom:+.1f} ps   area {rb.cell_area:.0f} um2   "
          f"power {rb.p_total:.3f} mW   DRC {rb.drc}")

    print(f"\n(2) MANUFACTURING-VARIATION STRESS TEST  ({args.chips} chips)")
    print(f"    timing yield            {100*rb.yield_nom:6.1f} %")
    print(f"    worst-slack mean/sigma  {rb.mean_worst_slack:+.1f} / "
          f"{rb.std_worst_slack:.2f} ps")
    print(f"    mean Vmin               {rb.vmin_mean*1000:.0f} mV "
          f"(nominal {sta.VDD_NOM*1000:.0f} mV)")
    print(f"    -> {100*(1-rb.yield_nom):.1f} % of chips would fail timing")

    print("\n(3) AI-OPTIMIZED configuration (searching ...)")
    opt = optimizer.optimize(nl, K=160, seed=42, n_doe=8, n_iter=16,
                             time_budget=90, progress=None)
    t = opt.trial
    print("    drives: " + "  ".join(f"{c}:{t.drives.get(c,1.0):.0f}x"
                                      for c in RESIZABLE_TYPES))
    print(f"    Wp/Wn {t.ratio:.2f}  buffers {t.nbuf}  "
          f"metal M{t.layer_short}/M{t.layer_mid}/M{t.layer_long}  "
          f"density {t.density:.2f}")
    ro_full = sta.evaluate(nl, t, K=args.chips, seed=7)

    print("\n(4) COMPARISON")
    hdr = f"    {'metric':<26}{'baseline':>12}{'optimized':>12}{'change':>12}"
    print(hdr)
    print("    " + "-" * 62)
    rows = [
        ("cell area (um2)", rb.cell_area, ro_full.cell_area,
         lambda a, b: f"{100*(b-a)/a:+.1f}%"),
        ("total power (mW)", rb.p_total, ro_full.p_total,
         lambda a, b: f"{100*(b-a)/a:+.1f}%"),
        ("mean path delay (ps)", rb.mean_path_delay, ro_full.mean_path_delay,
         lambda a, b: f"{b-a:+.1f}"),
        ("timing yield (%)", 100 * rb.yield_nom, 100 * ro_full.yield_nom,
         lambda a, b: f"{b-a:+.1f} pp"),
        ("DRC violations", float(rb.drc), float(ro_full.drc),
         lambda a, b: f"{int(b-a):+d}"),
        ("worst slack nom (ps)", rb.worst_slack_nom, ro_full.worst_slack_nom,
         lambda a, b: f"{b-a:+.1f}"),
        ("mean Vmin (mV)", rb.vmin_mean * 1000, ro_full.vmin_mean * 1000,
         lambda a, b: f"{b-a:+.0f}"),
    ]
    for name, a, b, fmt in rows:
        print(f"    {name:<26}{a:>12.2f}{b:>12.2f}{fmt(a, b):>12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
