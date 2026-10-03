"""
28nm-class standard-cell library.
=================================

Each cell carries the coefficients of the gate-level timing model

    t_stage = ( A + B * C_ext ) / S

where

* ``A``     intrinsic delay (ps) at unit drive, nominal PVT (rail imbalance
            already folded in - the slower of rise/fall dominates),
* ``B``     driver output-resistance coefficient (ps/fF),
* ``C_ext`` total load capacitance seen by the driver (fF),
* ``S``     the transistor drive factor from :mod:`fabaware.compact`
            (drive strength x variability x PVT).

Coefficients are calibrated so that a drive-1 inverter at Vdd=0.8 V, 25 degC
delivers ~10 ps intrinsic delay and ~0.22 ps/fF load sensitivity, consistent
with published 28nm gate speeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

DRIVE_STRENGTHS: Tuple[float, ...] = (1.0, 2.0, 4.0)


@dataclass(frozen=True)
class Cell:
    name: str
    a: float            # intrinsic delay coefficient (ps)
    b: float            # load coefficient (ps/fF)
    cin: float          # input capacitance per input (fF) at drive 1
    area0: float        # area at drive 1 (um^2)
    ilink: float        # leakage at 25 degC, drive 1 (nA)
    ntr: int            # transistor count
    setup: float = 0.0  # setup time (ps) - flip-flops only
    flop: bool = False

    @property
    def is_buffer(self) -> bool:
        return self.name.startswith("BUF")


#: library definition -----------------------------------------------------
LIBRARY: Dict[str, Cell] = {
    "INV":   Cell("INV",   a=4.2,  b=0.14, cin=1.00, area0=1.1, ilink=0.30, ntr=2),
    "BUF":   Cell("BUF",   a=3.5,  b=0.13, cin=1.10, area0=1.1, ilink=0.40, ntr=2),
    "NAND2": Cell("NAND2", a=4.4,  b=0.18, cin=1.10, area0=1.6, ilink=0.80, ntr=4),
    "NAND3": Cell("NAND3", a=6.3,  b=0.25, cin=1.50, area0=2.2, ilink=1.20, ntr=6),
    "NOR2":  Cell("NOR2",  a=5.6,  b=0.28, cin=1.10, area0=1.6, ilink=1.00, ntr=4),
    "XOR2":  Cell("XOR2",  a=7.2,  b=0.31, cin=1.60, area0=2.6, ilink=2.50, ntr=8),
    "MUX2":  Cell("MUX2",  a=9.1,  b=0.28, cin=1.80, area0=2.6, ilink=2.00, ntr=6),
    "A21":   Cell("A21",   a=7.7,  b=0.28, cin=1.60, area0=2.0, ilink=1.60, ntr=6),
    "AOI22": Cell("AOI22", a=9.1,  b=0.35, cin=2.00, area0=2.8, ilink=2.40, ntr=8),
    "DFF":   Cell("DFF",   a=0.0,  b=0.0,  cin=2.40, area0=7.0, ilink=45.0,
                  ntr=10, setup=22.0, flop=True),
}

#: which cell types the AI is allowed to re-size (drive selection)
RESIZABLE_TYPES: Tuple[str, ...] = (
    "NAND2", "AOI22", "XOR2", "MUX2", "A21", "NAND3", "BUF",
)


def drive_to_area_factor(drive: float) -> float:
    """Cell area growth vs. drive (width scaling)."""
    return 0.35 + 0.65 * float(drive)


def area_of(cell: Cell, drive: float, ratio: float = 1.0) -> float:
    """Cell area (um^2) at a given drive strength and Wp/Wn ratio."""
    return cell.area0 * drive_to_area_factor(drive) * (1.0 + 0.35 * (ratio - 1.0))


def leakage_of(cell: Cell, drive: float, ratio: float = 1.0) -> float:
    """Cell leakage (nA) at a given drive strength and Wp/Wn ratio."""
    return cell.ilink * drive * (1.0 + 0.30 * (ratio - 1.0))


def cin_of(cell: Cell, drive: float) -> float:
    """Input capacitance (fF) - gate capacitance scales linearly with W."""
    return cell.cin * float(drive)
