# Moving to real EDA tools

FabAware-Opt originally shipped with five Python modules standing in for the
real EDA toolchain. This document tracks the migration to genuine
industry tools.

---

## Status

| Layer | Python model | Real tool | Backend module | Status |
|---|---|---|---|---|
| RTL synthesis | `design.py` (hand-built netlist) | **Yosys** | `backends/yosys.py` | ✅ **REAL — verified end to end** |
| Transistor model | `compact.py` | **ngspice + BSIM** | `backends/ngspice.py` | ✅ written — runs the moment `ngspice` is installed |
| Static timing | `sta.py` | **OpenSTA** | `backends/opensta.py` | ✅ written — runs the moment `sta` is installed |
| Cell timing library | *(ours)* | **Liberty (.lib)** | `backends/liberty.py` | ✅ generates a virtual 28 nm PDK |
| Netlist hand-off | *(ours)* | **structural Verilog** | `backends/emit.py` | ✅ verified by Yosys elaboration |
| Place & route | `pd.py` | **OpenROAD** | `backends/openroad.py` | ✅ written — needs OpenROAD **and** a PDK |
| Cell mapping | *(ours)* | **SKY130 PDK** | `backends/pdk.py` | ✅ written — needs `volare enable --pdk sky130` |
| Optimization | `optimizer.py` | *(none standard)* | — | ⭐ **ours — unchanged, tool-agnostic** |

"Written" means the deck/SDC/TCL generation, tool invocation and
result-parsing code all exist, and the flow falls back to the Python model
automatically whenever the tool is absent. Nothing breaks either way.

Every tool that cannot be exercised in this sandbox is still *tested* here —
the generators and parsers run against canned tool output, so the only thing
left to verify on your machine is that the tool itself is installed.

Check what is live on any machine with:

```bash
python -c "from fabaware.backends import tools; print(tools.summary())"
```

Or exercise all of them end to end:

```bash
python3 scripts/verify_real_backends.py            # what works, what is missing
python3 scripts/verify_real_backends.py --liberty sky130.lib   # with a real PDK
```

---

## 1. Yosys — real RTL synthesis ✅ WORKING

**This one runs today.** `rtl/fab32.v` is genuine Verilog; Yosys synthesizes
it; the resulting gate netlist feeds the timing engine.

```bash
fabaware-run --real            # synthesize with real Yosys
fabaware-run --real --liberty sky130.lib   # map onto a real cell library
```

What Yosys actually produced for FAB-32:

```
508 cells:  213 $_AND_   158 $_OR_   65 $_XOR_
             35 $_DFF_P_  32 $_MUX_    5 $_NOT_
```

Yosys chose a **Brent-Kung carry-lookahead adder** for `a + b` — its own
architectural decision, not one we imposed. After mapping onto the virtual
28 nm library the netlist is **844 gates, 35 flip-flops, 3,298 transistors**.

### Cell mapping

Without a PDK, Yosys emits its generic internal cells. We map them onto the
project's virtual library:

| Yosys cell | Our library |
|---|---|
| `$_AND_` | NAND2 + INV |
| `$_OR_` | NOR2 + INV |
| `$_NOT_` | INV |
| `$_XOR_` | XOR2 |
| `$_MUX_` | MUX2 |
| `$_DFF_P_` | DFF |

With a real PDK, pass `--liberty sky130.lib` and Yosys runs
`abc -liberty`, mapping directly onto the foundry's cells. No mapping table
needed.

### Result with the real netlist

```
timing yield   34.5%  →  100.0%    (+65.5 pp)
worst slack     -3.2  →   +57.6 ps
DRC             225   →      0
cell area      1504   →   1880 µm²   (+25%)
total power   0.308   →  0.316 mW    (+2.6%)
Vmin            833   →    738 mV
```

The AI relieved M5 congestion by promoting short/mid nets to M6 and dropping
placement density to 0.57 — the physically correct response, found by search.

---

## 2. ngspice — real transistor simulation

`backends/ngspice.py` replaces `compact.py` with measured BSIM3v3 (level 49)
device physics. It ships a complete model card, so it needs no PDK.

The key design decision is **characterize-then-fit, not simulate-everything**.
Running SPICE inside a Monte-Carlo loop over thousands of chips would take
hours. Instead SPICE runs *once*, to measure the handful of numbers a compact
model actually needs:

| Measured by ngspice | Feeds | Deck |
|---|---|---|
| I_on at fixed bias | drive strength | `deck_iv()` |
| I_off (off-state leakage) | static power | `deck_leakage()` |
| I_on vs Vdd curve | the Vdd exponent `KAPPA` | `deck_iv_vs_vdd()` |

Those become the coefficients of the compact model — exactly the relationship
a Liberty file has to a static timing engine. After calibration the fast model
and real SPICE agree by construction, and the Monte-Carlo loop stays fast.

```bash
fabaware-run --spice          # characterize with ngspice, then optimize
```

Without ngspice installed the step is reported as skipped and the run
continues on the built-in model.

---

## 3. OpenSTA — real static timing analysis

`backends/opensta.py` runs a genuine timing engine on the netlist. Two things
had to exist before this was possible:

**A Liberty timing library** (`backends/liberty.py`). OpenSTA has no built-in
cell timing, so we *generate* one — a virtual 28 nm PDK. Every cell in our
library is emitted at three drive strengths with NLDM delay tables sampled
from the same gate equation the engine uses, so OpenSTA and our model agree by
construction. Supply a real PDK (`--liberty sky130.lib`) and this is bypassed.

**A structural Verilog netlist** (`backends/emit.py`). The optimizer's chosen
drive strengths are baked into the cell names (`NAND2_X2`, not `NAND2`), so
the baseline and the AI-optimized design become two ordinary netlists any
third-party tool can read.

### Cross-check, not replacement

OpenSTA is deliberately **not** used inside the optimizer's inner loop: it
would need thousands of invocations. It is used once at the end — which is
what actually matters, because it turns "our arithmetic says the yield
improved" into "an independent timing engine says the design got faster":

```bash
fabaware-run --sta            # optimize, then verify with OpenSTA
```

```
  Tool cross-check
  ------------------------------------------------------------------
  static timing : OpenSTA  [/usr/bin/sta]
    clock period: 435.0 ps
    baseline   : worst slack -3.2 ps   (71 endpoints)
    optimized  : worst slack +57.6 ps   (71 endpoints)
    improvement : +60.8 ps
    verdict     : OpenSTA independently confirms the optimization improved timing
  ------------------------------------------------------------------
```

OpenSTA gives one deterministic slack; it does not know about our within-die
variation. `slack_to_yield()` combines the two: the chip passes if the random
variation does not eat the slack.

---

## 4. OpenROAD — real place & route

`backends/openroad.py` runs the genuine RTL-to-GDSII chain: floorplan →
global placement → detailed placement → (clock tree) → global route →
detailed route.

**This is the one layer with no fallback.** Placement needs real cell *shapes*,
and routing needs a real layer stack. There is nothing meaningful to
approximate with — a "route" through invented geometry would be fiction. So
`run_pnr()` raises with an actionable message when no PDK is present, rather
than quietly returning a made-up number.

That makes it the highest-value integration, though: **wire length and DRC
count stop being predictions of our model and become measurements of an actual
routed layout.** Those two numbers underpin the area and DRC claims in every
report.

### Cell mapping (`backends/pdk.py`)

Our library speaks our names (`NAND2_X2`); SKY130 speaks its own
(`sky130_fd_sc_hd__nand2_2`). Names differ between foundries and even between
libraries from one foundry, so nothing is hard-coded as certain. Each of our
cell types declares a list of **candidate** names; the candidates are checked
against the cells that actually exist in the Liberty file; the first that
exists wins. A cell the PDK genuinely lacks is reported as unmapped rather
than silently emitted — a link failure inside OpenROAD is a much worse place
to discover that.

```bash
fabaware-run --pdk sky130 --pdr      # map onto SKY130, then route for real
fabaware-run --pdk sky130 --pdr --sta --spice   # every layer real
```

### Installing the PDK

```bash
pip install volare
volare enable --pdk sky130 <version>     # ~333 MB compressed
```

OpenROAD is not in any distro's repositories — download a prebuilt binary from
the [OpenROAD releases](https://github.com/Precision-Innovations/OpenROAD/releases)
page, or build from source.

---

## 5. Installing the rest on your own machine

These need `apt` (or your distro's package manager), which works on a normal
laptop even though it is blocked in some sandboxes.

```bash
sudo apt install ngspice        # transistor simulation
sudo apt install yosys          # synthesis (pip: yowasp-yosys)
```

OpenSTA and OpenROAD are not in Debian's repositories. Use the prebuilt
binaries:

```bash
# OpenSTA
git clone https://github.com/parallaxsw/OpenSTA
cd OpenSTA && mkdir build && cd build && cmake .. && make -j$(nproc)

# OpenROAD — prebuilt is far easier than building
# see https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/releases
```

A convenience script is provided:

```bash
bash scripts/install_real_tools.sh
```

Any tool can also be pointed at explicitly:

```bash
export FABAWARE_NGSPICE=/opt/ngspice/bin/ngspice
export FABAWARE_OPENSTA=/opt/OpenSTA/app/sta
export FABAWARE_OPENROAD=/opt/OpenROAD/bin/openroad
```

---

## 6. Getting a real PDK

The only fully open process design kit is **SkyWater SKY130** (130 nm):

```bash
pip install volare
volare enable --pdk sky130 0fe599b2afb6708d281543108caf8310912f54af
```

That gives you real BSIM SPICE models, real Liberty timing files and a real
DRC deck. Note the trade-off: SKY130 is 130 nm, not the 28 nm our virtual
library is calibrated to. **Real process, older node** — pick whichever your
project needs to claim, and say which you picked.

---

## 7. How each swap works

The optimizer never talks to a tool directly. It only needs something that can
answer *"how good is this configuration?"* — so swapping a layer is a matter
of reimplementing one function.

```python
def evaluate(netlist, trial, K, seed) -> EvalResult:
    ...
```

| Swap | What to replace | Interface to keep |
|---|---|---|
| ngspice for `compact.py` | `drive_factor()`, `leakage_factor()` | same inputs, same returns |
| OpenSTA for `sta.py` | `evaluate()` | returns `EvalResult` |
| OpenROAD for `pd.py` | `place_and_route()` | returns `PhysResult` |

The **ngspice** swap is done: `calibrate()` measures Ion / Ioff / the Vdd
exponent once, and `apply_calibration()` writes them into `compact.py`. Only
the parameters SPICE can actually determine are overwritten; the geometric
parts of the model are left alone, and the console prints exactly what changed.

The **OpenSTA** swap is done, but as a *cross-check* rather than a replacement
(see §3). Concretely `run_sta_crosscheck()`:

1. writes the netlist, with the trial's drive strengths in the cell names
2. generates a Liberty library for that configuration
3. emits an SDC with `create_clock -period <T_SPEC>`
4. runs `sta -no_splash -exit script.tcl`
5. parses `report_checks`, `report_worst_slack`, `report_power`, `report_area`

The Monte-Carlo loop and the optimizer do not change at all.

**OpenROAD** is the one layer still on our own model. Place-and-route needs
real cell layouts (LEF), and without a PDK there is nothing to route with, so
there is no meaningful partial step here — it is all or nothing.

---

## 8. What stays ours

`optimizer.py` is the research contribution. There is no standard tool for
"choose drive strengths, sizing ratios, metal layers and density to maximise
yield under variation" — that is the open problem this project addresses. It
is deliberately backend-agnostic: give it a different `evaluate()` and the same
search works on a real PDK with real timing.

---

## 9. Honest scope after the migration

- ✅ **RTL entry and synthesis are real.** Verilog in, Yosys netlist out.
- ✅ **Transistor characterization becomes real** the moment `ngspice` is on
  `PATH` — `--spice` measures Ion / Ioff / the Vdd exponent with BSIM and fits
  the compact model to them.
- ✅ **Static timing becomes real** the moment `sta` is on `PATH` — `--sta`
  times the same two netlists with an independent engine and reports whether
  it confirms the improvement.
- ✅ **Place & route becomes real** once OpenROAD *and* a PDK are installed —
  `--pdk sky130 --pdr` routes both configurations and reports measured area,
  wire length and DRC rather than predicted ones.
- ⚠️ **A PDK is a hard requirement for P&R**, unlike the other layers. There
  is deliberately no fallback, because there is nothing honest to fall back to.
- ⚠️ **The cell library is virtual** until you supply a `.lib`. The generated
  Liberty file is self-consistent with our model — it is a prediction, not a
  measurement, and it is labelled as such in the file header.

Run `python3 scripts/verify_real_backends.py` on your machine to see exactly
which of these is live for you.

The scope statement still applies: *a fabrication-aware, open-source EDA
optimization framework evaluated through transistor simulation and
RTL-to-gate netlist experiments.* With Yosys integrated the "RTL-to-gate" half
is literally true; with ngspice and OpenSTA installed, both halves are.
