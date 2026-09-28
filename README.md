# CellForge

**PVT-robust standard-cell characterization, ML sizing, Liberty and STA.**
Open source. SKY130-calibrated. Runs on a laptop. Built to be demoed.

CellForge is the industrial standard-cell loop — characterize under process/voltage/temperature, fit a delay surrogate, size transistors for yield, emit NLDM Liberty, time a netlist — without a foundry NDA or a 40 GB OpenROAD install.

It is the artefact you open in an intern interview at Qualcomm, Intel, NVIDIA, Synopsys or Cadence and *drive*.

---

## Run the product (this is the demo)

Windows (IdeaPad Slim 3i or any PC):

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python cellforge.py lab
```

Or double-click `run_lab.bat`.

Then open the URL the terminal prints. You get a live lab:

- **Live lab** — drag Wn, VDD, temperature, corner; delay / leakage / yield update in milliseconds
- **Devices** — NMOS I–V and subthreshold (the “why ff burns and ss is slow” plot)
- **Library** — min vs logical-effort vs ML-opt, physics-signed-off
- **Models** — HistGB R² 0.96 vs Ridge 0.68
- **STA** — registered 8-bit ripple-carry adder, Fmax vs PVT, downloadable `.lib`
- **Industry** — which intern roles this maps to, and the 2-minute talk track

CLI without the UI:

```powershell
.venv\Scripts\python cellforge.py fo4
.venv\Scripts\python cellforge.py char --cell NAND2 --wn 1.6 --wp 2.1 --corner ss --temp 125
.venv\Scripts\python cellforge.py run          # regenerate dataset, models, report
```

No GPU. No PDK tarball. No Docker. Python 3.10+.

---

## What it is

| Stage | Industry tool | CellForge |
|---|---|---|
| Device model | BSIM6 under NDA | Sakurai α-power + subthreshold, **pinned to SKY130 Ion / Ioff / FO4** |
| Characterization | Cadence Liberate / Synopsys SiliconSmart | Vectorized DOE, 9 000 PVT × sizing points |
| Variation | Corners + Pelgrom MC | ss/tt/ff + σVt = AVt/√(WL) |
| Surrogate | Internal GBDT delay models | HistGB, test R² **0.962** |
| Sizing | Multi-objective cell sizer | NSGA-II: delay, energy, 1−yield |
| Delivery | Liberty NLDM | `results/liberty/*.lib` |
| Sign-off | PrimeTime / Tempus | Python STA of a registered 8-bit RCA |

**Deliberately not included:** Magic/KLayout GDS, OpenROAD place-and-route, foundry BSIM. Those are physical-design and NDA problems. They do not change the characterization/ML/STA story and they will not fit a student laptop. See `docs/ROADMAP.md`.

---

## Headline numbers

From the last full run (`results/metrics.json`):

| | |
|---|---|
| FO4 inverter, tt 1.8 V 25 °C | **45.0 ps** (pinned) |
| FO4 ss 1.62 V 125 °C | 83 ps |
| FO4 ff 1.98 V −40 °C | 26 ps |
| Ion n/p | 520 / 245 µA/µm |
| Delay surrogate R² / MAE | **0.962** / 8.2 ps |
| Ridge baseline R² | 0.681 |
| Leakage surrogate R² | 0.967 |
| ML-opt cell yield (8 cells) | 100 % |
| 8-bit RCA Fmax tt / ss | **614 / 426 MHz** |
| Block yield @ 400 MHz | **96.4 %** (P5 Fmax 403 MHz) |

---

## Why this gets interviews

Library, STA and CAD internships do not ask you to tape out a SoC. They ask whether you can:

1. Talk about **FO4, logical effort, NLDM, setup checks, ss/tt/ff** without notes.
2. Explain **why a min-size inverter fails yield** and what you do about it.
3. Show **code that produces a `.lib` and a WNS number**.
4. Be honest about **what is not BSIM / not SPEF**.

That is this repo. Mapping to roles, companies and a 2-minute demo script: `docs/INDUSTRY.md`. Resume bullets: `docs/RESUME.md`. Viva/interview Q&A: `docs/VIVA.md`.

---

## Architecture

```
MOSFET compact model (SKY130-pinned)
        │
        ▼
 Latin-hypercube PVT × sizing DOE          ← Liberate-class data
        │
        ▼
 HistGB delay / energy / leakage           ← surrogate
        │
        ▼
 NSGA-II (delay, energy, 1−yield)          ← sizer
        │
        ▼
 Physics Monte-Carlo sign-off of the knee
        │
        ▼
 NLDM Liberty  +  8-bit RCA STA            ← PrimeTime-class check
        │
        ▼
 CellForge lab (this UI)  +  REPORT.html
```

Python API:

```python
from dic_mlopt.service import characterize_point, fo4_ps, sweep

print(fo4_ps())  # 45.0
print(characterize_point("NAND2", wn_um=1.6, wp_um=2.1, corner="ss", temp_c=125))
```

---

## Repository

```
app/web/                CellForge lab UI
app/server.py           FastAPI
src/dic_mlopt/          physics, DOE, ML, NSGA-II, Liberty, STA, CLI
results/                precomputed metrics, figures, .lib, models
docs/REPORT.html        academic write-up (print to PDF if a course asks)
docs/SLIDES.html        talk deck
docs/INDUSTRY.md        intern / placement mapping
docs/RESUME.md          copy-paste bullets
spice/                  optional ngspice (not required)
```

---

## Hardware envelope

Lenovo IdeaPad Slim 3i, Core i7-13th gen, Intel graphics, ~100 GB free: **in budget**.
RAM < 2 GB. Disk < 200 MB + `.venv`. No GPU.

---

## License

MIT. Not a foundry sign-off tool. Numbers are SKY130-**calibrated**, not SKY130-**extracted**.
