# FabAware-Opt explained from zero

No prior knowledge assumed. Read this before the viva, and give it to anyone
who asks "so what does your project actually do?".

---

## Part 1 — What is a chip, in plain language

### A chip is a city of switches

A modern processor contains **billions of transistors**. A transistor is just
an electrically-controlled switch: put a voltage on its control pin (the
*gate*) and current flows between its other two pins; remove the voltage and it
stops.

Everything a computer does — adding two numbers, storing a photo, playing
audio — is built from these switches arranged into logic gates:

```
NOT   →  flips a bit
NAND  →  "not both"
XOR   →  "different"
MUX   →  "pick one of two inputs"
DFF   →  remembers one bit (memory)
```

A **standard cell** is a pre-designed, pre-measured bundle of transistors that
implements one gate. Think of them as **LEGO bricks**. Instead of designing
transistors one by one, chip designers snap together standard cells from a
library, exactly like building with LEGO instead of moulding plastic.

### How chips are made (the 30-second version)

Chips are printed, not assembled. The process is called **lithography**:

1. Start with a silicon wafer — a shiny disc.
2. Coat it with light-sensitive chemical (photoresist).
3. Shine light through a stencil (mask) that contains the pattern.
4. Wash away exposed/unexposed chemical, etch, deposit metal.
5. Repeat ~80 times to build up layers.

It is photography, except the features are **22 nanometres** wide. A nanometre
is a billionth of a metre. A human hair is about 80,000 nm wide — so a
transistor feature is roughly **1/4000th the width of a hair**.

### The unavoidable problem

At that scale you cannot place atoms perfectly. Real effects:

- The light itself blurs at the edges (diffraction).
- The number of dopant atoms in a channel is small enough that random
  counting statistics matter — one transistor might get 47 atoms, its
  neighbour 52.
- Polishing the wafer flat leaves nanometre-scale bumps.

**So no two transistors are identical, and no two chips are identical.** This
is not a defect you can engineer away. It is physics.

---

## Part 2 — The problem our project attacks

### Chips run on a clock

A chip has a clock — a signal ticking billions of times per second. Work
starts on one tick and must be finished before the next one arrives. It is a
relay race: the baton must be passed before the timer beeps.

Our target clock is **4.74 GHz**, which means one tick every **211
picoseconds**. A picosecond is a trillionth of a second. Light travels about
3 cm in that time. That is the entire budget for electricity to race through
dozens of gates.

### Now add the mess

You design **one** chip. You manufacture **millions of copies**. Because of
Part 1, every copy is slightly different:

- Chip #1 is lucky — its transistors came out fast. ✅
- Chip #2 is unlucky — slow. ❌ Fails the 211 ps deadline.
- Chip #3 is average. ✅

**Timing yield** is the percentage of chips that meet the deadline.

### Why this is a money problem

If 29% of your chips pass, you throw away 71%. On a high-volume product that
is the difference between profit and catastrophe. Yield is arguably the single
most important number in semiconductor manufacturing.

### The traditional fix, and why it is wasteful

The safe approach: **design pessimistically**. Make everything bigger and
slower than needed so that even the unlucky chips pass. Bigger transistors are
faster but cost area and power.

That works, but you pay for it everywhere — including the 99% of the chip that
did not need help. It is like armouring an entire car because one panel might
get dented.

**Our question:** can you instead be *surgical* — figure out which specific
transistors and cells actually need help, and leave the rest alone?

---

## Part 3 — What our project does, in one paragraph

We built a **computer program that simulates a chip factory's variability
problem and then solves it automatically**. No factory, no silicon, no
expensive tools — just maths on a laptop. Specifically:

1. It builds a real circuit (a 32-bit arithmetic block) out of standard cells.
2. It simulates the physics of each transistor.
3. It manufactures **hundreds of imaginary chips**, each one randomly
   different, and checks which ones meet the 211 ps deadline.
4. It lets an **AI search** adjust the design — transistor sizes, cell
   strengths, wiring layers, layout density — and repeat the test.
5. It reports which configuration gives the best yield for the least area and
   power.

**The result on our default run:** timing yield goes from **29% → 99.5%**,
worst-case slack from **−1.7 ps → +14.3 ps**, and DRC violations from
**32 → 0**. The cost: **+21.6% area** and **+48.3% power**.

---

## Part 4 — How it does it: the five layers

Think of it as a stack. Each layer feeds the next.

```
 ⑤  AI search          optimizer.py    "which settings should we try next?"
 ④  Stress test        sta.py          "how many chips survive?"
 ③  Layout & wiring    pd.py           "where do cells go, how are they wired?"
 ②  The circuit        design.py       "what are we building?"
 ①  Transistor physics compact.py      "how fast is one transistor?"
```

### ① Transistor physics — `compact.py`

Everything starts here. This module answers: *given a transistor of width W
and length L, at voltage Vdd and temperature T, how fast does it switch and
how much current does it leak?*

Real effects it models:

| Effect | What it means | Why it matters |
|---|---|---|
| Mobility vs temperature | Electrons move sluggishly when hot | Hot chips are slower |
| Threshold drift | The switch-on voltage shifts ~−50 µV per °C | Changes both speed and leakage |
| Velocity saturation | Past a point, more voltage gives less current | Makes voltage scaling less effective |
| Leakage vs threshold | Lower threshold → exponentially more leakage | Fast chips leak badly |

**Why this layer matters:** it is the difference between a real model and a
fake one. If this were just a lookup table, changing a transistor size would
not change timing and the whole project would be theatre. Because delays are
*computed from physics*, a change in width genuinely propagates through to
yield.

Our calibration target: a basic inverter should switch in about **10
picoseconds** at 0.80 V and room temperature. That is the published figure for
a 28 nm manufacturing process.

### ② The circuit under test — `design.py`

We need something real to optimize. We built **FAB-32**, a 32-bit datapath:

- a **carry-select adder** — adds two 32-bit numbers fast
- an **ALU** — does add / AND / OR / XOR
- a **counter** (a tiny state machine) that chooses the operation
- a **pipeline register** — 32 flip-flops holding the result

**466 gates, 36 flip-flops, 2,628 transistors, 70 timing endpoints.**

Why an adder? Because its critical path is a long chain — about 19 gates in a
row. Long chains accumulate variation: 19 slightly-wrong transistors in
sequence is far riskier than 3. It is a genuinely hard case, which makes it a
good test.

### ③ Layout and wiring — `pd.py`

Now we place those 466 cells on a flat surface and wire them up.

- **Placement**: cells are grouped by function (bit 0's logic together, bit
  1's together...) and packed into rows, the way a real layout tool clusters
  related logic to keep wires short.
- **Wiring**: we estimate each wire's length, then convert that to
  **resistance and capacitance**. A long wire is like a thin, clogged pipe —
  it takes time to push a signal through.
- **Metal layers**: chips have ~10 stacked metal layers. Upper layers are
  thicker (lower resistance) but need more jogging to reach. We let the AI
  choose which layer each net uses.
- **Density**: how tightly to pack cells. Tighter = smaller chip but more
  crowding and more design-rule violations.
- **DRC**: *Design Rule Check* — the manufacturer's rulebook ("no wire closer
  than X nanometres to another"). Break the rules and the chip won't
  manufacture. We count violations with a simplified rule deck.

### ④ The stress test — `sta.py`

This is the heart. It answers: *how many imaginary chips survive?*

**Step A — nominal timing.** Trace every possible path through the circuit and
find the slowest one. That is the critical path. Its delay versus the 211 ps
budget is the **slack**:

```
slack = 211 ps − (how long the slowest path takes)

slack > 0  →  chip meets timing  ✅
slack < 0  →  chip is too slow   ❌
```

**Step B — Manufacture 200 imaginary chips.** For each one, randomly perturb
every transistor — but do it in two carefully different ways:

| Type | Scope | Effect |
|---|---|---|
| **Global** | Every transistor on the chip shifts together | Makes whole *chips* fast or slow |
| **Local** | Each transistor varies independently | Makes *paths within one chip* differ |

This distinction is the subtle part and it matters. With only global
variation, all paths on a chip would move in lockstep. Real chips have both,
and the mix determines how wide the timing spread is.

**Step C — Count survivors.** A chip passes only if *every one* of its 70
timing endpoints meets the deadline. Count the passers → that is the yield.

**Step D — Find each chip's Vmin.** For each chip, slowly lower the supply
voltage and find the point where it stops working. This measures **voltage
margin**: how much headroom you have in the field.

### ⑤ The AI search — `optimizer.py`

We now have a way to score any configuration. There are **13 knobs**:

| Knob | Range |
|---|---|
| Drive strength for 7 resizable cell types | 1× / 2× / 4× |
| Wp/Wn transistor sizing ratio | 0.80 – 1.40 |
| Buffers on long wires | 0 – 4 |
| Metal layer for short / mid / long nets | M5 / M6 / M7 |
| Placement density | 0.55 – 0.85 |

**Why we cannot just try everything.** Even at 3 settings each, 3¹³ is over a
million combinations — and **each evaluation is expensive** (it means
manufacturing and timing 200 imaginary chips). At ~0.1 s each, a million
evaluations is 28 hours.

**So we use a surrogate.** The idea:

1. Try a handful of configurations spread across the space (a *Sobol
   sequence* — a smarter version of random sampling).
2. Fit a **Gaussian process** — a machine-learning model that, from few data
   points, predicts the score *and* how uncertain it is about that
   prediction.
3. Use that model to pick the most promising next configuration to actually
   test (**expected improvement** — balances "go where the score looks good"
   against "go where we are most uncertain").
4. Test it for real, add the result, update the model, repeat.

This is called **Bayesian optimization**. It found our answer in **43
evaluations** instead of a million — about 3 seconds.

The score it maximises is deliberately not just "yield":

```
score = yield
        − 2.5 × (area overshoot beyond 1.30× the baseline)
        − 2.5 × (power overshoot beyond 1.50× the baseline)
        − 0.15 × (DRC violations / 100)
```

**This is why the result is interesting.** The AI stopped at 99.5% yield
instead of chasing 100%, because it was not allowed to spend unlimited area.
It bought the yield that mattered and then stopped.

---

## Part 5 — Reading the result

| Metric | Baseline | Optimized | What it means |
|---|---|---|---|
| Timing yield | 29.0% | 99.5% | Out of 200 chips, passers went 58 → 199 |
| Worst-case slack | −1.7 ps | +14.3 ps | From just missing to comfortably meeting |
| DRC violations | 32 | 0 | From un-manufacturable to clean |
| Cell area | 1,167 µm² | 1,419 µm² | +21.6% — the price |
| Total power | 0.214 mW | 0.317 mW | +48.3% — the price |
| Mean Vmin | 836 mV | 798 mV | 38 mV more voltage margin |

**Was it just "make everything bigger"?** No — and this is the best question
anyone can ask you. The AI left **71% of cells at their original size** and
only upsized the ones near the critical path. It also *loosened* the placement
density (0.84 → 0.67), which shortens wires and **saves** delay. A naive
"everything 4×" configuration scores much worse — you can run it and see.

---

## Part 6 — How this connects to the real world

### It is pure software

Nothing to plug in. It runs on any laptop — about **5 seconds**, CPU only, no
GPU. Your i7 with integrated graphics is more than enough; the heavy lifting is
NumPy matrix maths.

### What in our project is genuinely real

- **The physics equations** are the real ones used in industry compact models.
- **The methods** — Monte-Carlo statistical timing, critical-path analysis,
  Elmore wire delay, buffer insertion, Bayesian optimization — are all
  standard industry practice.
- **The trade-offs are real.** Upper metal having lower resistance but higher
  capacitance; upsizing costing area and power; density trading die size
  against routability. The optimizer rediscovers these from the physics
  rather than being told them.
- **The numbers are calibrated** to published 28 nm figures: ~10 ps gate
  delay, 0.80 V supply, 22 nm channel length.

### What is deliberately simplified (and why)

| Simplified | What industry uses | Why we did not |
|---|---|---|
| Our own compact model | **BSIM** models from the foundry | Requires a licensed PDK |
| Estimated wire routing | Detailed global + track routing (OpenROAD, Innovus) | Needs a full router |
| Simplified DRC deck | **Calibre / Assura** on real geometry | Needs real layout polygons |
| Our own timing engine | **OpenSTA, PrimeTime, Tempus** | Ours is educational, theirs are sign-off |
| "Generic 28 nm" | A specific foundry process | Real PDKs are under NDA |

**The honest framing**, which you should use verbatim:

> FabAware-Opt is a fabrication-aware, open-source EDA optimization framework
> evaluated through transistor simulation and RTL-to-gate netlist experiments.
> It does **not** fabricate a chip, and it does not replace sign-off tools.

### How you would connect it to the real toolchain

This is the most valuable thing to understand, because it shows our work is not
a dead end — it plugs into a real pipeline.

**Today's open-source chip design flow (all free, all real):**

```
Your Verilog code
      ↓  Yosys          (turns code into gates)
Gate-level netlist
      ↓  OpenROAD       (placement, routing, timing)
Physical layout
      ↓  KLayout        (view it, run DRC)
GDSII  →  send to a fab
```

With an open PDK (**SkyWater SKY130**, 130 nm, fully open source) you can
actually get chips fabricated today — for free, through Google's shuttle
programmes.

**Where our pieces slot in:**

| Our module | Real-world equivalent | How to swap |
|---|---|---|
| `compact.py` | ngspice + BSIM models | Replace with real SPICE; keep the interface |
| `design.py` | Verilog → Yosys | Write FAB-32 in Verilog, synthesise it |
| `pd.py` | OpenROAD / RePlAce + TritonRoute | Use OpenROAD's real placer/router |
| `sta.py` | **OpenSTA** | Load the real liberty/SPICE models, run real STA |
| `optimizer.py` | (nothing standard!) | **This is the reusable research contribution** |

That last row is the point. The first four layers are simplified versions of
tools that already exist and are better than ours. **The optimizer is the part
that is genuinely ours** — and it does not care what is underneath it, as long
as something can answer "score this configuration". Swap in OpenSTA and a real
PDK, and the same AI search would work on a real design.

### The real devices this affects

Every chip you own went through exactly this problem:

- **Phone SoC** (Snapdragon, Apple A-series, Dimensity) — billions of
  transistors, and binning decisions (which chips become the "Pro" model) are
  made from this kind of variation analysis.
- **Laptop CPU** — your i7 was likely *binned*: chips that came out fast and
  low-leakage become higher-tier parts.
- **Car electronics** — must work at −40 °C and +125 °C, which is exactly the
  temperature sweep we report.
- **Memory, GPUs, AI accelerators, medical implants** — all of it.

When you hear "TSMC 3 nm yield is 55%", that number is precisely what our
`yield_nom` is a small, simplified version of.

---

## Part 7 — The 60-second viva answer

> "Chips are manufactured with unavoidable atomic-scale variation, so
> identical designs produce chips with different speeds. Slow chips miss their
> clock deadline and get thrown away, which costs money. Our project simulates
> this: we model transistor physics, build a 32-bit datapath, manufacture
> hundreds of randomly-different virtual chips, and measure how many meet
> timing. Then a Gaussian-process optimizer searches 13 design parameters —
> transistor sizing, cell drive strengths, metal layers, layout density — to
> maximise yield within area and power budgets. We took a baseline at 29% yield
> and got it to 99.5% for 21% more area. It is a simulation framework, not a
> tape-out: it's evaluated through transistor simulation and RTL-to-gate
> netlist experiments, and every number is reproducible from a seed."

---

## Glossary

| Term | Meaning |
|---|---|
| **ASIC** | A chip designed for one specific purpose (as opposed to a general CPU) |
| **PDK** | Process Design Kit — the foundry's rulebook and transistor models |
| **Standard cell** | A pre-designed logic gate, like a LEGO brick |
| **Drive strength** | How big a cell's transistors are; bigger = faster but larger |
| **Slack** | Time margin: deadline minus actual delay. Negative = fail |
| **Critical path** | The slowest path through a circuit; sets the max clock speed |
| **Setup time** | How long a flip-flop's input must be stable before the clock edge |
| **Timing yield** | Percentage of manufactured chips that meet the timing spec |
| **PVT** | Process, Voltage, Temperature — the three sources of variation |
| **Corner** | A specific PVT combination, e.g. "slow-slow, 0.75 V, 125 °C" |
| **Monte Carlo** | Estimating by random sampling — here, simulating many random chips |
| **DRC** | Design Rule Check — does the layout obey the fab's manufacturing rules |
| **Elmore delay** | Formula for how long a signal takes to cross a resistive/capacitive wire |
| **Vmin** | Lowest supply voltage at which a chip still works |
| **Leakage** | Current a transistor wastes even when switched off |
| **RTL** | Register-Transfer Level — hardware described in code (Verilog) |
| **GDSII** | The file format describing a finished chip layout, sent to the fab |
| **Surrogate model** | A cheap approximation of an expensive function, used to guide search |
| **Expected improvement** | A rule for choosing where to sample next in Bayesian optimization |
