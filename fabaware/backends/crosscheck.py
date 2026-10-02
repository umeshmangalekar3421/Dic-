"""
Cross-check FabAware-Opt's engine against the real EDA tools.
=============================================================

The optimizer's inner loop runs thousands of Monte-Carlo evaluations, so it
has to use the fast analytic model — calling a SPICE or STA engine that many
times is not tractable. But a single **cross-check** at the end is cheap, and
it is the difference between "our arithmetic says the yield improved" and
"OpenSTA, an independent timing engine, says the design got faster".

This module therefore:

* writes the **baseline** and **AI-optimized** configurations out as ordinary
  gate-level Verilog netlists,
* generates a Liberty timing library for each (unless a real PDK is supplied),
* runs **OpenSTA** on both against the calibrated clock period, and
* optionally calibrates the compact model from **ngspice** measurements.

Everything degrades politely: if a tool is missing the step is reported as
skipped and the run still succeeds.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from ..design import Netlist
from ..pd import Trial
from . import liberty as liberty_mod
from . import emit as emit_mod
from . import opensta as opensta_mod
from . import ngspice as ngspice_mod
from . import tools

REPORTS = ("timing", "power", "area")


def _one_config(nl: Netlist, trial: Trial, tag: str, period_ps: float,
                out_dir: str, liberty_path: Optional[str],
                ratio: float) -> Dict[str, object]:
    """Emit + time a single configuration, returning what OpenSTA said."""
    v = os.path.join(out_dir, f"fab32_{tag}.v")
    emit_mod.write_netlist(nl, trial, v)

    if liberty_path:
        lib = liberty_path
        generated = False
    else:
        # the Wp/Wn ratio scales every cell, so each config gets its own lib
        lib = os.path.join(out_dir, f"fabaware_28nm_{tag}.lib")
        liberty_mod.write_liberty(lib, ratio=trial.ratio)
        generated = True

    workdir = os.path.join(out_dir, f"sta_{tag}")
    entry: Dict[str, object] = {
        "netlist": v, "liberty": lib, "liberty_generated": generated}
    try:
        res = opensta_mod.run_sta(
            netlist=v, liberty=[lib], top="fab32",
            period_ps=period_ps, clock_net="clk",
            workdir=workdir, reports=REPORTS)
    except Exception as exc:                      # tool missing or failed
        entry.update(ok=False, error=str(exc).strip().splitlines()[-1:][0]
                     if str(exc).strip() else "",
                     worst_slack_ps=None, endpoints=None,
                     area=None, power_mw=None)
        return entry

    entry.update(ok=True,
                 worst_slack_ps=res.worst_slack_ps,
                 endpoints=res.endpoints,
                 area=res.area_um2,
                 power_mw=res.power_mW)
    return entry


def run_sta_crosscheck(
    nl: Netlist,
    base_trial: Trial,
    opt_trial: Trial,
    period_ps: float,
    out_dir: str,
    liberty_path: Optional[str] = None,
) -> Dict[str, object]:
    """Time the baseline and optimized netlists with OpenSTA."""
    os.makedirs(out_dir, exist_ok=True)
    result: Dict[str, object] = {
        "backend": "opensta",
        "path": tools.find("opensta"),
        "period_ps": period_ps,
        "using_real_pdk": bool(liberty_path),
    }
    results = {
        "baseline": _one_config(nl, base_trial, "baseline", period_ps,
                                out_dir, liberty_path, base_trial.ratio),
        "optimized": _one_config(nl, opt_trial, "optimized", period_ps,
                                 out_dir, liberty_path, opt_trial.ratio),
    }
    result["results"] = results

    b = results["baseline"].get("worst_slack_ps")
    o = results["optimized"].get("worst_slack_ps")
    if b is None or o is None:
        result["slack_improvement_ps"] = None
        result["verdict"] = "OpenSTA did not report a worst slack"
    else:
        result["slack_improvement_ps"] = o - b
        result["verdict"] = (
            "OpenSTA independently confirms the optimization improved timing"
            if o > b else
            "OpenSTA does NOT confirm an improvement - investigate")
    return result


def run_pnr_crosscheck(
    nl: Netlist,
    base_trial: Trial,
    opt_trial: Trial,
    period_ps: float,
    out_dir: str,
    pdk_obj,
    density: float = 0.70,
) -> Dict[str, object]:
    """
    Place & route both configurations for real with OpenROAD.

    This is the layer where the measurements matter most: wire length and DRC
    count stop being predictions of our model and become facts about an
    actual routed layout.
    """
    from . import openroad as or_mod
    from . import pdk as pdk_mod

    os.makedirs(out_dir, exist_ok=True)
    cellmap = pdk_mod.CellMap(pdk_obj)

    result: Dict[str, object] = {
        "backend": "openroad",
        "path": tools.find("openroad"),
        "pdk": pdk_obj.name,
        "pdk_root": pdk_obj.root,
        "cellmap": cellmap.report(),
    }

    out: Dict[str, Dict[str, object]] = {}
    for tag, trial in (("baseline", base_trial), ("optimized", opt_trial)):
        work = os.path.join(out_dir, f"pnr_{tag}")
        os.makedirs(work, exist_ok=True)
        v = os.path.join(work, f"fab32_{tag}.v")
        sdc = os.path.join(work, f"fab32_{tag}.sdc")
        emit_mod.write_netlist(nl, trial, v, cellmap=cellmap)
        or_mod.write_sdc(sdc, period_ps)
        entry: Dict[str, object] = {"netlist": v}
        try:
            r = or_mod.run_pnr(
                netlist=v, liberty=[pdk_obj.corner_lib], lefs=pdk_obj.lefs,
                sdc=sdc, top="fab32", out_dir=work, density=density)
        except Exception as exc:
            entry.update(ok=False, error=str(exc).strip().splitlines()[-1:][0]
                         if str(exc).strip() else "")
            out[tag] = entry
            continue
        entry.update(ok=r.ok, area_um2=r.area_um2, drc=r.drc_count,
                     wirelength_um=r.wirelength_um,
                     worst_slack_ps=r.worst_slack_ps,
                     def_path=r.def_path, error=r.error)
        out[tag] = entry

    result["results"] = out
    b, o = out["baseline"], out["optimized"]
    if b.get("drc_count") is not None and o.get("drc_count") is not None:
        result["drc_delta"] = o["drc_count"] - b["drc_count"]
        result["verdict"] = (
            f"OpenROAD routed both: DRC {b['drc_count']} -> {o['drc_count']}")
    else:
        result["drc_delta"] = None
        result["verdict"] = "OpenROAD did not report a DRC count"
    return result


def run_spice_calibration(vdd: float = 0.80,
                          temp_c: float = 25.0) -> Dict[str, object]:
    """Calibrate the compact model from real ngspice measurements."""
    if not tools.find("ngspice"):
        return {"backend": "ngspice", "available": False,
                "reason": "ngspice not on PATH"}
    try:
        cal = ngspice_mod.calibrate(vdd=vdd, temp_c=temp_c)
    except Exception as exc:
        return {"backend": "ngspice", "available": False, "error": str(exc)}
    return {"backend": "ngspice", "available": True, "calibration": cal}


def crosscheck(
    nl: Netlist,
    base_trial: Trial,
    opt_trial: Trial,
    period_ps: float,
    out_dir: str = "reports/crosscheck",
    liberty_path: Optional[str] = None,
    do_sta: bool = True,
    do_spice: bool = True,
    do_pnr: bool = True,
    pdk_obj=None,
    vdd: float = 0.80,
    temp_c: float = 25.0,
) -> Dict[str, object]:
    """Run whichever cross-checks are both requested and possible."""
    os.makedirs(out_dir, exist_ok=True)
    report: Dict[str, object] = {"out_dir": os.path.abspath(out_dir)}

    if do_sta:
        if tools.find("opensta"):
            report["sta"] = run_sta_crosscheck(
                nl, base_trial, opt_trial, period_ps, out_dir,
                liberty_path=liberty_path or (
                    pdk_obj.corner_lib if pdk_obj else None))
        else:
            report["sta"] = {"backend": "opensta", "available": False,
                             "reason": "OpenSTA not on PATH"}

    if do_pnr:
        if pdk_obj is None:
            report["pnr"] = {"backend": "openroad", "available": False,
                             "reason": "no PDK installed"}
        elif not tools.find("openroad"):
            report["pnr"] = {"backend": "openroad", "available": False,
                             "reason": "OpenROAD not on PATH"}
        else:
            report["pnr"] = run_pnr_crosscheck(
                nl, base_trial, opt_trial, period_ps, out_dir, pdk_obj)

    if do_spice:
        report["spice"] = run_spice_calibration(vdd=vdd, temp_c=temp_c)

    return report


def format_crosscheck(report: Dict[str, object]) -> str:
    """Human-readable summary for the console."""
    L = []
    w = L.append
    w("")
    w("  Tool cross-check")
    w("  " + "-" * 66)
    sta = report.get("sta")
    if not sta:
        w("  static timing : not requested")
    elif not sta.get("available", True):
        w(f"  static timing : SKIPPED ({sta.get('reason', 'unavailable')})")
        w("                  install OpenSTA to have the result verified")
        w("                  independently:  docs/REAL_TOOLS.md")
    else:
        w(f"  static timing : OpenSTA  [{sta.get('path')}]")
        w(f"    clock period: {sta.get('period_ps'):.1f} ps")
        for tag in ("baseline", "optimized"):
            r = sta["results"][tag]
            sl = r.get("worst_slack_ps")
            txt = "n/a" if sl is None else f"{sl:+.1f} ps"
            w(f"    {tag:<10}: worst slack {txt}"
              f"   ({r.get('endpoints') or 0} endpoints)")
            if not r.get("ok"):
                w(f"                ! {r.get('error', '')[:90]}")
        imp = sta.get("slack_improvement_ps")
        if imp is not None:
            w(f"    improvement : {imp:+.1f} ps")
            w(f"    verdict     : {sta.get('verdict')}")

    pnr = report.get("pnr")
    if pnr:
        if not pnr.get("available", True):
            w(f"  place & route : SKIPPED ({pnr.get('reason')})")
        else:
            w(f"  place & route : OpenROAD  [{pnr.get('path')}]")
            w(f"    PDK         : {pnr.get('pdk')} @ {pnr.get('pdk_root')}")
            for tag in ("baseline", "optimized"):
                r = pnr["results"][tag]
                if not r.get("ok"):
                    w(f"    {tag:<10}: FAILED  {r.get('error', '')[:60]}")
                    continue
                bits = []
                if r.get("area_um2") is not None:
                    bits.append(f"area {r['area_um2']:.0f} um2")
                if r.get("wirelength_um") is not None:
                    bits.append(f"wire {r['wirelength_um']:.0f} um")
                bits.append(f"DRC {r.get('drc_count')}")
                w(f"    {tag:<10}: " + "  ".join(bits))
            if pnr.get("drc_delta") is not None:
                w(f"    verdict     : {pnr.get('verdict')}")

    sp = report.get("spice")
    if sp:
        if not sp.get("available"):
            w(f"  spice         : SKIPPED ({sp.get('reason') or sp.get('error')})")
        else:
            w("  spice         : ngspice calibration applied")
            for k, v in (sp.get("calibration") or {}).items():
                w(f"    {k:<14}: {v}")
    w("  " + "-" * 66)
    return "\n".join(L)
