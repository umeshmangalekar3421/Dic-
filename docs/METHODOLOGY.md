# Methodology

This document states every model used in FabAware-Opt, the equations behind
it, the calibration targets, and why each choice was made. If a number appears
in the report, the path from physics to that number is described here.

---

## 1. Overview of the flow

```
   compact MOSFET model  ──►  drive factor S(Vdd, T, W, L, Vth)
            │
            ├──►  gate delay  t = (A + B·Cext) / S
            │
   netlist (FAB-32)  ──►  placement ──►  routing ──►  wire RC
            │                                            │
            └──────────►  Cext  ◄────────────────────────┘
                            │
                            ▼
                 longest-path DP + back-trace  ──►  per-endpoint delay
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        nominal slack   Monte-Carlo   Vmin sweep
                        (K chips)
              └─────────────┼─────────────┘
                            ▼
                   yield / area / power / DRC
                            │
                            ▼
                  GP surrogate + expected improvement
```

Nothing in the chain is a lookup table indexed by configuration. Changing a
transistor width changes `S`, which changes gate delay, which changes the
critical path, which changes yield.

---

## 2. Compact MOSFET model (`fabaware/compact.py`)

### 2.1 Drive factor

The quantity everything downstream consumes is the *drive factor* `S`, defined
so that `S = 1` is a nominal device at 0.80 V and 300 K:

```
S = (W/W₀) · (L₀/L) · [µ(T)/µ₀] · (Veff/Veff₀)^k · θ⁻¹
```

with

| Symbol | Meaning | Value / form |
|--------|---------|--------------|
| `W₀` | nominal nMOS width | 48 nm |
| `L₀` | nominal channel length | 22 nm |
| `µ(T)/µ₀` | mobility temperature scaling | `(300/T)^1.5` |
| `Veff` | effective overdrive | `max(Vdd − |Vth|, 0.22·Vdd)` |
| `k` | overdrive exponent | **1.4** |
| `θ` | mobility-degradation correction | `1 + 0.30·(Veff − 0.50)/0.80` |

pMOS devices carry an additional factor `µp/µn ≈ 0.49`, which is why they are
slower and why the Wp/Wn ratio matters.

**Why `k = 1.4` and not 2.** The classic square-law gives `Ids ∝ Veff²`, but
that only holds for long-channel devices. In a 22 nm channel, velocity
saturation caps the carrier velocity, so the current grows far more slowly —
closer to `Veff^1.3`. The exponent 1.4 is our calibration point between the
square law (2.0) and full velocity saturation (1.0). This is not cosmetic: it
sets how sensitive timing is to supply voltage, and therefore how the Vmin
sweep behaves. Figure 2 in the report shows the resulting sub-linear
`Ids(Vdd)` curve.

**Why the overdrive floor `0.22·Vdd`.** As `Vdd` approaches `Vth`, the
square-law overdrive tends to zero and the delay would diverge. Real devices
operate in weak/moderate inversion there and still conduct. The floor keeps the
model finite and monotone across the 0.55–0.95 V sweep.

### 2.2 Threshold voltage

```
Vth(T) = Vth₀ + (−50 µV/K) · (T − 300 K) + ΔVth_global + ΔVth_local
```

The −50 µV/K drift is the standard LDD-device figure. Note the sign:
**hotter devices have a lower |Vth|**, which makes them leak more (bad) but
also switch faster. These two effects oppose each other, and the reported
corner analysis shows which one wins at 125 °C.

### 2.3 Leakage

```
I_leak ∝ exp(−ΔVth / τ) · exp((T − 300) / 60 K),   τ = 12.4 mV
```

The exponential Vth sensitivity is the reason variability is expensive: the
chips that end up fast are also the chips that leak. `τ = 12.4 mV` is chosen so
that a 3σ global Vth shift produces a realistic leakage spread rather than an
explosion.

---

## 3. Standard-cell library (`fabaware/library.py`)

Each cell carries coefficients for

```
t_stage = (A + B · Cext) / S
```

`A` is intrinsic delay, `B` is load sensitivity, `Cext` the load the cell
drives, `S` the drive factor above. Coefficients are calibrated so a drive-1
inverter at 0.80 V / 25 °C presents roughly **10 ps intrinsic delay** and
**~0.14 ps/fF** load sensitivity, consistent with published 28 nm gate speeds.
Compound cells (XOR2, MUX2, AOI22) are slower than NAND2 by the ratios you
would expect from their stack heights.

Cells also carry input capacitance, area, leakage and transistor count, all of
which scale with drive strength, so the area/power consequences of upsizing are
modelled rather than assumed.

---

## 4. Design under test (`fabaware/design.py`)

FAB-32 is built gate-by-gate from compound cells, in the way RTL elaboration
produces a netlist:

- **32-bit carry-select adder** — eight 4-bit blocks, each computing sums and
  carry for both `cin = 0` and `cin = 1` in parallel, then selecting. 8 blocks
  × 4 bits × 2 chains.
- **32-bit ALU** — add / and / or / xor, selected by a 2-bit op field.
- **4-bit counter FSM** — drives the op field; its Q outputs feed back as
  timing sources.
- **32-bit pipeline register** plus the 4-bit counter register.

466 gates, 36 flip-flops, 2 628 transistors, 70 timing endpoints.

**Why a carry-select adder.** Its critical path is a long chain of NAND2/MUX2
stages — 18–19 stages for the worst endpoints. Long chains accumulate
variation (σ scales roughly with √N for independent per-device variation, so a
19-stage path is far more variable than a 3-stage one), which makes this a
genuinely variation-sensitive test case rather than a contrived one.

---

## 5. Physical design (`fabaware/pd.py`)

### 5.1 Placement

Cells are grouped by a *functional cluster hint* assigned at netlist
construction (bit `i` of the datapath, or the FSM group) and placed in
serpentine order across standard-cell rows. This mimics the locality a real
packer achieves and, importantly, makes wire length respond to design choices:
bigger cells spread the placement and lengthen wires.

Row capacity is `n_rows × die_width`, derived from the target density:

```
core_area = cell_area / density
density ↑  ⇒  smaller die, tighter wires, more DRC
density ↓  ⇒  larger die, longer wires, more wire delay and power
```

That opposing pair is what makes density a real optimization variable, and the
optimizer does move it (0.84 → 0.67 in the reported run).

### 5.2 Routing and layer assignment

Wire length per net is approximated as half-way between the mean and the
farthest load distance:

```
L ≈ ½ · (mean_i |p_i − p_driver| + max_i |p_i − p_driver|)
```

The exact distance is recovered for single-load nets. This is the standard
half-perimeter/star hybrid used in placement-driven estimation.

Nets are split into **short / mid / long** at the 34th and 67th length
percentiles, and each class is assigned a metal layer:

| Layer | R (Ω/µm) | C (fF/µm) | Detour |
|-------|----------|-----------|--------|
| M5 | 0.150 | 0.14 | 1.00 |
| M6 | 0.090 | 0.17 | 1.10 |
| M7 | 0.055 | 0.20 | 1.22 |

**This table encodes a real trade-off, not a free win.** M7 has 2.7× lower
resistance but 43% higher capacitance per micron, and upper layers require
more jogging (detour 1.22 vs 1.00). The distributed Elmore term always
improves on upper metal:

```
t_wire = ½ · r · (L·detour)² · c
```

but the load capacitance `½·c·L·detour` seen by the driving gate gets *worse*.
So promoting long nets to M7 helps the critical path while blanket-promoting
every net to M7 does not. The test
`test_metal_layer_tradeoff_has_a_crossover` pins this behaviour down, and the
optimizer's answer (M7 for long nets) reflects it.

### 5.3 Buffer insertion

Long nets can be broken by up to 4 buffers. Each buffer splits the wire into
equal segments, converting a quadratic RC penalty into several smaller ones, at
the cost of buffer delay, area and power. This is the classic
`repeater insertion` trade-off, and again the optimizer decides.

### 5.4 DRC

A simplified rule deck reports violations for:

1. **Cell spacing** — when the target density leaves less than the 0.15 µm
   minimum gap between adjacent cells in a row.
2. **Metal utilisation** — routed length above 85% of a layer's capacity.
3. **Density window** — local density above 80%.
4. **Via crowding** — two or more layers simultaneously above 95%
   utilisation.

---

## 6. Statistical timing (`fabaware/sta.py`)

### 6.1 Nominal analysis

Longest-path dynamic programming over the gate DAG gives arrival times; each
timing endpoint (DFF D-pin or primary output) is then back-traced to recover
its critical path as an ordered list of stages plus a distributed wire term.
Slack is:

```
slack = T_spec − Σ_stages (A + B·Cext)/S − Σ_wires ½rL²c − t_setup
```

with `T_spec = 211 ps` (4.74 GHz) and `t_setup = 22 ps` for flip-flops.

### 6.2 Monte-Carlo

Each of the `K` chips draws:

| Source | Scope | σ |
|--------|-------|---|
| Gate width (CD + implant) | global | 2.8% |
| Gate length | global | 1.2% |
| Threshold voltage | global | 3.0 mV |
| Gate width | per device | 4.0% |
| Gate length | per device | 2.5% |
| Threshold voltage | per device | 4.0 mV |
| Metal RC | global | 2.0% |

Global terms are shared by every transistor on a chip (this is what makes chips
differ from each other); local terms are independent per device (this is what
makes paths within a chip differ). The distinction matters: with only global
variation every path on a chip would move together and the worst-slack
distribution would be much narrower than reality.

All `K × N_stage` delays are computed in one vectorised pass, which is why
200 chips evaluate in tens of milliseconds and the whole 40-evaluation search
finishes in seconds.

### 6.3 Vmin

For each chip, supply is swept 0.55 → 0.95 V in 50 mV steps and the lowest
voltage meeting timing is recorded. This gives a per-chip Vmin distribution —
a much more informative metric than a single worst-case corner, because it
directly measures voltage margin.

### 6.4 Power

```
P_dyn  = ½ · C_total · Vdd² · f · α
P_leak = Vdd · Σ I_leak(cell) · E[exp(−ΔVth/τ)] · exp((T−300)/60)
```

`E[exp(−ΔVth/τ)]` for `ΔVth ~ N(0, σ²)` is the exact lognormal moment
`exp(σ²/2τ²)` — computed analytically rather than sampled, so leakage does not
add Monte-Carlo noise of its own.

---

## 7. Optimization (`fabaware/optimizer.py`)

13 variables (7 cell drive strengths, Wp/Wn ratio, buffer count, 3 layer
assignments, placement density), all encoded into `[0,1]¹³`.

- **Initial design of experiments** — a scrambled Sobol sequence (space-filling,
  better than uniform random for surrogate fitting) plus the baseline and three
  hand-built heuristic seeds.
- **Surrogate** — `ConstantKernel × Matérn(ν=2.5)`, fitted to `(x, score)`.
- **Acquisition** — expected improvement with `ξ = 0.005`, maximised over a
  6 000-point scrambled Halton candidate set.
- **Refinement** — random single-coordinate perturbation around the best point.

The objective penalises area and power *beyond a budget* rather than
absolutely, so the optimizer is free to spend area and power up to the budget
and no further. Because yield is capped at 1.0 and the penalties are soft, the
search converges to a balanced point rather than to maximum slack.

---

## 8. Calibration summary

| Quantity | Target | Source of the target |
|----------|--------|----------------------|
| Gate delay, drive-1 INV, 0.80 V, 25 °C | ~10 ps | published 28 nm FO4 figures |
| Load sensitivity | ~0.14 ps/fF | derived from ~300 Ω driver resistance |
| Nominal supply | 0.80 V | 28 nm HKMG core supply |
| Channel length | 22 nm | 28 nm node drawn L |
| µp/µn | 0.49 | universal hole/electron mobility ratio |
| Vth temperature drift | −50 µV/K | standard LDD figure |
| Mobility exponent | −1.5 | phonon-scattering-limited mobility |
| Local Vth σ | 4 mV | matches reported 28 nm mismatch (Pelgrom-style scaling) |
| Target period | 211 ps (4.74 GHz) | aggressive but achievable 28 nm block |

---

## 9. Known simplifications

Stated plainly, because a credible project names its own limits:

1. **DRC is an estimator**, not a rule deck over real geometries. It captures
   the *right dependencies* (density → crowding, metal usage → utilisation)
   but its absolute counts are not sign-off numbers.
2. **Routing is estimated**, not detailed-routed. Congestion is modelled through
   a utilisation-driven detour factor rather than a global router.
3. **The placer is deterministic cluster/row packing**, not analytic placement
   with legalisation and timing-driven iteration.
4. **No crosstalk, IR-drop or clock-tree modelling.** Clock is assumed ideal.
5. **Single corner for the nominal result**; the corner analysis is reported
   separately and deterministically.

None of these undermine the research question, which is about *relative*
improvement under a consistent model. But they are the reason the scope
statement says "evaluated through transistor simulation and RTL-to-gate
netlist experiments" rather than "taped out".
