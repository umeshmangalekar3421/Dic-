"""
Statistical timing analysis under process variability.
======================================================

Per evaluation the flow:

1. builds the load (Cext) of every net from the trial's drive strengths and
   routed wire capacitance,
2. runs a longest-path (max-arrival) dynamic programme on the gate DAG and
   back-traces the critical path for every timing sink,
3. samples K chips.  Each chip gets correlated global variation (Vth, gate
   W/L, metal RC) plus uncorrelated local device variation,
4. computes every path delay from the compact-MOSFET drive factor  S,
5. reports timing yield, worst slack and per-chip Vmin.

Everything is vectorised with NumPy: K=200 Monte-Carlo chips evaluate in a
fraction of a second, which is what makes the AI search affordable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .compact import VTH0_N, mobility_scale, v_eff
from .design import Netlist
from .library import LIBRARY, cin_of, leakage_of
from .pd import BUF_DRIVE, LAYER_DATA, PhysResult, Trial

T_SPEC = 211.0            # ps, target cycle time (~4.7 GHz)
VDD_NOM = 0.80            # V, nominal supply
F_TARGET = 1.0 / (T_SPEC * 1e-12)   # Hz (from T_SPEC)
LEAK_TAU = 12.4e-3        # V, leakage sensitivity to Vth (mV-class)
LEAK_T_EA = 60.0          # K, activated-temperature scale factor


def freq_ghz() -> float:
    """Target clock frequency in GHz, derived from T_SPEC (ps)."""
    return 1e3 / T_SPEC


def freq_mhz() -> float:
    """Target clock frequency in MHz, derived from T_SPEC (ps)."""
    return 1e6 / T_SPEC
ACTIVITY = 0.12           # switching activity factor
PO_LOAD_FF = 0.30         # load capacitance of a primary output (fF)
EXP_VEFF = 1.4            # velocity-saturation-aware overdrive exponent

# variability model (28nm-class magnitudes: chip-level implant/CD/global
# threshold plus device-level random variation)
SIG_GW = 0.028            # global gate-width (CD + implant) variation
SIG_GL = 0.012            # global gate-length variation
SIG_GVT = 0.0030          # global Vth shift (V)
SIG_LW = 0.040            # local width variation per device
SIG_LL = 0.025            # local length variation per device
SIG_LVT = 0.0040          # local Vth per device (V)
SIG_WIRE = 0.020          # global metal RC variation

VDD_SCAN = np.round(np.arange(0.55, 0.96, 0.05), 2)


# ---------------------------------------------------------------------------
@dataclass
class EvalResult:
    trial: Trial
    yield_nom: float
    worst_slack_nom: float          # deterministic nominal
    mean_worst_slack: float
    std_worst_slack: float
    mean_path_delay: float          # ps, nominal, across critical paths
    vmin_mean: float
    vmin_min: float
    vmin_fail_frac: float
    cell_area: float
    wire_area: float
    die_area: float
    p_dyn: float                    # mW
    p_leak: float                   # mW
    p_total: float                  # mW
    drc: int
    drc_detail: Dict[str, int]
    paths: List[Tuple[str, float, float]] = field(default_factory=list)
    # path: (sink name, nominal delay ps, nominal slack ps)
    util_by_layer: Dict[int, float] = field(default_factory=dict)
    wire_len_by_layer: Dict[int, float] = field(default_factory=dict)
    slack_samples: Optional[np.ndarray] = None   # per-chip worst slack (K,)
    vmin_samples: Optional[np.ndarray] = None    # per-chip Vmin (K,)


# ---------------------------------------------------------------------------
def _ratio_factor(ratio: float) -> float:
    """Effective strength of the gate as a function of Wp/Wn ratio.

    Nominal ratio 1.0 -> 1.0;  ratio > 1 reinforces the slow (p) rail.
    Harmonic-mean shaped so that derating and boosting are symmetric.
    """
    r = float(ratio)
    return 2.0 * r / (1.0 + r)


def _nominal_drive_array(nl: Netlist, trial: Trial) -> np.ndarray:
    """Per-combinational-instance nominal drive (W scaling only)."""
    return np.array(
        [trial.drives.get(inst.cell, 1.0)
         for inst in nl.instances if not inst.is_dff]
    )


def _build_cext(nl: Netlist, phys: PhysResult,
                trial: Trial) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Load capacitance seen by each net's driver.

    Returns (cext, wire_term) where wire_term[n] is the distributed
    Elmore term 0.5 * r * l^2 * c  (ps, at nominal metal).
    """
    cext: Dict[str, float] = {}
    wire_term: Dict[str, float] = {}
    for net, L in phys.net_len.items():
        lay = phys.net_layer[net]
        r = LAYER_DATA[lay]["r"]
        c = LAYER_DATA[lay]["c"]
        nbuf = phys.buffered.get(net, 0)
        l_seg = L / (nbuf + 1)
        # load capacitance at the far end of the net
        loads = 0.0
        for li in nl.net_loads[net]:
            inst = nl.instances[li]
            if inst.is_dff:
                loads += LIBRARY["DFF"].cin
            else:
                loads += cin_of(LIBRARY[inst.cell], trial.drives.get(inst.cell, 1.0))
        if net in nl.primary_outputs:
            loads += PO_LOAD_FF
        if nbuf > 0:
            cbuf = cin_of(LIBRARY["BUF"], BUF_DRIVE)
            cext[net] = cbuf + 0.5 * c * l_seg
            wire_term[net] = (nbuf + 1) * 0.5 * r * l_seg * l_seg * c
        else:
            cext[net] = loads + 0.5 * c * L
            wire_term[net] = 0.5 * r * L * L * c
        # far-end load used by the last buffer stage
        if nbuf > 0:
            wire_term[net + "#last"] = loads + 0.5 * c * l_seg
    return cext, wire_term


@dataclass
class PathInfo:
    """A critical path: ordered timing stages + distributed wire term."""
    sink: str
    stages: List[Tuple[int, float]]      # (slot idx, k = A + B*Cext)
    wire: float                          # ps
    setup: float                         # ps


def _extract_paths(nl: Netlist, phys: PhysResult, trial: Trial,
                   cext: Dict[str, float],
                   wire_term: Dict[str, float]
                   ) -> Tuple[List[PathInfo], int]:
    """
    Longest-path DP + back-trace for every timing sink.

    Returns (paths, nbuf_virtual).  Slot indices: 0..M-1 map to combinatorial
    instances; higher slots are virtual buffer transistors.
    """
    comb = [i for i in nl.instances if not i.is_dff]
    m = len(comb)
    order = nl.order()

    drive = _nominal_drive_array(nl, trial)
    rf = _ratio_factor(trial.ratio)

    # virtual buffer slots per buffered net
    buf_slots: Dict[str, List[int]] = {}
    next_slot = m
    for net, nbuf in phys.buffered.items():
        slots = []
        for _ in range(nbuf):
            slots.append(next_slot)
            next_slot += 1
        buf_slots[net] = slots

    A_arr = np.array([LIBRARY[i.cell].a for i in comb])
    B_arr = np.array([LIBRARY[i.cell].b for i in comb])
    A_buf = LIBRARY["BUF"].a
    B_buf = LIBRARY["BUF"].b
    cext_buf_in = cin_of(LIBRARY["BUF"], BUF_DRIVE)

    # stage delay (nominal) for a gate outputting net n
    def gate_stage(inst: int, n_out: str) -> float:
        return (A_arr[inst] + B_arr[inst] * cext[n_out]) / (drive[inst] * rf)

    # full net-transfer delay (nominal) for driver of net n
    net_delay: Dict[str, float] = {}
    for net in nl.net_driver:
        d = nl.net_driver[net]
        nbuf = phys.buffered.get(net, 0)
        if d < 0:
            net_delay[net] = wire_term[net]
            continue
        td = gate_stage(d, net)
        if nbuf > 0:
            l_seg = phys.net_len[net] / (nbuf + 1)
            lay = phys.net_layer[net]
            c = LAYER_DATA[lay]["c"]
            cext_last = wire_term[net + "#last"]
            for j, sl in enumerate(buf_slots[net]):
                if j < nbuf - 1:
                    ce = cext_buf_in + 0.5 * c * l_seg
                else:
                    ce = cext_last
                td += (A_buf + B_buf * ce) / (BUF_DRIVE * rf)
            td += 0.0  # distributed term added in 'wire'
        net_delay[net] = td

    # arrival times at the far end of each net
    arr: Dict[str, float] = {}
    for n in nl.primary_inputs:
        arr[n] = 0.0
    for n in nl.dff_q:
        arr.setdefault(n, 0.0)
    for i in order:
        inst = nl.instances[i]
        if inst.is_dff:
            continue
        a = max(arr[n] for n in inst.in_nets)
        arr[inst.out_net] = a + net_delay[inst.out_net]

    # back-trace each sink
    paths: List[PathInfo] = []
    sinks = list(nl.dff_d) + [n for n in nl.primary_outputs]
    for sink in sinks:
        setup = 22.0 if sink in nl.dff_d else 0.0
        stages: List[Tuple[int, float]] = []
        wire = 0.0
        cur = sink
        guard = 0
        while True:
            guard += 1
            if guard > 400:
                raise RuntimeError("path back-trace did not terminate")
            d = nl.net_driver[cur]
            if d < 0:
                break  # reached a source
            wire += wire_term[cur]
            nbuf = phys.buffered.get(cur, 0)
            if nbuf > 0:
                l_seg = phys.net_len[cur] / (nbuf + 1)
                lay = phys.net_layer[cur]
                c = LAYER_DATA[lay]["c"]
                cext_last = wire_term[cur + "#last"]
                for j, sl in enumerate(buf_slots[cur]):
                    if j < nbuf - 1:
                        ce = cext_buf_in + 0.5 * c * l_seg
                    else:
                        ce = cext_last
                    stages.append((sl, A_buf + B_buf * ce))
            stages.append((d, A_arr[d] + B_arr[d] * cext[cur]))
            # pick the input that achieved the max arrival
            best = None
            for n in nl.instances[d].in_nets:
                if best is None or arr[n] > arr[best]:
                    best = n
            cur = best
        stages.reverse()
        paths.append(PathInfo(sink=sink, stages=stages, wire=wire, setup=setup))
    return paths, next_slot


def _delay_matrix(S: np.ndarray, paths: List[PathInfo]) -> np.ndarray:
    """
    Per-path gate-delay sum for K Monte-Carlo samples.
    S : (K, M_total) drive factors.
    Returns (K, P) array.
    """
    P = len(paths)
    Smax = max((len(p.stages) for p in paths), default=0)
    if Smax == 0:
        return np.zeros((S.shape[0], P))
    k = np.zeros((P, Smax))
    idx = np.zeros((P, Smax), dtype=int)
    for p, path in enumerate(paths):
        for s, (slot, kk) in enumerate(path.stages):
            k[p, s] = kk
            idx[p, s] = slot
    K = S.shape[0]
    delay = np.zeros((K, P))
    for s in range(Smax):
        kk = k[:, s]
        if not np.any(kk > 0.0):
            continue
        Ssel = S[:, idx[:, s]]
        delay += kk[None, :] / Ssel
    return delay


def evaluate(nl: Netlist, trial: Trial, K: int = 160, seed: int = 42,
             vdd: float = VDD_NOM, T: float = 300.0,
             do_vmin: bool = True) -> EvalResult:
    """Full statistical evaluation of one trial configuration."""
    phys = place_and_route_cached(nl, trial)

    cext, wire_term = _build_cext(nl, phys, trial)
    paths, n_slots = _extract_paths(nl, phys, trial, cext, wire_term)

    comb = [i for i in nl.instances if not i.is_dff]
    drive = _nominal_drive_array(nl, trial)
    rf = _ratio_factor(trial.ratio)
    M = len(comb)

    # per-slot base drive (buffers are virtual slots with BUF_DRIVE)
    base = np.zeros(n_slots)
    base[:M] = drive
    base[M:] = BUF_DRIVE

    # ---- nominal (deterministic) delays ---------------------------------
    S_nom = base * rf
    d_nom = np.array(
        [sum(kk / S_nom[sl] for sl, kk in p.stages) + p.wire for p in paths]
    )
    slack_nom = T_SPEC - d_nom - np.array([p.setup for p in paths])
    worst_slack_nom = float(np.min(slack_nom))
    mean_path_delay = float(np.mean(d_nom))

    # ---- Monte-Carlo ------------------------------------------------------
    rng = np.random.default_rng(seed)
    G = rng.normal(1.0, SIG_GW, K) / rng.normal(1.0, SIG_GL, K)
    gvt = rng.normal(0.0, SIG_GVT, K)
    wsc = rng.normal(1.0, SIG_WIRE, K)
    dw = rng.normal(0.0, SIG_LW, (K, n_slots))
    dl = rng.normal(0.0, SIG_LL, (K, n_slots))
    dvt = rng.normal(0.0, SIG_LVT, (K, n_slots))

    muT = mobility_scale(T)
    veff0 = v_eff(VDD_NOM, VTH0_N)

    def sample_S(Vdd: float) -> np.ndarray:
        veff = np.maximum(Vdd - (VTH0_N + gvt[:, None] + dvt), 0.22 * Vdd)
        return (base[None, :] * muT * rf * G[:, None]
                * (1.0 + dw) / (1.0 + dl) * (veff / veff0) ** EXP_VEFF)

    S = sample_S(vdd)
    delays = _delay_matrix(S, paths)
    wire_delay = wsc[:, None] * np.array([p.wire for p in paths])[None, :]
    total = delays + wire_delay
    slack = T_SPEC - total - np.array([p.setup for p in paths])[None, :]
    worst = np.min(slack, axis=1)
    yield_nom = float(np.mean(worst >= 0.0))

    # ---- per-chip Vmin ----------------------------------------------------
    # NaN means "does not meet timing even at the top of the scan range".
    vmin = np.full(K, np.nan)
    if do_vmin:
        for v in VDD_SCAN:
            Sv = sample_S(v)
            dv = _delay_matrix(Sv, paths) + wsc[:, None] * np.array(
                [p.wire for p in paths])[None, :]
            sv = T_SPEC - dv - np.array([p.setup for p in paths])[None, :]
            worst_v = np.min(sv, axis=1)
            still_bad = np.isnan(vmin) & (worst_v >= 0.0)
            vmin[still_bad] = v
    found = ~np.isnan(vmin)
    vmin_mean = float(vmin[found].mean()) if found.any() else float("nan")
    vmin_min = float(vmin[found].min()) if found.any() else float("nan")

    # ---- power -------------------------------------------------------------
    c_gates = 0.0
    for inst in nl.instances:
        c_gates += cin_of(LIBRARY[inst.cell], trial.drives.get(inst.cell, 1.0))
    c_wire = 0.0
    for net, L in phys.net_len.items():
        c_wire += LAYER_DATA[phys.net_layer[net]]["c"] * L
    c_tot = c_gates + c_wire
    p_dyn = 0.5 * c_tot * 1e-15 * vdd ** 2 * F_TARGET * ACTIVITY * 1e3  # mW

    # mean leakage over the global-Vth distribution (exact Gaussian moment)
    mean_vt_factor = np.exp(SIG_GVT ** 2 / (2.0 * LEAK_TAU ** 2))
    temp_factor = np.exp((T - 300.0) / 60.0)
    i_leak = 0.0
    for inst in nl.instances:
        i_leak += leakage_of(LIBRARY[inst.cell],
                             trial.drives.get(inst.cell, 1.0), trial.ratio)
    p_leak = vdd * i_leak * 1e-9 * mean_vt_factor * temp_factor * 1e3  # mW

    paths_out = []
    for p in paths:
        d = float(sum(kk / S_nom[sl] for sl, kk in p.stages) + p.wire)
        paths_out.append((p.sink, d, float(T_SPEC - d - p.setup)))

    return EvalResult(
        trial=trial,
        yield_nom=yield_nom,
        worst_slack_nom=worst_slack_nom,
        mean_worst_slack=float(np.mean(worst)),
        std_worst_slack=float(np.std(worst)),
        mean_path_delay=mean_path_delay,
        vmin_mean=vmin_mean if do_vmin else float("nan"),
        vmin_min=vmin_min if do_vmin else float("nan"),
        vmin_fail_frac=float(np.mean(np.isnan(vmin))) if do_vmin else float("nan"),
        cell_area=phys.cell_area,
        wire_area=phys.wire_area,
        die_area=phys.die_area,
        p_dyn=float(p_dyn),
        p_leak=float(p_leak),
        p_total=float(p_dyn + p_leak),
        drc=phys.drc,
        drc_detail=dict(phys.drc_detail),
        paths=paths_out,
        util_by_layer=dict(phys.util_by_layer),
        wire_len_by_layer=dict(phys.wire_len_by_layer),
        slack_samples=worst,
        vmin_samples=vmin if do_vmin else None,
    )


# ---------------------------------------------------------------------------
# physical-design cache (placement depends only on the trial)
# ---------------------------------------------------------------------------
_phys_cache: Dict[int, PhysResult] = {}


def place_and_route_cached(nl: Netlist, trial: Trial) -> PhysResult:
    from .pd import place_and_route
    key = hash((
        tuple(sorted(trial.drives.items())), trial.ratio, trial.nbuf,
        trial.layer_short, trial.layer_mid, trial.layer_long, trial.density,
    ))
    if key not in _phys_cache:
        _phys_cache[key] = place_and_route(nl, trial)
    return _phys_cache[key]


def clear_cache() -> None:
    _phys_cache.clear()


def evaluate_corners(nl: Netlist, trial: Trial) -> Dict[str, float]:
    """Deterministic worst slack at a set of PVT corners (no local variation)."""
    corners = [
        ("TT 0.80V 25C", 0.80, 300.0, 0.0),
        ("FF 0.85V 25C", 0.85, 300.0, 0.0),
        ("SS 0.75V 25C", 0.75, 300.0, 0.0),
        ("TT 0.80V 125C", 0.80, 373.0, 0.0),
        ("TT 0.80V -40C", 0.80, 233.0, 0.0),
    ]
    phys = place_and_route_cached(nl, trial)
    cext, wire_term = _build_cext(nl, phys, trial)
    paths, n_slots = _extract_paths(nl, phys, trial, cext, wire_term)
    base = _nominal_drive_array(nl, trial)
    base = np.concatenate([base, np.full(n_slots - len(base), BUF_DRIVE)])
    rf = _ratio_factor(trial.ratio)
    out = {}
    for name, vdd, T, shift in corners:
        muT = mobility_scale(T)
        vth = VTH0_N + shift + (T - 300.0) * (-50e-6)
        veff = max(vdd - abs(vth), 0.22 * vdd)
        veff0 = max(VDD_NOM - VTH0_N, 0.22 * VDD_NOM)
        S = base * rf * muT * (veff / veff0) ** EXP_VEFF
        worst = np.inf
        for p in paths:
            d = sum(kk / S[sl] for sl, kk in p.stages) + p.wire
            worst = min(worst, T_SPEC - d - p.setup)
        out[name] = float(worst)
    return out
