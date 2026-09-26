# Presenting FabAware-Opt

How to demo it, what to say, and the questions to expect.

---

## The one-sentence framing

> *"We built an open-source framework that models how manufacturing variation
> affects chip timing, and used a Gaussian-process optimizer to pick transistor
> sizes, cell drive strengths and physical-design parameters that raise timing
> yield from 29% to 99.5% without blowing the area or power budget."*

Then immediately state what it is **not**:

> *"To be precise: this is a fabrication-aware optimization framework evaluated
> through transistor simulation and RTL-to-gate netlist experiments. It does
> not fabricate a chip."*

Saying this before you are asked is worth more than saying it after.

---

## Live demo (5 minutes)

### Option A — the dashboard (recommended)

```bash
fabaware-web          # open http://localhost:8000
```

Click **Run optimization**. The log scrolls live, the cards fill in, and nine
figures render. Total time about 5 seconds, so you can re-run with different
chip counts and seeds during questions.

### Option B — the terminal demo

```bash
python -c "from fabaware.cli import demo; demo(['-K','400'])"
```

This walks through the exact four steps in the brief:

1. **A normal standard-cell configuration** — worst slack −1.7 ps
2. **A manufacturing-variation stress test** — 400 chips, only 27% pass
3. **The AI-optimized configuration** — the search runs and prints its choice
4. **Comparison** — area, power, delay, yield, DRC, worst-case slack

### Option C — the report

```bash
fabaware-run --chips 200
open reports/report.html
```

A single self-contained HTML file (no internet, no external assets) with every
figure embedded. This is the artefact to submit.

---

## The four slides that matter

**Slide 1 — the problem.** A chip designed at nominal conditions is not the
chip you get. Every transistor on every die differs slightly; long paths
accumulate those differences. Show report Figure 3: the baseline slack
distribution straddling the spec line, with most chips on the wrong side.

**Slide 2 — the approach.** Physics → netlist → statistical timing → AI search.
Emphasise that delays are *derived from a compact MOSFET model*, not looked up,
so transistor-level choices actually reach the timing numbers.

**Slide 3 — the result.** The comparison table. Yield 29% → 99.5%, slack
−1.7 → +14.3 ps, DRC 32 → 0, area +21.6%, power +48.3%. Note that the optimizer
*stopped* at 99.5% instead of spending more area — that is the budgeted
objective working as designed.

**Slide 4 — the trade-off.** Show the Pareto plot (Figure 9) and the metal-layer
cross-over. This is where you show it is not just "make everything bigger":
M7 is better for long wires and worse for short ones, and the optimizer found
the split.

---

## Questions you will be asked

**"Did you actually fabricate this?"**
No, and we don't claim to. It is a simulation framework evaluated through
transistor simulation and RTL-to-gate netlist experiments. The models are
calibrated to published 28 nm figures and the numbers are reproducible from a
seed. `VALIDATION.md` §7 lists exactly what has not been validated.

**"How do you know your model is right?"**
Three answers. (1) Every monotonicity property physics requires is pinned by a
test: mobility falls with temperature, lower Vth leaks more, 2× width gives
exactly 2× drive, hot is slower than cold. (2) The Monte-Carlo engine is
checked against the deterministic solver — set all σ to zero and they agree to
1e-6 ps. (3) The corner ordering FF > TT > SS and −40 °C > 25 °C > 125 °C is
verified. That does not make the model *exact*; it makes it *consistent and
physically sound*. The honest gap is that we have no SPICE or commercial-STA
cross-check, because that needs a licensed PDK.

**"Is this just making all the cells bigger?"**
No. Look at the chosen configuration: NAND2 stays at 1×, MUX2 stays at 1×,
while AOI22, XOR2 and NAND3 go to 2×. The optimizer left 71% of the cell
instances alone and sized the ones on or near the critical path. It also moved
placement density from 0.84 to 0.67, which *shrinks* wire delay, and it
promoted only the long nets to M7. A naive "everything 4×" configuration scores
much worse — you can run it and see.

**"Why not just use a bigger safety margin / lower the clock?"**
That is exactly the engineering alternative, and it is worth naming: you can
buy yield with frequency. The point of this work is that you can buy it more
cheaply by choosing *where* to spend area and power. A good extension is to
report the frequency the baseline would need to match 99.5% yield, versus the
area the optimizer spent — that converts the result into a
frequency-per-area trade-off.

**"Why a Gaussian process and not a neural network?"**
Because evaluations are precious. Each one is a full Monte-Carlo statistical
timing run, so we get tens of samples, not millions. A GP gives us a calibrated
uncertainty estimate from a few dozen points, which is what expected
improvement needs. A neural network would be a poor fit at this sample size.
An honest extension is to compare GP-EI against random search and against a
hand-tuned expert configuration.

**"Your optimized design still fails the slow-slow and 125 °C corners — isn't
that a problem?"**
It's a real observation, and the report says so explicitly (Figure 7's caption
is generated from the data, so it can never claim something the numbers don't
support). The resolution is about what the objective *is*: the optimizer
maximizes Monte-Carlo timing yield at the nominal operating point (0.80 V,
25 °C), which is the metric the project is about. The deterministic corners are
a separate, stricter check reported alongside. Every corner *improves* — SS
goes −27.3 → −8.3 ps and 125 °C goes −61.7 → −38.6 ps — but meeting them would
require optimizing for the worst corner instead, which is a different
objective. If you want to pre-empt this entirely, add the corners to the
objective as a penalty and re-run; the framework supports that in a few lines.

**"How long does it take?"**
About 5 seconds for the full flow on a laptop — 43 statistical-timing
evaluations over 200 Monte-Carlo chips. CPU-only NumPy, no GPU.

**"What would you do next?"**
Compare against random search and an expert-tuned baseline (so the AI result
has something to beat); add a second benchmark design so the result is not
specific to FAB-32; and add gate leakage and NBTI to the device model.

---

## Pitfalls to avoid

1. **Don't say "we designed a chip" or "our chip yields 99.5%".** Say "our
   model predicts 99.5% timing yield for this configuration".
2. **Don't claim the DRC count is a sign-off number.** It comes from a
   simplified analytic rule deck. Say so.
3. **Don't hide the power cost.** Area went up 21.6% and power 48.3%. The claim
   is that this is *proportionate* — the yield went from 29% to 99.5% — not
   that it was free.
4. **Have a re-run ready.** If someone challenges a number, re-run with a
   different seed live. The dashboard makes this a one-click demo, and it is
   much more convincing than defending a static table.

---

## Artefacts to submit

| File | What it is |
|------|-----------|
| `reports/report.html` | self-contained report, all figures embedded |
| `reports/results.json` | every number, machine-readable |
| `README.md` | the pitch, quick start, scope |
| `docs/METHODOLOGY.md` | models, equations, calibration |
| `docs/VALIDATION.md` | what was verified |
| `docs/TEAM.md` | who did what |
| `pytest -q` output | 34 passing tests |
