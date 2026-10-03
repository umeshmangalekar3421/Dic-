"""
Physical design: placement, routing, wiring metrics and DRC.
============================================================

A deterministic, analytic physical-design model (the class of models used in
placement/routing estimators inside real EDA tools):

* row-based standard-cell placement (core area fixed by target density)
* Manhattan wire-length estimation with layer-dependent detour and
  congestion
* layer-class assignment (short / mid / long nets)
* buffer insertion on long wires
* a simplified rule deck producing a DRC violation count
* cell / wire / die area accounting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

import numpy as np

from .design import Netlist
from .library import LIBRARY, area_of

# ---------------------------------------------------------------------------
# metal layer data: R (ohm/um), C (fF/um), width (um), capacity (um per um^2)
# ---------------------------------------------------------------------------
LAYER_DATA = {
    5: {"r": 0.15, "c": 0.14, "w": 0.15, "cap": 5.0, "detour": 1.00},
    6: {"r": 0.09, "c": 0.17, "w": 0.25, "cap": 3.5, "detour": 1.10},
    7: {"r": 0.055, "c": 0.20, "w": 0.40, "cap": 2.5, "detour": 1.22},
}

ROW_PITCH = 3.0      # um
CELL_HEIGHT = 2.2    # um
ASPECT = 1.18        # die_w / die_h
PERIPHERY = 0.12     # extra die area fraction
BUF_DRIVE = 2.0      # drive strength of inserted buffers
BUF_WIDTH = 1.6      # um, footprint of an inserted buffer


@dataclass
class Trial:
    """One candidate configuration (the AI decision variables)."""
    drives: Dict[str, float]                 # cell type -> drive (1/2/4)
    ratio: float = 1.0                       # Wp/Wn sizing ratio
    nbuf: int = 0                            # buffers on long wires
    layer_short: int = 5
    layer_mid: int = 5
    layer_long: int = 5
    density: float = 0.84

    def layer_for(self, net_cls: str) -> int:
        return {
            "short": self.layer_short,
            "mid": self.layer_mid,
            "long": self.layer_long,
        }[net_cls]


@dataclass
class PhysResult:
    trial: Trial
    die_w: float
    die_h: float
    core_area: float
    cell_area: float
    wire_area: float
    die_area: float
    net_len: Dict[str, float]                # per-net routed length (um)
    net_layer: Dict[str, int]
    net_cls: Dict[str, str]
    buffered: Dict[str, int]                 # net -> number of inserted buffers
    drc: int
    drc_detail: Dict[str, int]
    wire_len_by_layer: Dict[int, float]
    util_by_layer: Dict[int, float]
    pos: Dict[int, Tuple[float, float]] = field(default_factory=dict)

    @property
    def cell_area_um2(self) -> float:
        return self.cell_area


def _cell_footprint(cell: str, drive: float) -> float:
    """Cell width in um at a given drive (height fixed to CELL_HEIGHT)."""
    base = LIBRARY[cell].area0 / CELL_HEIGHT
    return base * (0.35 + 0.65 * drive) + (0.35 if LIBRARY[cell].flop else 0.0)


def place_and_route(nl: Netlist, trial: Trial, seed: int = 1) -> PhysResult:
    """Deterministic placement + routing estimation for a trial config."""
    # ---------------- area / core -----------------------------------------
    cell_area = 0.0
    for inst in nl.instances:
        cell_area += area_of(LIBRARY[inst.cell],
                             trial.drives.get(inst.cell, 1.0), trial.ratio)
    core_area = cell_area / max(trial.density, 0.30)
    die_w = np.sqrt(core_area / ASPECT)
    die_h = core_area / die_w

    # ---------------- placement -------------------------------------------
    # cluster-based ordering: instances sharing a functional hint (bit / FSM
    # group) are placed next to each other, as a real packer would
    n_rows = max(2, int(np.ceil(die_h / ROW_PITCH)))
    row_len = die_w
    order_sorted = sorted(
        range(len(nl.instances)),
        key=lambda i: (nl.hint.get(i, 9999), i),
    )
    widths = [
        _cell_footprint(nl.instances[i].cell, trial.drives.get(nl.instances[i].cell, 1.0))
        for i in order_sorted
    ]
    n_cells = len(widths)
    sum_w = float(sum(widths))
    GAP_MIN = 0.15                       # DRC minimum cell spacing (um)
    row_capacity = n_rows * row_len
    gap_target = (row_capacity - sum_w) / max(n_cells, 1)
    gap = max(gap_target, GAP_MIN)
    if gap_target < GAP_MIN:
        crowding = min(1.5, (GAP_MIN - gap_target) / GAP_MIN)
        drc_spacing = int(crowding * n_cells / 25.0)
    else:
        drc_spacing = 0

    pos: Dict[int, Tuple[float, float]] = {}
    x_cursor = 0.0
    row = 0
    direction = 1
    for i, w in zip(order_sorted, widths):
        if direction == 1:
            if x_cursor + w > row_len:
                if row < n_rows - 1:
                    row += 1
                    x_cursor = row_len
                    direction = -1
                else:
                    x_cursor = max(0.0, row_len - w)  # overlap (DRC'd)
            pos[i] = (min(max(x_cursor + w / 2.0, 0.0), row_len),
                      row * ROW_PITCH)
            x_cursor += w + gap
        else:
            if x_cursor - w < 0.0:
                if row < n_rows - 1:
                    row += 1
                    x_cursor = 0.0
                    direction = 1
                else:
                    x_cursor = min(w, row_len)  # overlap (DRC'd)
            pos[i] = (min(max(x_cursor - w / 2.0, 0.0), row_len),
                      row * ROW_PITCH)
            x_cursor -= w + gap

    # source positions: DFF Q outputs sit on their flip-flop; primary inputs
    # sit on the periphery next to the cluster they feed
    src_pos: Dict[str, Tuple[float, float]] = {}
    for idx, q in nl.dff_q_of.items():
        src_pos[q] = pos[idx]
    cluster_row: Dict[int, float] = {}
    for i, (x, y) in pos.items():
        h = nl.hint.get(i, 9999)
        if h < 9000:
            cluster_row.setdefault(h, y)
    for n in nl.primary_inputs:
        h = nl.pi_hint.get(n, 9999)
        y = cluster_row.get(h % 1000, 0.0)
        if h < 1000:          # const / shared
            src_pos[n] = (die_w / 2.0, y)
        elif h < 2000:        # a-bit inputs, west periphery
            src_pos[n] = (0.5, y)
        else:                 # b-bit inputs, east periphery
            src_pos[n] = (die_w - 0.5, y)

    def net_origin(net: str) -> Tuple[float, float]:
        d = nl.net_driver[net]
        if d >= 0:
            return pos[d]
        return src_pos.get(net, (die_w / 2.0, die_h / 2.0))

    # ---------------- routing ---------------------------------------------
    raw_len: Dict[str, float] = {}
    for net in nl.net_driver:
        if not nl.net_loads[net]:
            raw_len[net] = 0.0
            continue
        ox, oy = net_origin(net)
        dmax = 0.0
        dsum = 0.0
        nloads = 0
        for li in nl.net_loads[net]:
            lx, ly = pos[li]
            d = abs(lx - ox) + abs(ly - oy)
            dmax = max(dmax, d)
            dsum += d
            nloads += 1
        # routing-tree approximation: half-way between the mean and the
        # farthest load (single-load nets collapse to the exact distance)
        raw_len[net] = 0.5 * (dsum / nloads + dmax)

    lengths = np.array([v for v in raw_len.values() if v > 0.0])
    if len(lengths) > 10:
        q33 = float(np.quantile(lengths, 0.34))
        q66 = float(np.quantile(lengths, 0.67))
    else:
        q33 = q66 = 1e9

    net_cls: Dict[str, str] = {}
    for net, L in raw_len.items():
        if L <= q33:
            net_cls[net] = "short"
        elif L <= q66:
            net_cls[net] = "mid"
        else:
            net_cls[net] = "long"

    # layer utilisation (first pass, base detour) -> congestion detour
    def assign_layers() -> Tuple[Dict[str, int], Dict[str, float]]:
        nl_: Dict[str, int] = {}
        tot: Dict[int, float] = {5: 0.0, 6: 0.0, 7: 0.0}
        for net, L in raw_len.items():
            lay = trial.layer_for(net_cls[net])
            nl_[net] = lay
            tot[lay] += L * LAYER_DATA[lay]["detour"]
        return nl_, tot

    net_layer, tot_raw = assign_layers()
    cap = {l: LAYER_DATA[l]["cap"] * core_area for l in (5, 6, 7)}
    util = {l: tot_raw[l] / max(cap[l], 1e-9) for l in (5, 6, 7)}
    cong = {l: 1.0 + 0.5 * max(0.0, util[l] - 0.85) for l in (5, 6, 7)}

    # final lengths with congestion detour
    net_len: Dict[str, float] = {}
    for net, L in raw_len.items():
        lay = net_layer[net]
        net_len[net] = L * LAYER_DATA[lay]["detour"] * cong[lay]

    # buffer insertion on the longest nets
    buffered: Dict[str, int] = {}
    if trial.nbuf > 0:
        longs = sorted(
            (n for n in net_len if net_cls[n] == "long" and net_len[n] > 6.0),
            key=lambda n: -net_len[n],
        )
        for n in longs[:24]:
            buffered[n] = trial.nbuf

    # ---------------- area / DRC -------------------------------------------
    wire_len_by_layer = {5: 0.0, 6: 0.0, 7: 0.0}
    for net in net_len:
        wire_len_by_layer[net_layer[net]] += net_len[net]
    wire_area = sum(wire_len_by_layer[l] * LAYER_DATA[l]["w"] for l in (5, 6, 7))
    die_area = core_area * (1.0 + PERIPHERY)

    drc_detail: Dict[str, int] = {}
    # R1: minimum cell spacing (crowding at high utilisation)
    drc_detail["cell_spacing"] = drc_spacing
    # R2: metal utilisation limit (0.85)
    metal = 0
    for l in (5, 6, 7):
        if util[l] > 0.85:
            metal += int((util[l] - 0.85) * 250)
    drc_detail["metal_util"] = metal
    # R3: local density window > 80%
    drc_detail["density_window"] = 2 if trial.density > 0.80 else 0
    # R4: double-layer congestion (vias)
    hot = [l for l in (5, 6, 7) if util[l] > 0.95]
    drc_detail["via_crowding"] = 3 if len(hot) >= 2 else 0
    drc = sum(drc_detail.values())

    pos_out: Dict[int, Tuple[float, float]] = dict(pos)
    return PhysResult(
        trial=trial, die_w=float(die_w), die_h=float(die_h),
        core_area=float(core_area), cell_area=float(cell_area),
        wire_area=float(wire_area), die_area=float(die_area),
        net_len=net_len, net_layer=net_layer, net_cls=net_cls,
        buffered=buffered, drc=int(drc), drc_detail=drc_detail,
        wire_len_by_layer=wire_len_by_layer, util_by_layer=util,
        pos=pos_out,
    )
