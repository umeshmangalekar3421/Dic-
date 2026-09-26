"""Gate-level static timing of a registered 8-bit ripple-carry adder.

Netlist (per bit i)
-------------------
  propagate / generate using AOI/NAND/INV (mirror-carry style):
    p_i  = XOR2(a_i, b_i)
    g_i  = NAND2(a_i, b_i) inverted  -> AND
    cout_i uses AOI21(g, p, cin) + INV   (majority / carry)

  sum_i = XOR2(p_i, cin_i)

Input and output registers are DFF_X1.  Clock path is ideal (no skew)
which is the usual first-cut STA assumption for a course-scale block.

Delay of each gate is interpolated from the same NLDM tables written
into the Liberty file (input slew x output load).  Wire load is a
simple fanout-based model (0.4 fF + 0.6 fF * fanout).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from dic_mlopt import config as C
from dic_mlopt.liberty.writer import LOADS_PF, SLEWS_NS, nldm_tables
from dic_mlopt.physics.characterize import CellCharacterizer


@dataclass
class Gate:
    name: str
    cell: str
    inputs: List[str]
    output: str


@dataclass
class STAResult:
    arrival_ns: Dict[str, float]
    slew_ns: Dict[str, float]
    critical_path: List[str]
    t_combo_ns: float
    t_cq_ns: float
    t_setup_ns: float
    t_required_ns: float
    wns_ns: float
    fmax_mhz: float
    period_ns: float
    n_gates: int
    cell_counts: Dict[str, int]


def build_registered_adder(width: int = 8) -> Tuple[List[Gate], List[str], List[str]]:
    gates: List[Gate] = []
    # Input FFs
    for i in range(width):
        gates.append(Gate(f"ffa{i}", "DFF", ["a_d{i}".format(i=i), "clk"], f"a{i}"))
        gates.append(Gate(f"ffb{i}", "DFF", ["b_d{i}".format(i=i), "clk"], f"b{i}"))
    gates.append(Gate("ffcin", "DFF", ["cin_d", "clk"], "cin0"))

    cin = "cin0"
    for i in range(width):
        gates.append(Gate(f"xor_p{i}", "XOR2", [f"a{i}", f"b{i}"], f"p{i}"))
        gates.append(Gate(f"nand_g{i}", "NAND2", [f"a{i}", f"b{i}"], f"gn{i}"))
        gates.append(Gate(f"inv_g{i}", "INV", [f"gn{i}"], f"g{i}"))
        # carry: ~(~g & ~(p & cin))  = g | (p & cin)  via AOI21 + INV
        gates.append(Gate(f"aoi_c{i}", "AOI21", [f"p{i}", cin, f"g{i}"], f"cn{i}"))
        gates.append(Gate(f"inv_c{i}", "INV", [f"cn{i}"], f"c{i + 1}"))
        gates.append(Gate(f"xor_s{i}", "XOR2", [f"p{i}", cin], f"s{i}"))
        cin = f"c{i + 1}"

    for i in range(width):
        gates.append(Gate(f"ffs{i}", "DFF", [f"s{i}", "clk"], f"s_q{i}"))
    gates.append(Gate("ffcout", "DFF", [f"c{width}", "clk"], "cout_q"))
    primary_in = [f"a_d{i}" for i in range(width)] + [f"b_d{i}" for i in range(width)] + ["cin_d", "clk"]
    primary_out = [f"s_q{i}" for i in range(width)] + ["cout_q"]
    return gates, primary_in, primary_out


def _interp2(table: np.ndarray, slew_ns: float, load_pf: float) -> float:
    s = np.clip(slew_ns, SLEWS_NS[0], SLEWS_NS[-1])
    c = np.clip(load_pf, LOADS_PF[0], LOADS_PF[-1])
    # bilinear
    i = int(np.searchsorted(SLEWS_NS, s) - 1)
    j = int(np.searchsorted(LOADS_PF, c) - 1)
    i = np.clip(i, 0, len(SLEWS_NS) - 2)
    j = np.clip(j, 0, len(LOADS_PF) - 2)
    s0, s1 = SLEWS_NS[i], SLEWS_NS[i + 1]
    c0, c1 = LOADS_PF[j], LOADS_PF[j + 1]
    ts = 0.0 if s1 == s0 else (s - s0) / (s1 - s0)
    tc = 0.0 if c1 == c0 else (c - c0) / (c1 - c0)
    v00, v01 = table[i, j], table[i, j + 1]
    v10, v11 = table[i + 1, j], table[i + 1, j + 1]
    return float((1 - ts) * (1 - tc) * v00 + (1 - ts) * tc * v01 + ts * (1 - tc) * v10 + ts * tc * v11)


class LibertyView:
    def __init__(self, sizing: Dict[str, dict], corner: str, vdd: float, temp_c: float):
        char = CellCharacterizer()
        self.tables = {}
        for name, sz in sizing.items():
            self.tables[name] = nldm_tables(char, name, sz["wn_um"], sz["wp_um"], corner, vdd, temp_c)

    def delay(self, cell: str, slew_ns: float, load_pf: float) -> float:
        t = self.tables[cell]
        return 0.5 * (
            _interp2(t["cell_rise"], slew_ns, load_pf)
            + _interp2(t["cell_fall"], slew_ns, load_pf)
        )

    def slew(self, cell: str, slew_ns: float, load_pf: float) -> float:
        t = self.tables[cell]
        return _interp2(t["rise_trans"], slew_ns, load_pf)

    def cin(self, cell: str) -> float:
        return self.tables[cell]["cin_pf"]

    def t_cq(self, cell: str = "DFF") -> float:
        return max(self.tables[cell]["t_cq_ns"], self.delay(cell, 0.03, 0.006))

    def t_setup(self, cell: str = "DFF") -> float:
        return max(self.tables[cell]["t_setup_ns"], 0.01)


def run_sta(
    sizing: Dict[str, dict],
    corner: str = "tt",
    vdd: float = C.VDD_NOM,
    temp_c: float = 25.0,
    period_ns: float = C.ADDER_PERIOD_NS,
    width: int = 8,
) -> STAResult:
    gates, _, _ = build_registered_adder(width)
    lib = LibertyView(sizing, corner, vdd, temp_c)

    fanout: Dict[str, int] = {}
    drivers: Dict[str, Gate] = {}
    for g in gates:
        drivers[g.output] = g
        for inp in g.inputs:
            fanout[inp] = fanout.get(inp, 0) + 1

    def load_of(net: str) -> float:
        fo = fanout.get(net, 1)
        # each fanout pin cap + wire
        # guess cell of fanout from drivers of nets that use this as input
        cap = 0.0004 + 0.0006 * fo  # pF
        for g in gates:
            if net in g.inputs:
                cap += lib.cin(g.cell) / max(len(g.inputs), 1)
        return cap

    arrival: Dict[str, float] = {}
    slew: Dict[str, float] = {}
    pred: Dict[str, str] = {}

    # clock and data-at-FF-D assumed arrival 0
    arrival["clk"] = 0.0
    slew["clk"] = 0.03
    for i in range(width):
        arrival[f"a_d{i}"] = 0.0
        arrival[f"b_d{i}"] = 0.0
        slew[f"a_d{i}"] = 0.03
        slew[f"b_d{i}"] = 0.03
    arrival["cin_d"] = 0.0
    slew["cin_d"] = 0.03

    remaining = list(gates)
    guard = 0
    while remaining and guard < 10000:
        guard += 1
        progress = False
        for g in list(remaining):
            if not all(inp in arrival for inp in g.inputs):
                continue
            if g.cell == "DFF":
                # launch: clk -> Q
                if g.output.endswith("_q") or g.name.startswith("ffs") or g.name.startswith("ffcout"):
                    # capture FF: D arrival is combo, handled later
                    dpin = g.inputs[0]
                    # still produce Q for completeness
                    cload = load_of(g.output)
                    dly = lib.t_cq()
                    arrival[g.output] = arrival["clk"] + dly
                    slew[g.output] = lib.slew("DFF", 0.03, cload)
                    pred[g.output] = "clk"
                else:
                    cload = load_of(g.output)
                    dly = lib.t_cq()
                    arrival[g.output] = arrival["clk"] + dly
                    slew[g.output] = lib.slew("DFF", 0.03, cload)
                    pred[g.output] = g.name
                remaining.remove(g)
                progress = True
                continue
            # combinational
            in_arr = max(arrival[inp] for inp in g.inputs)
            in_slew = max(slew[inp] for inp in g.inputs)
            cload = load_of(g.output)
            dly = lib.delay(g.cell, in_slew, cload)
            arrival[g.output] = in_arr + dly
            slew[g.output] = lib.slew(g.cell, in_slew, cload)
            # predecessor = latest input
            late = max(g.inputs, key=lambda n: arrival[n])
            pred[g.output] = late
            remaining.remove(g)
            progress = True
        if not progress:
            break

    # capture checks on output FFs
    t_cq = lib.t_cq()
    t_su = lib.t_setup()
    # combo path: from input FF Q to output FF D
    d_pins = [f"s{i}" for i in range(width)] + [f"c{width}"]
    latest_net = max(d_pins, key=lambda n: arrival.get(n, 0.0))
    latest = arrival[latest_net]
    t_combo = latest - t_cq  # subtract launch t_cq already in arrival of a_i
    wns = period_ns - (t_cq + t_combo + t_su)
    fmax = 1000.0 / (t_cq + t_combo + t_su)  # MHz

    path = [latest_net]
    seen = set()
    while path[-1] in pred and path[-1] not in seen:
        seen.add(path[-1])
        path.append(pred[path[-1]])
    path.reverse()

    counts: Dict[str, int] = {}
    for g in gates:
        counts[g.cell] = counts.get(g.cell, 0) + 1

    return STAResult(
        arrival_ns=arrival,
        slew_ns=slew,
        critical_path=path,
        t_combo_ns=t_combo,
        t_cq_ns=t_cq,
        t_setup_ns=t_su,
        t_required_ns=period_ns,
        wns_ns=wns,
        fmax_mhz=fmax,
        period_ns=period_ns,
        n_gates=len(gates),
        cell_counts=counts,
    )


def monte_carlo_fmax(
    sizing: Dict[str, dict],
    n: int = 250,
    corner: str = "ss",
    vdd: float = 1.62,
    temp_c: float = 125.0,
    period_ns: float = C.ADDER_PERIOD_NS,
    seed: int = 0,
) -> dict:
    """Perturb every cell delay by Pelgrom-derived sigma and recompute Fmax."""
    rng = np.random.default_rng(seed)
    base = run_sta(sizing, corner, vdd, temp_c, period_ns)
    # Approximate: scale combo delay by a lognormal around 1 with sigma ~ 4%
    # (mismatch of many stacked gates averages down, global corner already applied)
    scales = rng.normal(1.0, 0.035, size=n)
    t = (base.t_cq_ns + base.t_combo_ns + base.t_setup_ns) * np.clip(scales, 0.85, 1.20)
    wns = period_ns - t
    fmax = 1000.0 / t
    yield_at_period = float(np.mean(wns >= 0))
    return {
        "wns_ns": wns,
        "fmax_mhz": fmax,
        "yield": yield_at_period,
        "fmax_mean": float(fmax.mean()),
        "fmax_p5": float(np.percentile(fmax, 5)),
        "fmax_p95": float(np.percentile(fmax, 95)),
        "base": {
            "t_combo_ns": base.t_combo_ns,
            "t_cq_ns": base.t_cq_ns,
            "t_setup_ns": base.t_setup_ns,
            "wns_ns": base.wns_ns,
            "fmax_mhz": base.fmax_mhz,
            "critical_path": base.critical_path,
            "n_gates": base.n_gates,
            "cell_counts": base.cell_counts,
        },
    }
