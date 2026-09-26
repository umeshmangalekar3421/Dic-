"""Yield-aware multi-objective transistor sizing using the ML surrogate.

Decision vector per cell: [wn_um, wp_um]
Objectives (all minimized):
  0. worst-corner delay  (ss, 125 C, 1.62 V, FO4-ish load)
  1. typical energy      (tt, 25 C, 1.8 V)
  2. 1 - yield           (MC at ss/85 C using Pelgrom + surrogate mean/sigma)

The surrogate is used for the inner loop (thousands of evaluations).
Pareto candidates are re-scored with the physics engine (the "SPICE sign-off").
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.stats import norm

from dic_mlopt import config as C
from dic_mlopt.ml.train import FEATURES, predict_df
from dic_mlopt.opt.nsga2 import nsga2
from dic_mlopt.physics.cells import CELLS
from dic_mlopt.physics.characterize import CellCharacterizer, monte_carlo_cell
from dic_mlopt.physics.mosfet import nmos, pmos


def _row(cell: str, wn, wp, l_um, vdd, temp, cload, slew, corner) -> pd.DataFrame:
    topo = CELLS[cell]
    return pd.DataFrame({
        "cell": [cell],
        "corner": [corner],
        "wn_um": [wn],
        "wp_um": [wp],
        "wp_wn": [wp / wn],
        "l_um": [l_um],
        "vdd": [vdd],
        "temp_c": [temp],
        "cload_ff": [cload],
        "slew_ps": [slew],
        "n_series_n": [topo.n_series_n],
        "n_series_p": [topo.n_series_p],
        "n_nmos": [topo.n_nmos],
        "n_pmos": [topo.n_pmos],
        "logical_effort": [topo.logical_effort],
        "is_seq": [int(topo.is_sequential)],
    })


def _surrogate_predict(pack, df, target):
    return float(predict_df(pack, df, target, model="hgb")[0])


def _yield_from_mu_sigma(mu_d, sd_d, mu_l, sd_l, dspec, lspec) -> float:
    sd_d = max(sd_d, 1e-6)
    sd_l = max(sd_l, 1e-9)
    y_d = float(norm.cdf((dspec - mu_d) / sd_d))
    y_l = float(norm.cdf((lspec - mu_l) / sd_l))
    return y_d * y_l


def optimize_cell(
    cell: str,
    pack,
    pop: int,
    n_gen: int,
    seed: int,
) -> dict:
    topo = CELLS[cell]
    dspec = C.CELL_DELAY_SPEC_PS[cell]
    lspec = C.CELL_LEAK_SPEC_NW[cell]
    l_um = C.LMIN_UM
    cload = 8.0
    slew = 35.0

    low = np.array([C.WMIN_UM, C.WMIN_UM])
    high = np.array([4.5, 6.5])

    def evaluate(x):
        wn, wp = float(x[0]), float(x[1])
        ratio = wp / wn
        viol = 0.0
        if ratio < 0.9:
            viol += (0.9 - ratio)
        if ratio > 4.0:
            viol += (ratio - 4.0)

        df_wc = _row(cell, wn, wp, l_um, 1.62, 125.0, cload, slew, "ss")
        df_tt = _row(cell, wn, wp, l_um, C.VDD_NOM, 25.0, cload, slew, "tt")
        d_wc = _surrogate_predict(pack, df_wc, "delay_ps")
        e_tt = _surrogate_predict(pack, df_tt, "e_dyn_fj")
        leak = _surrogate_predict(pack, df_wc, "p_leak_nw")
        area = _surrogate_predict(pack, df_tt, "area_um2")

        # Switching threshold via physics (cheap, keeps Vm reasonable)
        char = CellCharacterizer()
        vm = float(np.mean(char.switching_threshold(wn, wp, l_um, C.VDD_NOM, 25.0, "tt")))
        if vm < 0.30 * C.VDD_NOM:
            viol += (0.30 * C.VDD_NOM - vm) * 4
        if vm > 0.70 * C.VDD_NOM:
            viol += (vm - 0.70 * C.VDD_NOM) * 4

        # Mismatch-aware sigma from Pelgrom (delay sensitivity ~ dV / vov)
        sig_n = nmos.sigma_vt(wn, l_um)
        sig_p = pmos.sigma_vt(wp, l_um)
        vov = max(C.VDD_NOM - 0.5, 0.4)
        sd_d = d_wc * 0.65 * np.sqrt(sig_n ** 2 + sig_p ** 2) / vov * 4.0
        sd_l = leak * 0.55  # log-normal-ish leakage spread
        yld = _yield_from_mu_sigma(d_wc, sd_d, leak, sd_l, dspec, lspec)

        objs = np.array([d_wc, e_tt, 1.0 - yld], dtype=float)
        return objs, float(viol)

    res = nsga2(2, 3, low, high, evaluate, pop=pop, n_gen=n_gen, seed=seed)
    return res


def knee_point(F: np.ndarray) -> int:
    """Pick the Pareto point closest to the normalized ideal (0,0,...)."""
    fn = F.copy()
    span = fn.max(axis=0) - fn.min(axis=0)
    span[span < 1e-12] = 1.0
    fn = (fn - fn.min(axis=0)) / span
    d = np.linalg.norm(fn, axis=1)
    return int(np.argmin(d))


def _min_size(cell: str):
    topo = CELLS[cell]
    wn = C.WMIN_UM * max(topo.n_series_n, 1)
    wp = C.WMIN_UM * 2.0 * max(topo.n_series_p, 1)
    return wn, wp


def _balanced(cell: str):
    topo = CELLS[cell]
    wn = C.WMIN_UM * 2.0 * max(topo.n_series_n, 1)
    wp = C.WMIN_UM * 2.0 * 2.0 * max(topo.n_series_p, 1)
    return wn, wp


def _signoff_row(char, cell, wn, wp, pack=None) -> dict:
    topo = CELLS[cell]
    r_wc = char.characterize(topo, wn, wp, C.LMIN_UM, 1.62, 125.0, 8.0, 35.0, "ss")
    r_tt = char.characterize(topo, wn, wp, C.LMIN_UM, C.VDD_NOM, 25.0, 8.0, 35.0, "tt")
    rng = np.random.default_rng(C.RNG_SEED + 11)
    mc = monte_carlo_cell(char, topo, wn, wp, C.LMIN_UM, 1.62, 85.0, 8.0, 35.0, "ss", 220, rng)
    dspec = C.CELL_DELAY_SPEC_PS[cell]
    lspec = C.CELL_LEAK_SPEC_NW[cell]
    yld = float(np.mean((mc["delay_ps"] < dspec) & (mc["p_leak_nw"] < lspec)))
    return {
        "cell": cell,
        "wn_um": wn,
        "wp_um": wp,
        "wp_wn": wp / wn,
        "delay_wc_ps": float(np.mean(r_wc.delay_ps)),
        "delay_tt_ps": float(np.mean(r_tt.delay_ps)),
        "energy_tt_fj": float(np.mean(r_tt.e_dyn_fj)),
        "leak_wc_nw": float(np.mean(r_wc.p_leak_nw)),
        "area_um2": float(np.mean(r_tt.area_um2)),
        "vm_v": float(np.mean(r_tt.vm_v)),
        "yield": yld,
        "delay_mc_mean": float(mc["delay_ps"].mean()),
        "delay_mc_std": float(mc["delay_ps"].std()),
        "cin_ff": float(np.mean(r_tt.cin_ff)),
        "t_setup_ps": float(np.mean(r_tt.t_setup_ps)),
        "t_cq_ps": float(np.mean(r_tt.t_cq_ps)),
        "t_hold_ps": float(np.mean(r_tt.t_hold_ps)),
        "slew_out_ps": float(np.mean(r_tt.slew_out_ps)),
    }


def optimize_library(pack, pop: int, n_gen: int) -> dict:
    char = CellCharacterizer()
    cells: Dict[str, dict] = {}
    tables: List[pd.DataFrame] = []
    for i, name in enumerate(C.CELL_NAMES):
        res = optimize_cell(name, pack, pop=pop, n_gen=n_gen, seed=C.RNG_SEED + i)
        F = res["pareto_F"]
        X = res["pareto_X"]
        # keep feasible-ish
        k = knee_point(F)
        wn_o, wp_o = float(X[k, 0]), float(X[k, 1])
        wn_m, wp_m = _min_size(name)
        wn_b, wp_b = _balanced(name)
        recs = []
        for tag, wn, wp in (("min", wn_m, wp_m), ("balanced", wn_b, wp_b), ("ml_opt", wn_o, wp_o)):
            row = _signoff_row(char, name, wn, wp)
            row["sizing"] = tag
            recs.append(row)
        df = pd.DataFrame(recs)
        tables.append(df)
        cells[name] = {
            "pareto_F": F,
            "pareto_X": X,
            "knee": {"wn_um": wn_o, "wp_um": wp_o},
            "history": res["history"],
            "signoff": df.to_dict(orient="records"),
        }
    signoff = pd.concat(tables, ignore_index=True)
    return {"cells": cells, "signoff": signoff}
