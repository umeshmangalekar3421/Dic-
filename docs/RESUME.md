# Resume / LinkedIn / mail — copy-paste

Replace `[CellForge]` with the GitHub URL of this repo.

## Resume — 4 bullets (VLSI / CAD / STA intern)

- Built **CellForge**, an open-source SKY130-calibrated standard-cell lab: PVT characterization, HistGB delay/leakage surrogate (test R² 0.96 vs Ridge 0.68), yield-aware NSGA-II sizing, NLDM Liberty generation, and STA of a registered 8-bit ripple-carry adder.
- Implemented a Sakurai α-power + subthreshold MOSFET model pinned to public SKY130 Ion/Ioff (520/245 µA/µm) and FO4 = 45 ps; ss/tt/ff corners and Pelgrom mismatch (σVt = AVt/√WL).
- Closed an 8-bit RCA at **614 MHz tt / 426 MHz ss** with **96 % Monte-Carlo yield at 400 MHz**; emitted Liberty for three corners.
- Shipped a live Python/FastAPI lab (drag VDD, W, temperature, corner → delay/yield in ms) used as an intern-interview demo of the Liberate → sizer → PrimeTime loop.

## Resume — shorter (one bullet)

- CellForge: SKY130-calibrated cell characterization + ML sizing + Liberty/STA (FO4 45 ps, delay R² 0.96, 8-bit RCA 614 MHz tt) — open-source stand-in for the library-team loop.

## LinkedIn About (3 lines)

I build tools around digital CMOS. CellForge is a laptop-scale, open-source stand-in for the standard-cell loop used in library and STA teams: PVT characterization, an ML delay surrogate, yield-aware transistor sizing, Liberty, and block-level timing. Looking for internships in library characterization, STA, CAD/EDA or ML-for-silicon.

## LinkedIn project title

CellForge — PVT-robust standard-cell lab (SKY130-calibrated)

## Mail to a recruiter / hiring manager (short)

Subject: intern — library / STA / CAD — CellForge

I am a Digital IC student. I built CellForge, an open-source flow that characterizes CMOS cells under PVT, trains a delay surrogate (R² 0.96), sizes for yield, writes Liberty and times an 8-bit adder (614 MHz tt). It is the Liberate → sizer → PrimeTime loop without an NDA. I can demo the live lab in 10 minutes. Repo: [url]
