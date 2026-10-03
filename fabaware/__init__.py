"""
FabAware-Opt
============

A fabrication-aware, open-source EDA optimization framework evaluated through
transistor simulation and RTL-to-gate netlist experiments.

FabAware-Opt models a 28nm-class standard-cell ASIC design, injects realistic
process / voltage / temperature (PVT) and within-die variability, and uses an
AI (Gaussian-process surrogate + expected-improvement search) to select
transistor sizing (Wp/Wn ratio), standard-cell drive strengths, buffering and
metal-layer / placement parameters that maximise *timing yield* under
manufacturing variation, subject to area and power budgets.

Scope note
----------
This is a simulation/optimization framework. It does **not** fabricate a chip;
it is evaluated through transistor-level compact-model simulation and
netlist-level (RTL-to-GDSII class) timing, power, area and DRC experiments.
"""

__version__ = "1.0.0"
__all__ = [
    "compact",
    "library",
    "design",
    "pd",
    "sta",
    "optimizer",
    "report",
]
