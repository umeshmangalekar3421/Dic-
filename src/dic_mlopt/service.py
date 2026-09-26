"""Public product API used by the CLI and the CellForge lab server.

These functions are the stable surface a recruiter / intern can import:

    from dic_mlopt.service import characterize_point, fo4_ps, sweep
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from dic_mlopt import config as C
from dic_mlopt import __version__
from dic_mlopt.physics.cells import CELLS
from dic_mlopt.physics.characterize import CellCharacterizer
from dic_mlopt.physics.mosfet import nmos, pmos, calibrate_drive
from dic_mlopt.physics.sanity import run_sanity


@lru_cache(maxsize=1)
def _char() -> CellCharacterizer:
    return CellCharacterizer()


def _f(x) -> float:
    return float(np.mean(np.asarray(x, dtype=float)))


def characterize_point(
    cell: str = "INV",
    wn_um: float = 0.84,
    wp_um: float = 1.68,
    l_um: float = C.LMIN_UM,
    vdd: float = C.VDD_NOM,
    temp_c: float = 25.0,
    cload_ff: float = 8.0,
    slew_ps: float = 30.0,
    corner: str = "tt",
) -> dict:
    """Single-point characterization.  This is the Liberate-class query."""
    if cell not in CELLS:
        raise KeyError(f"unknown cell {cell}; choose from {list(CELLS)}")
    if corner not in C.CORNERS:
        raise KeyError(f"unknown corner {corner}; choose from {list(C.CORNERS)}")
    wn_um = float(np.clip(wn_um, 0.20, C.WMAX_UM))
    wp_um = float(np.clip(wp_um, 0.20, C.WMAX_UM))
    vdd = float(np.clip(vdd, 1.20, 2.20))
    temp_c = float(np.clip(temp_c, -55.0, 150.0))
    r = _char().characterize(
        CELLS[cell], wn_um, wp_um, l_um, vdd, temp_c, cload_ff, slew_ps, corner
    )
    delay = _f(r.delay_ps)
    leak = _f(r.p_leak_nw)
    dspec = C.CELL_DELAY_SPEC_PS[cell]
    lspec = C.CELL_LEAK_SPEC_NW[cell]
    # First-order Pelgrom yield at this point
    from dic_mlopt.physics.mosfet import nmos as _n, pmos as _p
    from scipy.stats import norm

    sig = np.sqrt(_n.sigma_vt(wn_um, l_um) ** 2 + _p.sigma_vt(wp_um, l_um) ** 2)
    vov = max(vdd - 0.5, 0.35)
    sd_d = max(delay * 0.65 * sig / vov * 4.0, 0.3)
    sd_l = max(leak * 0.55, 1e-6)
    yld = float(norm.cdf((dspec - delay) / sd_d) * norm.cdf((lspec - leak) / sd_l))
    topo = CELLS[cell]
    return {
        "cell": cell,
        "description": topo.description,
        "corner": corner,
        "wn_um": wn_um,
        "wp_um": wp_um,
        "wp_wn": wp_um / wn_um,
        "l_um": l_um,
        "vdd": vdd,
        "temp_c": temp_c,
        "cload_ff": cload_ff,
        "slew_ps": slew_ps,
        "delay_ps": delay,
        "delay_rise_ps": _f(r.delay_rise_ps),
        "delay_fall_ps": _f(r.delay_fall_ps),
        "slew_out_ps": _f(r.slew_out_ps),
        "e_dyn_fj": _f(r.e_dyn_fj),
        "p_leak_nw": leak,
        "area_um2": _f(r.area_um2),
        "vm_v": _f(r.vm_v),
        "cin_ff": _f(r.cin_ff),
        "t_setup_ps": _f(r.t_setup_ps),
        "t_hold_ps": _f(r.t_hold_ps),
        "t_cq_ps": _f(r.t_cq_ps),
        "logical_effort": topo.logical_effort,
        "n_nmos": topo.n_nmos,
        "n_pmos": topo.n_pmos,
        "is_sequential": topo.is_sequential,
        "yield_est": yld,
        "delay_spec_ps": dspec,
        "leak_spec_nw": lspec,
        "fo4_ratio": delay / max(_char().fo4_ps(vdd=vdd, temp_c=temp_c, corner=corner), 1e-9),
    }


def fo4_ps(vdd: float = C.VDD_NOM, temp_c: float = 25.0, corner: str = "tt") -> float:
    return float(_char().fo4_ps(vdd=vdd, temp_c=temp_c, corner=corner))


def sweep(
    cell: str = "INV",
    axis: str = "vdd",
    wn_um: float = 0.84,
    wp_um: float = 1.68,
    corner: str = "tt",
    n: int = 32,
    **fixed,
) -> dict:
    """Sweep one axis, return arrays for plotting."""
    grids = {
        "vdd": np.linspace(1.44, 1.98, n),
        "temp_c": np.linspace(-40.0, 125.0, n),
        "wn_um": np.linspace(C.WMIN_UM, 4.0, n),
        "cload_ff": np.linspace(1.0, 32.0, n),
        "slew_ps": np.linspace(10.0, 200.0, n),
    }
    if axis not in grids:
        raise KeyError(f"axis must be one of {list(grids)}")
    xs = grids[axis]
    delays, leaks, energies = [], [], []
    base = dict(cell=cell, wn_um=wn_um, wp_um=wp_um, corner=corner, **fixed)
    for x in xs:
        base[axis] = float(x)
        if axis == "wn_um" and "wp_um" not in fixed:
            # keep ratio 2 if sweeping width
            base["wp_um"] = float(x) * (wp_um / wn_um)
        r = characterize_point(**base)
        delays.append(r["delay_ps"])
        leaks.append(r["p_leak_nw"])
        energies.append(r["e_dyn_fj"])
    return {
        "axis": axis,
        "x": xs.tolist(),
        "delay_ps": delays,
        "p_leak_nw": leaks,
        "e_dyn_fj": energies,
        "cell": cell,
        "corner": corner,
    }


def iv_curves(device: str = "nmos", temp_c: float = 25.0, w_um: float = 1.0) -> dict:
    mos = nmos if device == "nmos" else pmos
    vds = np.linspace(0.0, 1.8, 60)
    curves = []
    for vgs in (0.6, 0.9, 1.2, 1.5, 1.8):
        ids = mos.ids(vgs, vds, w_um, C.LMIN_UM, temp_c) * 1e3  # mA
        curves.append({"vgs": vgs, "vds": vds.tolist(), "ids_mA": ids.tolist()})
    return {"device": mos.name, "temp_c": temp_c, "w_um": w_um, "curves": curves}


def subthreshold(device: str = "nmos", w_um: float = 1.0) -> dict:
    mos = nmos if device == "nmos" else pmos
    vgs = np.linspace(0.0, 1.8, 80)
    series = []
    for temp in (-40.0, 25.0, 85.0, 125.0):
        ids = np.maximum(mos.ids(vgs, 1.8, w_um, C.LMIN_UM, temp), 1e-16)
        series.append({"temp_c": temp, "vgs": vgs.tolist(), "ids_A": ids.tolist()})
    return {"device": mos.name, "series": series}


def load_metrics() -> dict:
    path = C.RESULTS_DIR / "metrics.json"
    if not path.exists():
        return {"available": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["available"] = True
    return data


def load_library() -> List[dict]:
    path = C.RESULTS_DIR / "library_signoff.csv"
    if not path.exists():
        return []
    return pd.read_csv(path).to_dict(orient="records")


def load_sta() -> List[dict]:
    path = C.STA_DIR / "adder_sta.csv"
    if not path.exists():
        return []
    return pd.read_csv(path).to_dict(orient="records")


def product_manifest() -> dict:
    ion = calibrate_drive()
    try:
        sanity = {
            "fo4_ps": fo4_ps(),
            "fo4_ss": fo4_ps(vdd=1.62, temp_c=125.0, corner="ss"),
            "fo4_ff": fo4_ps(vdd=1.98, temp_c=-40.0, corner="ff"),
        }
    except Exception:
        sanity = {}
    metrics = load_metrics()
    return {
        "name": "CellForge",
        "version": __version__,
        "tagline": "PVT-robust standard-cell characterization, ML sizing, Liberty and STA.",
        "cells": list(C.CELL_NAMES),
        "corners": list(C.CORNERS),
        "vdd_nom": C.VDD_NOM,
        "lmin_um": C.LMIN_UM,
        "wmin_um": C.WMIN_UM,
        "cell_height_um": C.CELL_HEIGHT_UM,
        "ion": ion,
        "sanity": sanity,
        "metrics_loaded": bool(metrics.get("available")),
        "industry_analogue": {
            "characterization": "Cadence Liberate / Synopsys SiliconSmart",
            "variation": "Monte Carlo + Pelgrom mismatch + ss/tt/ff",
            "surrogate": "internal ML delay models used by library teams",
            "sizing": "multi-objective sizer (NSGA-II)",
            "delivery": "NLDM Liberty",
            "signoff": "STA (PrimeTime / OpenSTA class)",
        },
    }


def industry_map() -> dict:
    return {
        "roles": [
            {
                "title": "Standard-cell / library characterization intern",
                "companies": "Intel, Qualcomm, Broadcom, Samsung Foundry, TSMC partners, Cadence",
                "you_can_talk_about": "NLDM tables, PVT corners, FO4, Cin, leakage vectors, Liberty syntax",
            },
            {
                "title": "STA / timing intern",
                "companies": "NVIDIA, AMD, Apple silicon teams, Google Silicon, NXP, TI",
                "you_can_talk_about": "setup check, WNS, Fmax, t_cq + combo + t_su, slow-corner sign-off, yield vs period",
            },
            {
                "title": "CAD / EDA software intern",
                "companies": "Synopsys, Cadence, Siemens EDA, Ansys",
                "you_can_talk_about": "replacing SPICE inside an optimizer with a surrogate, DOE, Liberty writers",
            },
            {
                "title": "ML for silicon / DTCO intern",
                "companies": "NVIDIA, Intel, Qualcomm AI/CAD, research labs",
                "you_can_talk_about": "HistGB vs Ridge, permutation importance, yield as an objective, physics sign-off of ML knees",
            },
        ],
        "flow_map": [
            {"step": "Device model", "industry": "BSIM6 / BSIM-CMG under NDA", "here": "Sakurai α-power + subthreshold, pinned to SKY130 Ion/Ioff/FO4"},
            {"step": "Characterization", "industry": "Liberate / SiliconSmart + FineSim", "here": "Vectorized compact-model DOE (Latin hypercube)"},
            {"step": "Variation", "industry": "Global corners + mismatch MC", "here": "ss/tt/ff + Pelgrom σVt = AVt/√(WL)"},
            {"step": "Surrogate", "industry": "Internal GBDT delay models", "here": "HistGB, R² = 0.96 on held-out delay"},
            {"step": "Sizing", "industry": "SOCE / in-house MCO", "here": "NSGA-II, delay / energy / 1−yield"},
            {"step": "Delivery", "industry": ".lib + .lef + .gds", "here": "NLDM .lib (tt/ss/ff) — LEF/GDS intentionally out of scope"},
            {"step": "Sign-off", "industry": "PrimeTime / Tempus", "here": "Python STA of a registered 8-bit RCA + block MC yield"},
        ],
        "honest_limits": [
            "Compact MOS, not a foundry BSIM card — order-of-magnitude SKY130, not sign-off accuracy.",
            "No layout extraction (no SPEF, no LEF/GDS). Clock is ideal.",
            "DFF setup/hold is scaled from FO1, not a metastability search.",
            "That is the same abstraction a library intern learns in week one, before they get PDK access.",
        ],
        "sky130_correlation": [
            {"metric": "Drawn Lmin", "cellforge": "0.15 µm", "sky130": "0.15 µm (nfet_01v8)", "status": "match"},
            {"metric": "VDD nom", "cellforge": "1.80 V", "sky130": "1.80 V", "status": "match"},
            {"metric": "HD row height", "cellforge": "2.72 µm", "sky130": "2.72 µm (fd_sc_hd)", "status": "match"},
            {"metric": "Site width", "cellforge": "0.46 µm", "sky130": "0.46 µm", "status": "match"},
            {"metric": "FO4 inverter", "cellforge": "45 ps tt/1.8 V/25 °C", "sky130": "≈ 30–60 ps (published-order 130 nm)", "status": "in-band"},
            {"metric": "Ion NMOS", "cellforge": "520 µA/µm", "sky130": "≈ 500–600 µA/µm class", "status": "in-band"},
            {"metric": "Ion PMOS", "cellforge": "245 µA/µm", "sky130": "≈ 220–280 µA/µm class", "status": "in-band"},
        ],
    }
