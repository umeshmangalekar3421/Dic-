# How CellForge connects to internships and placement

This is the document to read the night before a Qualcomm / Intel / NVIDIA /
Synopsys / Cadence / TI / NXP / Samsung interview.

## What those teams actually hire interns to do

They do **not** hire B.Tech students to invent a new ISA. They hire them to:

- characterize or consume **standard cells**
- close **timing** at ss/125 °C
- write **Python around EDA tools**
- try **ML where SPICE is too slow**

CellForge is a portable, NDA-free version of that loop. In the interview you
are not “a student with a course project”. You are someone who has already
walked the path their intern will walk in week two, minus the PDK.

## Role → what you open on screen

| Role | Open this tab | Sentence |
|---|---|---|
| Library characterization | Live lab + Library | “I generate NLDM-class delay vs slew/load, under ss/tt/ff, and emit `.lib`.” |
| STA intern | STA | “Setup check is t_cq + combo + t_su. This 8-bit RCA is 614 MHz tt, 426 MHz ss, 96 % yield at 400 MHz.” |
| CAD / EDA software | Models + Industry table | “The sizer cannot call SPICE 10k times. HistGB R² 0.96 sits inside NSGA-II; the knee is physics-signed-off.” |
| ML for silicon / DTCO | Models + Pareto | “Yield is an objective, not a afterthought. Permutation importance recovers Cload, W, L, corner — the α-power law.” |
| RTL/physical design | STA + limits | “I know why OpenROAD/GDS is a different class of problem and I did not fake it.” |

## Companies where this language is native

Qualcomm, Intel, NVIDIA, AMD, Broadcom, MediaTek, Apple silicon, Google Silicon,
NXP, Texas Instruments, Analog Devices, Samsung LSI, Cadence, Synopsys,
Siemens EDA, and in India additionally: Qualcomm Bangalore, Intel, TI Bangalore,
Samsung Noida, NXP Noida, Cadence Noida, Synopsys Bangalore, Micron.

## Two-minute live demo (memorize)

1. Launch `python -m dic_mlopt lab`. Open **Live lab**.
2. Cell = NAND2. Move VDD 1.8 → 1.5. Delay goes up. Switch corner to **ss**. Delay jumps again.
   *“That is process × voltage. This is why we characterize at corners, not at tt only.”*
3. **Devices** → subthreshold. *“Leakage is exponential in T. ff/hot is a power problem.”*
4. **Library**. Point at INV min yield 0 vs ML-opt 100 %.
   *“Min-size fails the delay spec. Logical-effort balanced is already close. ML is the last 10–20 % plus yield.”*
5. **Models**. HistGB 0.96 vs Ridge 0.68.
   *“We do not replace physics. We replace *repeated* physics inside the optimizer.”*
6. **STA**. 8-bit RCA. *“Ripple carry is slow on purpose. Next conversation is CLA / PPA.”*
7. **Limits**, unprompted. Compact MOS, no SPEF, ideal clock.
   *“When I get PDK access I swap the compact model for BSIM and the STA for PrimeTime. The loop stays.”*

## What not to claim

- Do not say “I did SKY130 tapeout” or “this is foundry-accurate”.
- Do not say “I used OpenROAD” — you deliberately did not, and that is a strength.
- Do not hide that DFF setup/hold is FO1-derived.

Honesty is how CAD managers decide you will not poison a library.

## Resume one-liners (also in `RESUME.md`)

See `docs/RESUME.md`. LinkedIn featured project: this README + a 30 s screen
capture of the live lab sliders.
