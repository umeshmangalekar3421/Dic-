#!/usr/bin/env python3
"""
verify_real_backends.py — prove the real EDA tools are being used.
=================================================================

Run this on a machine that has the tools installed:

    python3 scripts/verify_real_backends.py

For each tool it does a genuine end-to-end exercise (not just `which`), then
prints a table. Nothing here is required for FabAware-Opt to run — the project
falls back to its own models — this script exists so you can *see* which
numbers came from a real tool and which came from the fallback.

    python3 scripts/verify_real_backends.py --liberty sky130.lib   # real PDK
    python3 scripts/verify_real_backends.py --quick                # skip slow steps
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, MISS, WARN = "  OK  ", "  --  ", "  ??  "


def _run(cmd, cwd=None, timeout=600):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, "command not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def check_yosys(work):
    """Synthesize rtl/fab32.v with real Yosys."""
    from fabaware.backends import tools
    exe = tools.find("yosys")
    if not exe:
        return None, "yosys not on PATH"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = ("read_verilog rtl/fab32.v; "
              "synth -top fab32 -noabc; stat")
    rc, out = _run([exe, "-p", script], cwd=root)
    if rc != 0:
        return False, out.strip().splitlines()[-1][:90]
    n = 0
    for line in out.splitlines():
        line = line.strip()
        if line.endswith("cells") and line.split()[0].isdigit():
            n = int(line.split()[0])
    return True, f"{n} generic cells synthesized from rtl/fab32.v"


def check_netlist_import(work, liberty=None):
    """Run the project's real Yosys import path end to end."""
    try:
        from fabaware.backends.yosys import build_from_verilog
        nl = build_from_verilog(liberty=liberty)
        st = nl.stats()
        return True, (f"{st['gates']} gates, {st['dffs']} flops, "
                      f"{st['transistors']} transistors imported")
    except Exception as exc:
        return None, str(exc).splitlines()[-1][:120]


def check_ngspice(work):
    """Run a real BSIM transistor simulation and fit the Vdd exponent."""
    from fabaware.backends import tools, ngspice
    exe = tools.find("ngspice")
    if not exe:
        return None, "ngspice not on PATH"
    try:
        iv = ngspice.measure_iv(48.0, 22.0, vds=0.80, pmos=False)
        ion = iv[-1][1] if iv else float("nan")
        ileak = ngspice.measure_leakage(48.0, 22.0, vdd=0.80, pmos=False)
        return True, (f"Ion {ion*1e6:.1f} uA/um, Ioff {ileak*1e9:.2f} nA/um "
                      f"(measured, level-49 BSIM)")
    except Exception as exc:
        return False, str(exc).splitlines()[-1][:120]


def check_spice_calibration(work):
    """Full compact-model calibration from SPICE."""
    try:
        from fabaware.backends import ngspice
        cal = ngspice.calibrate()
        return True, "calibration: " + ", ".join(
            f"{k}={v:.4g}" for k, v in list(cal.items())[:4])
    except Exception as exc:
        return None, str(exc).splitlines()[-1][:120]


def check_opensta(work, liberty=None):
    """Time a real netlist with OpenSTA."""
    from fabaware.backends import tools
    exe = tools.find("opensta")
    if not exe:
        return None, "OpenSTA (sta) not on PATH"
    try:
        from fabaware.design import build_fab32
        from fabaware.optimizer import BASELINE_TRIAL
        from fabaware.backends import crosscheck
        nl = build_fab32()
        rep = crosscheck.run_sta_crosscheck(
            nl, BASELINE_TRIAL, BASELINE_TRIAL, 211.0, work,
            liberty_path=liberty)
        r = rep["results"]["baseline"]
        if r.get("worst_slack_ps") is None:
            return False, r.get("error", "no slack reported")[:90]
        return True, (f"worst slack {r['worst_slack_ps']:+.1f} ps, "
                      f"{r.get('endpoints')} endpoints timed")
    except Exception as exc:
        return False, str(exc).splitlines()[-1][:120]


def check_pdk(work, pdk_root=None):
    """Locate a real PDK and report how many of our cells it can supply."""
    try:
        from fabaware.backends import pdk as pdk_mod
        obj = pdk_mod.find_pdk("sky130", root=pdk_root)
        if obj is None:
            return None, ("sky130 not found - install with: "
                          "pip install volare && volare enable --pdk sky130 <ver>")
        if not obj.ok:
            return False, f"found {obj.root} but lib/LEF incomplete"
        cm = pdk_mod.CellMap(obj)
        return True, (f"{len(cm.available)} cells in .lib, {len(cm.map)} mapped"
                      + (f", missing {len(cm.unmapped)}" if cm.unmapped else ""))
    except Exception as exc:
        return False, str(exc).splitlines()[-1][:100]


def check_openroad(work, pdk_root=None):
    """Run real place & route if a PDK is available."""
    from fabaware.backends import tools
    exe = tools.find("openroad")
    if not exe:
        return None, "openroad not on PATH"
    try:
        from fabaware.backends import pdk as pdk_mod, crosscheck as cc
        from fabaware.design import build_fab32
        from fabaware.optimizer import BASELINE_TRIAL
        obj = pdk_mod.find_pdk("sky130", root=pdk_root)
        if obj is None or not obj.ok:
            return None, "installed, but no PDK to route with"
        rep = cc.run_pnr_crosscheck(
            build_fab32(), BASELINE_TRIAL, BASELINE_TRIAL,
            211.0, work, obj)
        r = rep["results"]["baseline"]
        if not r.get("ok"):
            return False, (r.get("error") or "run failed")[:80]
        return True, (f"routed: area {r.get('area_um2')} um2, "
                      f"DRC {r.get('drc_count')}, wire {r.get('wirelength_um')} um")
    except Exception as exc:
        return False, str(exc).splitlines()[-1][:100]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--liberty", default=None,
                    help="real .lib to use instead of the generated virtual PDK")
    ap.add_argument("--quick", action="store_true",
                    help="skip the slower calibration steps")
    ap.add_argument("--work", default="build/verify", help="scratch directory")
    ap.add_argument("--pdk-root", default=None,
                    help="explicit path to an installed PDK")
    args = ap.parse_args(argv)

    work = args.work
    os.makedirs(work, exist_ok=True)

    print()
    print("=" * 78)
    print("  FabAware-Opt — real EDA tool verification")
    print("=" * 78)

    from fabaware.backends import tools
    print()
    print(tools.summary())

    checks = [
        ("Yosys  · synthesize rtl/fab32.v",
         lambda: check_yosys(work)),
        ("Yosys  · import netlist into the engine",
         lambda: check_netlist_import(work, args.liberty)),
        ("ngspice · measure a BSIM transistor",
         lambda: check_ngspice(work)),
    ]
    if not args.quick:
        checks.append(("ngspice · calibrate the compact model",
                       lambda: check_spice_calibration(work)))
    checks += [
        ("OpenSTA · time the gate-level netlist",
         lambda: check_opensta(work, args.liberty)),
        ("SKY130  · locate the PDK and map cells",
         lambda: check_pdk(work, args.pdk_root)),
        ("OpenROAD · place & route for real",
         lambda: check_openroad(work, args.pdk_root)),
    ]

    print()
    print("  end-to-end checks")
    print("  " + "-" * 74)
    n_ok = 0
    for label, fn in checks:
        t0 = time.time()
        try:
            state, msg = fn()
        except Exception as exc:                      # never let one check kill the run
            state, msg = False, f"{type(exc).__name__}: {exc}"
        dt = time.time() - t0
        mark = OK if state else (MISS if state is None else WARN)
        if state:
            n_ok += 1
        print(f"  {mark} {label:<42} {dt:5.1f}s  {msg}")
    print("  " + "-" * 74)
    print(f"  {n_ok}/{len(checks)} real tools exercised successfully")
    print()
    print("  Nothing above is required: FabAware-Opt falls back to its own")
    print("  models for whatever is missing, and the console always says which")
    print("  backend produced which number.")
    print()
    print("  Install guide: docs/REAL_TOOLS.md     Installer: scripts/install_real_tools.sh")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
