# Viva / interview notes

For internships, **demo the lab** (`python cellforge.py lab`) rather than
the PDF.  The PDF is the course write-up; the lab is the product.

Short answers you can give without opening a laptop.  Numbers are from
`results/metrics.json` of the last full run.

## What did you build?

A laptop-scale, fully open-source flow that takes SKY130-calibrated transistor
physics → a PVT characterization dataset → an ML delay/leakage surrogate →
NSGA-II transistor sizing for yield → a Liberty file → STA of an 8-bit
registered ripple-carry adder.

## Why not Magic / OpenROAD / the real PDK?

Disk and reliability.  OpenROAD + SKY130 is 20–50 GB and a research flow;
the Slim 3i has ~100 GB free.  A Digital IC Design course grades devices,
cells, PVT, libraries and timing — not GDS streaming.  Optional ngspice
netlists are in `spice/` if an examiner asks.

## What MOSFET model?

Sakurai α-power law in strong inversion plus the subthreshold exponential.
Vt has temperature (`≈ −1.6 mV/K`), DIBL, ss/tt/ff corners and Pelgrom
mismatch `σVt = AVt/√(WL)`.  Ion is pinned to 520 / 245 µA/µm (n/p),
Ioff to ~250 / 120 pA/µm, FO4 inverter delay to **45.0 ps** at tt/1.8 V/25 °C.

## Why is FO4 45 ps?

Published-order 130 nm / SKY130 FO4 is 30–60 ps.  We solve a delay prefactor
so the min-size FO4 inverter hits 45 ps.  Slow corner (ss, 1.62 V, 125 °C)
is **83 ps**; fast corner (ff, 1.98 V, −40 °C) is **26 ps**.

## Where did the dataset come from?

It does not exist in public at transistor-width resolution.  Foundry `.lib`
files are *fixed* drive strengths.  We generate a Latin-hypercube DOE
(9000 points) over Wn, Wp, L, VDD, T, Cload, slew × cell × corner.
That is exactly what Liberate would produce; only the SPICE engine is replaced.

## ML results to quote

| Target | Model | Test R² | MAE |
|--------|--------|---------|-----|
| Delay  | HistGB | **0.962** | 8.2 ps |
| Delay  | Ridge  | 0.681 | — |
| Leakage| HistGB (log target) | **0.967** | — |

Permutation importance: Cload, Wn, Wp, L, stack depth, corner — which is
what `t ∝ C V / I(W, Vt, T)` says.

## How is yield defined?

A die passes if delay < spec and leakage < spec.  Inside NSGA-II, yield is
`Φ((spec−μ)/σ)` with σ from Pelgrom.  Sign-off is 220-shot Monte Carlo on
the physics engine.  All eight ML-opt cells reach 100 % cell-level yield
at ss/85 °C.

## Why NSGA-II, not a single cost?

Delay, energy and yield fight.  A weighted sum hides that.  NSGA-II returns
a Pareto front; we pick the knee (closest to the normalized ideal).

## Adder numbers

Registered 8-bit RCA, ideal clock, NLDM interpolation.

| Corner | Fmax |
|--------|------|
| tt 1.8 V 25 °C | **614 MHz** |
| ss 1.62 V 125 °C | **426 MHz** |
| ff 1.98 V −40 °C | **1075 MHz** |

Sign-off period 400 MHz (fair for an 8-stage ripple carry).  Block MC yield
**96.4 %**, P5 Fmax **403 MHz**.  Critical path is the carry chain
(`AOI21` + `INV` per bit).  A CLA would be faster — say that if asked.

## What is a Liberty NLDM table?

Cell delay and output slew as a 2-D lookup vs input slew and output load.
We emit 5×5 tables for tt/ss/ff.  Files: `results/liberty/*.lib`.

## Limitations (say these yourself — it scores honesty)

Compact MOS, not BSIM6.  Ideal clock, no SPEF.  DFF setup/hold scaled from
FO1, not a metastability search.  Single related-pin timing arcs.

## How do I regenerate every number?

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_project.py
```

Open `docs/REPORT.html` and print to PDF.
