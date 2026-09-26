"""Design-of-experiments characterization dataset.

A Latin-hypercube over transistor sizes, L, VDD, temperature, load and
input slew is crossed with cell type and process corner.  Each row is
one SPICE-class characterization point (here evaluated by the compact
model, which in an industrial flow would be ngspice / Liberate).
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd
from scipy.stats import qmc

from dic_mlopt import config as C
from dic_mlopt.physics.cells import CELLS
from dic_mlopt.physics.characterize import CellCharacterizer, monte_carlo_cell


def _lhs(n: int, d: int, seed: int) -> np.ndarray:
    sampler = qmc.LatinHypercube(d=d, seed=seed)
    return sampler.random(n)


def generate_dataset(n_samples: int, seed: int = C.RNG_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    char = CellCharacterizer()
    names = list(C.CELL_NAMES)
    corners = list(C.CORNERS.keys())

    u = _lhs(n_samples, 7, seed)
    wn = C.WMIN_UM + u[:, 0] * (C.WMAX_UM - C.WMIN_UM)
    # Keep PMOS/NMOS ratio in a physical band 0.8 .. 4.0
    ratio = 0.80 + u[:, 1] * (4.0 - 0.80)
    wp = np.clip(wn * ratio, C.WMIN_UM, C.WMAX_UM)
    l_um = C.LMIN_UM + u[:, 2] * (C.LMAX_UM - C.LMIN_UM)
    vdd = C.VDD_MIN + u[:, 3] * (C.VDD_MAX - C.VDD_MIN)
    temp_c = -40.0 + u[:, 4] * (165.0)
    cload = C.CLOAD_FF_MIN + u[:, 5] * (C.CLOAD_FF_MAX - C.CLOAD_FF_MIN)
    slew = C.SLEW_PS_MIN + u[:, 6] * (C.SLEW_PS_MAX - C.SLEW_PS_MIN)

    cell_idx = rng.integers(0, len(names), size=n_samples)
    # Bias corners: 55 % tt, 22.5 % ss, 22.5 % ff
    corner_draw = rng.random(n_samples)
    corner_idx = np.where(corner_draw < 0.55, 1, np.where(corner_draw < 0.775, 0, 2))
    corner_names = np.array(corners)

    rows = []
    # Evaluate in batches per cell to keep the topology constant
    for ci, cname in enumerate(names):
        m = cell_idx == ci
        if not np.any(m):
            continue
        cell = CELLS[cname]
        for cj, cnr in enumerate(corners):
            mm = m & (corner_idx == cj)
            if not np.any(mm):
                continue
            r = char.characterize(
                cell,
                wn=wn[mm], wp=wp[mm], l_um=l_um[mm],
                vdd=vdd[mm], temp_c=temp_c[mm],
                cload_ff=cload[mm], slew_ps=slew[mm],
                corner=cnr,
            )
            df = pd.DataFrame({
                "cell": cname,
                "corner": cnr,
                "wn_um": wn[mm],
                "wp_um": wp[mm],
                "wp_wn": wp[mm] / wn[mm],
                "l_um": l_um[mm],
                "vdd": vdd[mm],
                "temp_c": temp_c[mm],
                "cload_ff": cload[mm],
                "slew_ps": slew[mm],
                "n_series_n": cell.n_series_n,
                "n_series_p": cell.n_series_p,
                "n_nmos": cell.n_nmos,
                "n_pmos": cell.n_pmos,
                "logical_effort": cell.logical_effort,
                "is_seq": int(cell.is_sequential),
                "delay_ps": np.asarray(r.delay_ps),
                "delay_rise_ps": np.asarray(r.delay_rise_ps),
                "delay_fall_ps": np.asarray(r.delay_fall_ps),
                "slew_out_ps": np.asarray(r.slew_out_ps),
                "e_dyn_fj": np.asarray(r.e_dyn_fj),
                "p_leak_nw": np.asarray(r.p_leak_nw),
                "area_um2": np.asarray(r.area_um2),
                "vm_v": np.asarray(r.vm_v),
                "cin_ff": np.asarray(r.cin_ff),
                "t_setup_ps": np.asarray(r.t_setup_ps),
                "t_cq_ps": np.asarray(r.t_cq_ps),
            })
            rows.append(df)
    out = pd.concat(rows, ignore_index=True)
    # Drop non-physical rows (numerical blow-ups)
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    out = out[(out["delay_ps"] > 1.0) & (out["delay_ps"] < 5000.0)]
    out = out[(out["p_leak_nw"] > 0) & (out["e_dyn_fj"] > 0)]
    return out.reset_index(drop=True)


def generate_yield_table(
    n_designs: int,
    n_mc: int,
    seed: int = C.RNG_SEED + 7,
) -> pd.DataFrame:
    """For random sizings, run Monte Carlo and record empirical yield."""
    rng = np.random.default_rng(seed)
    char = CellCharacterizer()
    names = list(C.COMBINATIONAL)
    recs = []
    for i in range(n_designs):
        cname = names[i % len(names)]
        cell = CELLS[cname]
        wn = float(rng.uniform(C.WMIN_UM, 3.5))
        ratio = float(rng.uniform(1.2, 3.2))
        wp = float(np.clip(wn * ratio, C.WMIN_UM, C.WMAX_UM))
        l_um = C.LMIN_UM
        vdd = C.VDD_NOM
        temp = 85.0
        cload = 8.0
        slew = 40.0
        corner = "ss"
        mc = monte_carlo_cell(
            char, cell, wn, wp, l_um, vdd, temp, cload, slew, corner, n_mc, rng
        )
        dspec = C.CELL_DELAY_SPEC_PS[cname]
        lspec = C.CELL_LEAK_SPEC_NW[cname]
        y = float(np.mean((mc["delay_ps"] < dspec) & (mc["p_leak_nw"] < lspec)))
        recs.append({
            "cell": cname,
            "wn_um": wn,
            "wp_um": wp,
            "l_um": l_um,
            "delay_mean_ps": float(mc["delay_ps"].mean()),
            "delay_std_ps": float(mc["delay_ps"].std()),
            "leak_mean_nw": float(mc["p_leak_nw"].mean()),
            "leak_std_nw": float(mc["p_leak_nw"].std()),
            "yield": y,
            "n_mc": n_mc,
        })
    return pd.DataFrame(recs)


def reference_points(char: CellCharacterizer | None = None) -> pd.DataFrame:
    """A small table of textbook-style reference characterizations."""
    char = char or CellCharacterizer()
    recs = []
    for name, cell in CELLS.items():
        wn = C.WMIN_UM * cell.n_series_n
        wp = C.WMIN_UM * 2.0 * cell.n_series_p
        for corner in C.CORNERS:
            for temp in (25.0, 125.0):
                for vdd in (1.62, 1.80):
                    r = char.characterize(
                        cell, wn, wp, C.LMIN_UM, vdd, temp,
                        cload_ff=8.0, slew_ps=30.0, corner=corner,
                    )
                    recs.append({
                        "cell": name, "corner": corner, "temp_c": temp, "vdd": vdd,
                        "wn_um": wn, "wp_um": wp,
                        "delay_ps": float(np.mean(r.delay_ps)),
                        "p_leak_nw": float(np.mean(r.p_leak_nw)),
                        "e_dyn_fj": float(np.mean(r.e_dyn_fj)),
                        "area_um2": float(np.mean(r.area_um2)),
                    })
    return pd.DataFrame(recs)
