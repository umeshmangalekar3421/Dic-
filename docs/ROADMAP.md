# Roadmap (what was kept, what was cut, why)

## Original idea

Machine-learning-assisted optimization of standard-cell libraries under
PVT, using SKY130 + Magic + KLayout + ngspice + Yosys + OpenROAD + OpenSTA.

## What a Digital IC Design examiner actually grades

1. MOSFET current and delay under V, T, process.
2. Standard-cell topologies (INV, NAND, NOR, AOI, MUX, XOR, DFF).
3. Characterization → Liberty.
4. Variation (corners + mismatch) and yield.
5. A timed block (STA) that consumes the library.

Layout GDS and a full OpenROAD place-and-route are **physical-design**
topics; they do not change the ML-sizing result and they are the part
that fails on a student laptop.

## Cuts (risk removal)

| Item | Why it was removed |
|------|--------------------|
| Full SKY130 PDK tarball | Several GB, version hell, not needed once Ion/Ioff/FO4 are pinned |
| Magic / KLayout layouts | No PEX, no extra grade, extra install |
| OpenROAD RTL-to-GDS | 20–50 GB, hours, frequent route failures |
| Yosys / OpenSTA as *required* binaries | Platform-specific builds; Python STA reads the same NLDM tables |
| ngspice as *required* | Optional netlists are shipped; Python compact model is the engine |

## Kept and strengthened

- SKY130 1.8 V geometry and Ion/Ioff/FO4 targets.
- α-power + subthreshold MOSFET (Sakurai) + Pelgrom mismatch.
- DOE dataset generation (no public sizing dataset exists).
- HistGB surrogate vs Ridge / RF baselines.
- NSGA-II yield-aware sizing with physics Monte-Carlo sign-off.
- NLDM Liberty writer.
- Registered 8-bit ripple-carry adder STA + block-level yield.

## Hardware envelope

Lenovo IdeaPad Slim 3i, Core i7-13th gen, Intel graphics, ~100 GB free.

- RAM: well under 2 GB.
- Disk: < 200 MB including `.venv`.
- GPU: not used.
- OS: Windows or Linux, Python 3.10+.

## One-command path

```text
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     (Windows)
.venv/bin/pip install -r requirements.txt         (Linux)
python run_project.py
```

Open `docs/REPORT.html` and `docs/SLIDES.html`.
