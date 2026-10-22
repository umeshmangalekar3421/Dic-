# Complete setup, execution and tool manifest

Self-contained. Everything needed to install and run FabAware-Opt is in this
file. You can paste it to another AI, or follow it directly.

Repo: https://github.com/umeshmangalekar3421/Dic-.git
Work branch: `arena/01a0df1c-dic`  (the default `main` branch has only a README)

---

## 0. Read this first: you may already be done

The project runs **standalone**. Every real EDA tool is optional and has a
Python fallback. If you have Python plus four libraries, the whole thing runs.

| Tier | What | Needed for | Status on my machine |
|---|---|---|---|
| **1 — required** | Python 3.9+ and 4 Python libraries | *everything* | ✅ installed |
| **2 — recommended** | Yosys | `--real` (real synthesis) | ✅ installed |
| **3 — recommended** | ngspice | `--spice` (real transistor physics) | ✅ installed |
| **4 — optional** | OpenSTA | `--sta` (real timing check) | ❌ not installed |
| **5 — optional** | OpenROAD + SKY130 PDK | `--pdr` (real routing) | ❌ not installed |

**Only tier 5 is failing, and it is optional.** Tiers 1–3 give you a complete,
working, demonstrable project. Do not block on the PDK.

---

## 1. Complete installation manifest

### Tier 1 — Required (Python + 4 libraries)

| Package | Version | Size | Purpose |
|---|---|---|---|
| Python | ≥ 3.9 | — | runtime |
| numpy | ≥ 1.21 | 44 MB | Monte-Carlo arrays |
| scipy | ≥ 1.7 | 112 MB | statistics |
| scikit-learn | ≥ 1.0 | 50 MB | Gaussian-process surrogate |
| matplotlib | ≥ 3.4 | 35 MB | charts |
| pytest | ≥ 7.0 | small | running the test suite (optional) |
| flask | ≥ 2.0 | 1 MB | web dashboard only (optional) |

Total ≈ **250–320 MB**.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev,web]"
```

If pip complains about an "externally-managed-environment", that is PEP 668:
you are running pip outside the venv. Activate the venv first.

### Tier 2 — Yosys (real RTL synthesis)

```bash
sudo apt install yosys          # Debian/Ubuntu
sudo dnf install yosys          # Fedora
```
Fallback if unavailable: `pip install yowasp-yosys` (WebAssembly build, 75 MB).

Verify: `yosys -V`

### Tier 3 — ngspice (real transistor simulation)

```bash
sudo apt install ngspice
```
Verify: `ngspice -v`

This is what makes `--spice` real. It runs BSIM3v3 transistor models — BSIM
itself needs no installation, it is a ~2 KB text model card already inside
`fabaware/backends/ngspice.py`.

### Tier 4 — OpenSTA (real timing analysis) — OPTIONAL

Not in any package manager. Two routes:

```bash
# A: build from source (~10-20 min)
sudo apt install cmake swig tcl-dev libboost-all-dev
git clone --depth 1 https://github.com/parallaxsw/OpenSTA.git
cd OpenSTA && mkdir build && cd build && cmake .. && make -j$(nproc)
sudo make install

# B: use the installer helper
bash scripts/install_real_tools.sh --with-opensta
```

### Tier 5 — OpenROAD + SKY130 PDK — OPTIONAL

```bash
# PDK (~333 MB compressed download)
pip install volare
volare enable --pdk sky130 <40-char-version-hash>

# OpenROAD: prebuilt binary only, no package manager route
# https://github.com/Precision-Innovations/OpenROAD/releases
export FABAWARE_OPENROAD=/path/to/openroad
```

**This is the step that has been failing.** See the troubleshooting section.

---

## 2. Exact commands, start to finish

```bash
# --- get the code ---------------------------------------------------
cd ~
git clone https://github.com/umeshmangalekar3421/Dic-.git
cd Dic-
git checkout arena/01a0df1c-dic        # ESSENTIAL - main has only a README
git log --oneline -1                   # expect: 293685c Raise pip's network...

# --- install --------------------------------------------------------
bash scripts/install_real_tools.sh     # automated, idempotent
#   or, if the PDK download keeps failing:
bash scripts/install_real_tools.sh --no-pdk

# --- verify ---------------------------------------------------------
source venv/bin/activate
python3 scripts/verify_real_backends.py

# --- run ------------------------------------------------------------
fabaware-run                 # core flow, Python models
fabaware-run --real          # REAL Yosys synthesis
fabaware-run --real --spice  # + REAL ngspice transistor characterization
fabaware-web                 # dashboard at http://localhost:8000
pytest -q                    # 120 tests
```

`source venv/bin/activate` is needed in every new terminal.

---

## 3. What the project is

**FabAware-Opt** — AI-assisted process-variation-aware standard-cell and
physical-design optimization for improved ASIC yield.

Accurate one-line scope (use this wording; do not claim fabrication):
> *A fabrication-aware, open-source EDA optimization framework evaluated
> through transistor simulation and RTL-to-GDSII experiments.*

### The problem

Manufactured transistors are never identical. Two chips from the same design
differ slightly, so some run slower than intended and fail. The fraction that
work is the **yield**, and yield is money.

### The approach

An AI search picks 13 design settings so more chips pass. It evaluates each
candidate over a Monte-Carlo population of ~200 simulated "chips", then uses a
Gaussian-process surrogate with expected improvement to find a good answer in
~40 evaluations rather than millions.

### The 13 decision variables

- drive strength for 7 resizable cell types (NAND2, AOI22, XOR2, MUX2, A21, NAND3, BUF)
- Wp/Wn transistor width ratio
- number of inserted buffers
- metal layer for short / mid / long wires
- placement density

### Project layout

```
fabaware/
  compact.py    fast transistor model (replaced by ngspice when present)
  library.py    10-cell virtual 28 nm library
  design.py     builds the 32-bit chip netlist (replaced by Yosys when present)
  pd.py         placement + wiring estimate (replaced by OpenROAD when present)
  sta.py        statistical timing (cross-checked by OpenSTA when present)
  optimizer.py  ***OUR ACTUAL CONTRIBUTION*** - the AI search
  figure.py     9 charts
  report.py     HTML report + results.json
  cli.py        fabaware-run / fabaware-demo
  web.py        Flask dashboard
  backends/
    tools.py       auto-detects installed tools
    yosys.py       real synthesis
    ngspice.py     real BSIM transistor simulation
    opensta.py     real static timing analysis
    openroad.py    real place & route
    liberty.py     generates a Liberty timing library (virtual PDK)
    pdk.py         maps our cells onto real SKY130 cells
    emit.py        writes gate-level Verilog
    crosscheck.py  runs real tools and reports whether they agree
rtl/fab32.v       synthesizable Verilog input
tests/            120 tests
scripts/          install_real_tools.sh, verify_real_backends.py
```

### Which tool replaces which module

| Our module | Real tool |
|---|---|
| `compact.py` | ngspice + BSIM |
| `design.py` | Verilog + Yosys |
| `pd.py` | OpenROAD |
| `sta.py` | OpenSTA |
| `optimizer.py` | **nothing — this is ours** |

### Results you should see

`--real` run (verified on my machine):

| Metric | Baseline | AI-optimized |
|---|---|---|
| Timing yield | 34.5% | 100.0% (+65.5 pp) |
| Worst slack | −3.2 ps | +57.6 ps |
| DRC | 225 | 0 |
| Cell area | 1,504 µm² | 1,880 µm² (+25%) |
| Power | 0.308 mW | 0.316 mW (+2.6%) |

Default Python-netlist run: yield 29.0% → 99.5%, slack −1.7 → +14.3 ps, DRC 32 → 0.

Area and power rise while yield goes to 100% — that is the intended trade-off,
not a bug.

---

## 4. Execution order for a demonstration

1. `fabaware-run` — baseline vs AI-optimized, Python models
2. `fabaware-run --real` — same, but the netlist comes from real Yosys
3. `fabaware-run --real --spice` — adds real ngspice characterization
4. `fabaware-web` — live dashboard for the audience
5. `pytest -q` — 120 tests, evidence of correctness

Each run writes `reports/report.html` (or the `--out` directory) containing
the report and 9 charts.

---

## 5. Troubleshooting

### `pip install` fails with ReadTimeoutError / "from versions: none"

Network, not a package problem. pip's default read timeout is 15 s.

```bash
pip install --timeout 120 --retries 5 <package>
```

If still failing, pre-download then install offline:
```bash
pip download --timeout 120 -d /tmp/wh <package>
pip install --no-index --find-links /tmp/wh <package>
```

### `error: externally-managed-environment`

You are using system pip. Activate the venv: `source venv/bin/activate`.
Do **not** use `--break-system-packages` unless you understand the risk.

### `volare` will not install

It is optional and only needed for `--pdr`. Skip it:
```bash
bash scripts/install_real_tools.sh --no-pdk
```
Everything else still works.

### `apt install` fails with "Permission denied" on the lock file

Use `sudo`. If you have no sudo rights, use the pip fallbacks
(`pip install yowasp-yosys`) which need no root.

### `git clone` gives only a README

You are on `main`. Run: `git checkout arena/01a0df1c-dic`

### Python 3.14 concerns

Confirmed fine. volare's wheel is pure Python, and its C-extension
dependencies (zstandard 0.25, PyYAML 6.0.3) both publish `cp314` Linux
wheels. No compiler needed.

---

## 6. Prompt to paste to another AI

```
I need help installing a Python EDA project on my Linux laptop.
My distro is Debian/Ubuntu-based, my Python is 3.14, and I have
sudo access.

Here is the project's own setup manifest:
<paste the whole of docs/SETUP_MANIFEST.md>

What is already working on my machine:
- yosys    installed at /usr/bin/yosys
- ngspice  installed at /usr/local/bin/ngspice
- a venv exists with numpy, scipy, scikit-learn, matplotlib

What is failing:
- `pip install volare` times out reaching pypi.org with
  ReadTimeoutError (read timeout=15), and reports
  "Could not find a version that satisfies the requirement volare
   (from versions: none)"

Please help me with, in this order:
1. Decide whether I actually need volare. It is for an OPTIONAL
   place-and-route feature. Confirm what I can already do without it.
2. Fix the pip timeout problem so I can install packages reliably.
3. Give me the exact commands to verify the project runs end to end.
4. Tell me clearly which parts are optional so I stop blocking on them.

Be concrete: give me commands I can paste, and tell me what output to
expect so I can tell success from failure.
```
