# FabAware-Opt

**AI-Assisted Process-Variation-Aware Standard-Cell and Physical-Design
Optimization for Improved ASIC Yield**

> A fabrication-aware, open-source EDA optimization framework evaluated through
> transistor simulation and RTL-to-gate netlist experiments.

---

## The research question

> **Can an open-source AI-assisted flow select transistor sizes, standard cells,
> and physical-design parameters that improve timing yield under process,
> voltage, and temperature variations without excessive power or area overhead?**

This repository answers that question with a working, reproducible simulation
framework — not a slide deck. It builds a real 32-bit datapath netlist, models
transistor physics, injects manufacturing variability over hundreds of
simulated chips, and lets a Gaussian-process optimizer search the design space.

## What it does, in one minute

```
$ pip install -e .
$ fabaware-run --chips 200
```

```
RESULT   timing yield   29.0%  →   99.5%   (+70.5 pp)
         worst slack     -1.7  →   +14.3 ps
         area / power  1167→1419 um2   0.214→0.317 mW
         DRC          32 → 0
         total runtime 4.7 s
```

The four-step demonstration the project is built around:

| Step | What happens |
|------|--------------|
| **1. Normal configuration** | Conventional drive-1-everywhere standard-cell setup: worst slack **−1.7 ps**, 32 DRC violations |
| **2. Manufacturing-variation stress test** | 200 Monte-Carlo chips with correlated global + per-device local variation: only **29%** meet timing |
| **3. AI-optimized configuration** | GP surrogate + expected improvement over 13 design variables picks new cell drives, Wp/Wn ratio, buffering, metal layers, density |
| **4. Comparison** | Yield **99.5%**, slack **+14.3 ps**, DRC **0**, area **+21.6%**, power **+48.3%** |

Run it as a script: `python -c "from fabaware.cli import demo; demo(['-K','400'])"`

## Why this is not a toy

Every number is computed, not asserted.

**Transistor-level physics.** A compact MOSFET model (`fabaware/compact.py`)
provides drive current, output resistance and leakage from W, L, Vth, Vdd and
temperature — including µ ∝ T<sup>−1.5</sup> mobility degradation, ≈ −50 µV/K
threshold drift, velocity saturation and mobility-degradation correction.
Gate delays are *derived* from this model, so a change in transistor width or
supply propagates to timing the way it would in SPICE.

**A real netlist.** FAB-32 is built gate-by-gate from compound standard cells
(`fabaware/design.py`): a 32-bit carry-select adder in eight 4-bit blocks, a
4-operation 32-bit ALU, a 4-bit counter FSM driving the op field, and a
32-bit pipeline register — 466 gates, 36 flip-flops, 2 628 transistors, 70
timing endpoints. Its critical path runs through the carry chain, which is
genuinely variation-sensitive.

**Statistical timing that means something.** Each simulated chip draws
correlated global variation (implant/CD/global threshold) plus independent
per-device local variation. Longest-path dynamic programming computes every
endpoint; a chip passes only if *all* of them meet the 211 ps period. Per-chip
Vmin is found by a binary-free voltage sweep.

**Physical design that feeds back into timing.** Placement is cluster-aware row
packing; routing estimates Manhattan length with layer-dependent detour and
congestion; nets are classified short/mid/long and assigned M5/M6/M7; buffers
are inserted on long wires; wire RC becomes load capacitance and an Elmore
delay term that actually reaches the timing engine. A simplified rule deck
reports DRC violations.

**Genuine trade-offs, discovered not scripted.** Upper metal has lower R but
higher C/µm, so it wins on long wires and loses on short ones. Upsizing cells
buys timing and costs area and power. Denser placement shrinks the die and
raises DRC. The optimizer has to find the balance — and you can see it do so
in the Pareto plot.

## Quick start

```bash
git clone <your-fork> && cd Dic-
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -e .

fabaware-run                 # full flow → reports/report.html + results.json
fabaware-run --chips 500     # more Monte-Carlo chips (default 200)
fabaware-run --real          # synthesize rtl/fab32.v with REAL Yosys
fabaware-web                 # live dashboard on http://localhost:8000
pytest -q                    # 50 tests
```

## Real EDA tools

FabAware-Opt runs on **real tools when they are installed** and on its own
Python models when they are not — chosen automatically, per layer.

| Layer | Python model | Real tool | Status |
|---|---|---|---|
| RTL synthesis | `design.py` | **Yosys** | ✅ **real — runs today (`--real`)** |
| Transistor model | `compact.py` | ngspice + BSIM | backend ready |
| Static timing | `sta.py` | OpenSTA | backend ready |
| Place & route | `pd.py` | OpenROAD | backend ready |
| Optimization | `optimizer.py` | *(none standard)* | ⭐ **ours** |

With `--real`, `rtl/fab32.v` goes through genuine Yosys, which produced
**844 gates / 35 flops / 3,298 transistors** and chose a Brent-Kung
carry-lookahead adder on its own. On that netlist the flow reaches
**34.5% → 100% timing yield and DRC 225 → 0**.

```bash
python -c "from fabaware.backends import tools; print(tools.summary())"
bash scripts/install_real_tools.sh          # install the rest
fabaware-run --real --liberty sky130.lib    # map onto a real PDK
```

See [`docs/REAL_TOOLS.md`](docs/REAL_TOOLS.md) for how each swap works.

### Requirements

Python 3.9+, and `numpy`, `scipy`, `scikit-learn`, `matplotlib`. That is all.

**Runs comfortably on modest hardware.** The whole flow is CPU-only NumPy with
no GPU dependency: about **5 seconds** and well under 200 MB of RAM for the
default 200-chip run on a laptop-class processor. There is no heavy build step
and no external EDA tool to install.

## Repository layout

```
rtl/
  fab32.v        the design in real synthesizable Verilog (read by Yosys)
fabaware/
  compact.py     compact MOSFET model (the physics every number derives from)
  library.py     28nm-class standard-cell library with A/B timing coefficients
  design.py      FAB-32 netlist: 32-bit carry-select adder, ALU, FSM, pipeline
  pd.py          placement, routing, layer assignment, buffer insertion, DRC
  sta.py         Monte-Carlo statistical timing, Vmin sweep, power, corners
  optimizer.py   GP surrogate + expected improvement + local refinement
  figure.py      all charts, rendered from evaluated data
  report.py      self-contained HTML report + results.json
  cli.py         fabaware-run / fabaware-demo
  web.py         live dashboard
  backends/
    tools.py     auto-detection of Yosys / ngspice / OpenSTA / OpenROAD
    yosys.py     real RTL synthesis + netlist import
tests/          50 tests: physics, statistics, Yosys backend, reproducibility
scripts/        install_real_tools.sh
reports/        generated: report.html, results.json, figures/
```

## The AI search

13 decision variables:

| Variable | Range |
|----------|-------|
| Drive strength for 7 resizable cell types | 1× / 2× / 4× |
| Wp/Wn transistor sizing ratio | 0.80 – 1.40 |
| Buffers inserted on long wires | 0 – 4 |
| Metal layer for short / mid / long nets | M5 / M6 / M7 |
| Placement density | 0.55 – 0.85 |

Objective:

```
score = timing yield
        − 2.5 · max(0, area/area₀ − 1.30)
        − 2.5 · max(0, power/power₀ − 1.50)
        − 0.15 · DRC/100
```

The loop: a Sobol design of experiments → a Matérn-2.5 Gaussian-process
surrogate fitted to `x → score` → expected-improvement acquisition over a
6 000-point Halton candidate grid → evaluate the winner with full Monte-Carlo
statistical timing → repeat, then local refinement. The surrogate is what makes
an expensive, trustworthy evaluator affordable.

Because the yield term saturates at 100%, the optimizer does not simply
maximize slack at any cost — it stops and trades the remaining slack back for
area and power. That is why the reported solution sits on the favourable edge
of the Pareto frontier rather than at the far corner.

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/BEGINNERS_GUIDE.md`](docs/BEGINNERS_GUIDE.md) | Start here if chips/EDA are new to you |
| [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) | Models, equations, calibration and their justification |
| [`docs/VALIDATION.md`](docs/VALIDATION.md) | What was verified, and the evidence |
| [`docs/REAL_TOOLS.md`](docs/REAL_TOOLS.md) | Migrating to Yosys / ngspice / OpenSTA / OpenROAD |
| [`docs/TEAM.md`](docs/TEAM.md) | Division of work for a three-student team |
| [`docs/PRESENTATION.md`](docs/PRESENTATION.md) | How to demo it, and likely questions |

## Scope, stated precisely

**This project does not fabricate a chip, and does not replace sign-off tools.**
It is a *fabrication-aware, open-source EDA optimization framework evaluated
through transistor simulation and RTL-to-gate netlist experiments.*

- **Modelled:** transistor physics, gate-level timing, interconnect RC with
  layer choice and congestion, leakage, area, placement density, and a
  simplified DRC rule deck.
- **Deliberately simplified:** the DRC deck is an analytic estimator rather
  than a real rule deck; the placer is a deterministic cluster/row packer
  rather than a full analytical placer; routing is estimated rather than
  detailed-routed.
- **What the numbers are:** internally consistent, seed-reproducible, and
  calibrated to published 28 nm-class figures. They are *predictions of a
  model*, not measurements of silicon.

Every figure in the report is rendered from evaluated simulation data, and
every number is also written to `reports/results.json`.

## Reproducibility

All randomness is seeded (`--seed`, default 42). The same command on the same
machine produces byte-identical results; this is enforced by a regression test.

```bash
fabaware-run --chips 200 --seed 42 --out run-a
fabaware-run --chips 200 --seed 42 --out run-b
diff <(python -c "import json;print(json.load(open('run-a/results.json'))['optimized'])") \
     <(python -c "import json;print(json.load(open('run-b/results.json'))['optimized'])")
# no output
```

## License

MIT.
