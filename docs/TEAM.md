# Division of work for a three-student team

The project splits cleanly into three layers with narrow interfaces between
them, so the three students can work in parallel and integrate early. The
recommended split follows the module boundaries that already exist in the code.

---

## The three work packages

```
   ┌─────────────────────────────────────────────────────────────┐
   │                    shared contract (day 1)                   │
   │   Trial  ──config──►  evaluate()  ──►  EvalResult            │
   └─────────────────────────────────────────────────────────────┘
        │                      │                      │
        ▼                      ▼                      ▼
   Student A              Student B              Student C
   Device + library       Design + physical design   AI + evaluation
   (the physics)          (the silicon)              (the story)
```

The critical rule: **agree on the `Trial → EvalResult` interface on day 1.**
Once that is fixed, all three can proceed independently and integration is a
single function call.

| Interface | Owner | Consumers |
|-----------|-------|-----------|
| `Trial` (config dataclass) | A proposes, all agree | B, C |
| `EvalResult` (metrics dataclass) | C proposes, all agree | A, B |
| `evaluate(netlist, trial, K, seed)` | C (calls into A and B) | everyone |

---

## Student A — Device physics and cell library

**Modules:** `fabaware/compact.py`, `fabaware/library.py`

**Owns:**

- The compact MOSFET model: mobility, Vth drift, velocity saturation,
  mobility degradation, leakage.
- The standard-cell library: `A`, `B`, `Cin`, area, leakage, transistor count
  for ten cell types.
- Calibration of both against published 28 nm figures.

**Deliverables:**

1. `compact.py` with `drive_factor()`, `leakage_factor()`, `on_current()`,
   `output_resistance()`.
2. `library.py` with the ten-cell library and scaling functions.
3. The I–V and `Ids(Vdd)` figures (report Figures 1 and 2).
4. `METHODOLOGY.md` §2 and §3.
5. Tests: all physics monotonicity tests (8 tests).

**Definition of done:** the I–V curves look like MOSFET curves, a drive-1
inverter presents ~10 ps intrinsic delay at 0.80 V / 25 °C, and every
monotonicity test passes.

**Skills used:** semiconductor device physics, compact modelling.

---

## Student B — Design, placement, routing and DRC

**Modules:** `fabaware/design.py`, `fabaware/pd.py`

**Owns:**

- The FAB-32 netlist: 32-bit carry-select adder, ALU, FSM, pipeline register.
- Cluster hints, topological ordering, timing-endpoint extraction.
- Placement (cluster-aware serpentine row packing), wire-length estimation,
  layer assignment, buffer insertion, DRC rule deck.

**Deliverables:**

1. `design.py` producing a valid, acyclic, fully-driven netlist.
2. `pd.py` returning `PhysResult`: areas, per-net length/layer/class, buffers,
   DRC, layer utilisation, cell positions.
3. `METHODOLOGY.md` §4 and §5.
4. Tests: netlist well-formedness, placement legality, density/area behaviour,
   DRC non-negativity, the metal cross-over tests (7 tests).

**Definition of done:** the netlist is acyclic and every input is driven; all
cells land inside the die; higher density gives a smaller die; the metal-layer
cross-over behaves as documented.

**Skills used:** digital design, RTL-to-netlist concepts, physical design.

---

## Student C — Statistical timing, AI optimization, reporting

**Modules:** `fabaware/sta.py`, `fabaware/optimizer.py`, `fabaware/figure.py`,
`fabaware/report.py`, `fabaware/cli.py`, `fabaware/web.py`

**Owns:**

- The `Trial → EvalResult` contract (proposes it on day 1).
- Load-capacitance extraction, longest-path DP + back-trace.
- Monte-Carlo variability, Vmin sweep, power model, PVT corners.
- The GP + expected-improvement optimizer.
- All figures, the HTML report, `results.json`, the CLI, the dashboard.

**Deliverables:**

1. `sta.py` with `evaluate()`, `evaluate_corners()`.
2. `optimizer.py` with encode/decode and the three-phase search.
3. `figure.py` (9 charts), `report.py` (self-contained HTML + JSON).
4. `cli.py` and `web.py`.
5. `METHODOLOGY.md` §6 and §7, `VALIDATION.md`, `PRESENTATION.md`.
6. Tests: reproducibility, zero-variance consistency, optimizer behaviour,
   report integrity, fuzz robustness (19 tests).

**Definition of done:** the zero-variance Monte-Carlo test matches nominal
exactly; the optimizer beats the baseline; the report renders with all
figures embedded and no unresolved placeholders.

**Skills used:** statistics, machine learning, visualisation, tooling.

---

## Suggested timeline (6 weeks)

| Week | A | B | C |
|------|---|---|---|
| 1 | Compact model v1, library coefficients | Netlist skeleton, topological order | Interface contract, mock `evaluate()` |
| 2 | Calibration, I–V figures | FAB-32 complete | Nominal timing engine |
| 3 | Leakage model, temperature behaviour | Placement + routing | Monte-Carlo + Vmin |
| 4 | Support B/C on calibration questions | Layer assignment, buffers, DRC | Optimizer v1 (random search baseline) |
| 5 | Physics tests + docs | PD tests + docs | GP + EI, figures, report |
| 6 | Integration, final validation | Integration, final validation | Integration, final validation |

**Integrate at the end of week 2**, not week 6. The interface is one function
call; integrate it as soon as both sides are minimally functional and fix
mismatches early.

---

## Integration checklist

- [ ] `Trial` is agreed and constructed identically by all three.
- [ ] `evaluate()` accepts any `Trial` without raising (test with the extreme
      corners: all drives 1×, all drives 4×, ratio 0.8 and 1.4, density 0.55
      and 0.85).
- [ ] `EvalResult` fields are all populated; no `None` leaks into the report.
- [ ] `pytest -q` passes on all three machines with the same seed.
- [ ] `pyflakes` is clean.
- [ ] The report regenerates from scratch on a clean checkout.

---

## What to do if someone finishes early

- **A:** add a ring-oscillator or SRAM-style variation experiment; extend the
  model with gate leakage and NBTI.
- **B:** add a second benchmark design (a multiplier or an SRAM array) so the
  optimizer is validated on more than one netlist.
- **C:** add a comparison against random search and a hand-tuned expert
  configuration, so the AI result has a baseline to beat beyond "the default".

That last one is the highest-value addition for the viva: it turns "the AI did
well" into "the AI did better than these two alternatives".
