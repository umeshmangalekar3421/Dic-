"""Standard-cell topologies used by the characterization engine.

Each cell is described by pull-up / pull-down stack depth, device count
and logical-effort parameters (Sutherland / Harris).  Device counts are
those of static complementary CMOS (plus a transmission-gate MUX and a
master-slave DFF).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class StandardCell:
    name: str
    n_series_n: int
    n_series_p: int
    n_nmos: int
    n_pmos: int
    logical_effort: float
    parasitic_delay: float
    n_inputs: int
    is_sequential: bool = False
    # extra diffusion / internal nodes that add parasitic C (relative)
    internal_cap_weight: float = 0.0
    # stack leakage reduction when series devices are off
    stack_leak_factor: float = 1.0
    description: str = ""


CELLS: Dict[str, StandardCell] = {
    "INV": StandardCell(
        name="INV",
        n_series_n=1, n_series_p=1, n_nmos=1, n_pmos=1,
        logical_effort=1.0, parasitic_delay=1.0, n_inputs=1,
        description="Static CMOS inverter (1n + 1p).",
    ),
    "NAND2": StandardCell(
        name="NAND2",
        n_series_n=2, n_series_p=1, n_nmos=2, n_pmos=2,
        logical_effort=4.0 / 3.0, parasitic_delay=2.0, n_inputs=2,
        internal_cap_weight=0.35, stack_leak_factor=0.22,
        description="2-input NAND: 2-stack NMOS, parallel PMOS.",
    ),
    "NOR2": StandardCell(
        name="NOR2",
        n_series_n=1, n_series_p=2, n_nmos=2, n_pmos=2,
        logical_effort=5.0 / 3.0, parasitic_delay=2.0, n_inputs=2,
        internal_cap_weight=0.40, stack_leak_factor=0.22,
        description="2-input NOR: 2-stack PMOS, parallel NMOS.",
    ),
    "AOI21": StandardCell(
        name="AOI21",
        n_series_n=2, n_series_p=2, n_nmos=3, n_pmos=3,
        logical_effort=5.0 / 3.0, parasitic_delay=2.5, n_inputs=3,
        internal_cap_weight=0.55, stack_leak_factor=0.30,
        description="AND-OR-INVERT (A&B)|C  complementary CMOS, 6T.",
    ),
    "OAI21": StandardCell(
        name="OAI21",
        n_series_n=2, n_series_p=2, n_nmos=3, n_pmos=3,
        logical_effort=5.0 / 3.0, parasitic_delay=2.5, n_inputs=3,
        internal_cap_weight=0.55, stack_leak_factor=0.30,
        description="OR-AND-INVERT (A|B)&C  complementary CMOS, 6T.",
    ),
    "MUX2": StandardCell(
        name="MUX2",
        n_series_n=2, n_series_p=2, n_nmos=6, n_pmos=6,
        logical_effort=2.0, parasitic_delay=2.5, n_inputs=3,
        internal_cap_weight=0.80, stack_leak_factor=0.35,
        description="2:1 mux, complementary transmission-gate + output inv.",
    ),
    "XOR2": StandardCell(
        name="XOR2",
        n_series_n=2, n_series_p=2, n_nmos=6, n_pmos=6,
        logical_effort=4.0, parasitic_delay=4.0, n_inputs=2,
        internal_cap_weight=1.10, stack_leak_factor=0.40,
        description="Static CMOS 12T XOR.",
    ),
    "DFF": StandardCell(
        name="DFF",
        n_series_n=1, n_series_p=1, n_nmos=12, n_pmos=12,
        logical_effort=4.5, parasitic_delay=5.0, n_inputs=2,
        is_sequential=True, internal_cap_weight=2.2, stack_leak_factor=0.50,
        description="Master-slave rising-edge DFF (24T class) with clk-inv pair.",
    ),
}
