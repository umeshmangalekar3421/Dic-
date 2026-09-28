# Moving to real EDA tools

FabAware-Opt originally shipped with five Python modules standing in for the
real EDA toolchain. This document tracks the migration to genuine
industry tools.

---

## Status

| Layer | Python model | Real tool | Status |
|---|---|---|---|
| RTL synthesis | `design.py` (hand-built netlist) | **Yosys** | ✅ **REAL — working** |
| Transistor model | `compact.py` | **ngspice + BSIM** | 🔧 backend written, needs ngspice on your machine |
| Static timing | `sta.py` | **OpenSTA** | 🔧 backend written, needs OpenSTA binary |
| Place & route | `pd.py` | **OpenROAD** | 🔧 backend written, needs OpenROAD |
| Optimization | `optimizer.py` | *(none standard)* | ⭐ **ours — unchanged, tool-agnostic** |

"Backend written" means the detection, invocation and result-parsing code
exists and the flow falls back to the Python model automatically whenever the
tool is absent. Nothing breaks either way.

Check what is live on any machine with:

```bash
python -c "from fabaware.backends import tools; print(tools.summary())"
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

## 2. Installing the rest on your own machine

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

## 3. Getting a real PDK

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

## 4. How each swap works

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

Concretely, an OpenSTA backend would:

1. write the netlist and the trial's drive strengths to a Verilog netlist
2. emit an SDC with `create_clock -period <T_SPEC>`
3. run `sta -no_splash -exit script.tcl`
4. parse `report_timing` and `report_power` back into `EvalResult`

The Monte-Carlo loop and the optimizer would not change at all.

---

## 5. What stays ours

`optimizer.py` is the research contribution. There is no standard tool for
"choose drive strengths, sizing ratios, metal layers and density to maximise
yield under variation" — that is the open problem this project addresses. It
is deliberately backend-agnostic: give it a different `evaluate()` and the same
search works on a real PDK with real timing.

---

## 6. Honest scope after the migration

- ✅ **RTL entry and synthesis are real.** Verilog in, Yosys netlist out.
- ⚠️ **Timing, layout and DRC are still our models** until ngspice / OpenSTA /
  OpenROAD are installed. The numbers they produce are consistent and
  calibrated, but they are not sign-off numbers.
- ⚠️ **The cell library is virtual** until you supply a `.lib`.

The scope statement still applies: *a fabrication-aware, open-source EDA
optimization framework evaluated through transistor simulation and
RTL-to-gate netlist experiments.* With Yosys integrated, the "RTL-to-gate"
half of that sentence is now literally true.
