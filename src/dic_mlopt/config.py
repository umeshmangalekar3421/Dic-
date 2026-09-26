"""Project-wide physical and flow constants.

The compact model is calibrated to publicly documented SkyWater SKY130
1.8 V regular-Vt MOSFET behaviour (sky130_fd_pr__nfet_01v8 /
pfet_01v8) and to typical 130 nm digital-CMOS textbook parameters.
It is *not* a drop-in replacement for the foundry BSIM6 model card;
it is a Digital-IC-Design-course-grade model whose FO4 delay, Ion and
Ioff sit on the published SKY130 order of magnitude.

References
----------
- SkyWater SKY130 PDK, https://github.com/google/skywater-pdk
- T. Sakurai, A. R. Newton, "Alpha-power law MOSFET model", IEEE JSSC, 1990
- M. Pelgrom et al., "Matching properties of MOS transistors", IEEE JSSC, 1989
- J. Rabaey, A. Chandrakasan, B. Nikolic, Digital Integrated Circuits
- N. Weste, D. Harris, CMOS VLSI Design
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
FIG_DIR = RESULTS_DIR / "figures"
MODEL_DIR = RESULTS_DIR / "models"
LIB_DIR = RESULTS_DIR / "liberty"
STA_DIR = RESULTS_DIR / "sta"
DOCS_DIR = ROOT / "docs"

# ---------------------------------------------------------------------------
# SKY130 1.8 V regular-Vt geometry
# ---------------------------------------------------------------------------
VDD_NOM = 1.80          # V
LMIN_UM = 0.15          # drawn L of sky130_fd_pr n/pfet_01v8
WMIN_UM = 0.42          # hd-library minimum contacted width, um
WMAX_UM = 8.00
LMAX_UM = 0.30
CELL_HEIGHT_UM = 2.72   # sky130_fd_sc_hd row height
SITE_WIDTH_UM = 0.46    # sky130_fd_sc_hd site width

# Oxide / capacitance
TOX_M = 4.14e-9
EPS_OX = 3.45e-11       # F/m, SiO2
COX_F_M2 = EPS_OX / TOX_M
# F/m² → fF/µm² is ×1e3  (1 F/m² = 1000 fF/µm²)  →  ~8.33 fF/µm²
COX_FF_UM2 = COX_F_M2 * 1e3

# Diffusion / overlap parasitics (order-of-magnitude 130 nm)
CDIFF_FF_PER_UM = 0.80     # drain diffusion, fF per um of width
COV_FF_PER_UM = 0.20       # gate overlap, fF per um of width
CFRINGE_FF_PER_UM = 0.12

# ---------------------------------------------------------------------------
# MOSFET compact-model targets (tt, 25 C, Vds = Vgs = 1.8 V, W = 1 um, L = Lmin)
# ---------------------------------------------------------------------------
IDSAT_N_A_PER_UM = 5.20e-4     # ~520 uA/um
IDSAT_P_A_PER_UM = 2.45e-4     # ~245 uA/um  (mu_n/mu_p ~ 2.1)
IOFF_N_A_PER_UM = 2.50e-10     # ~250 pA/um
IOFF_P_A_PER_UM = 1.20e-10     # ~120 pA/um

VT0_N = 0.480                  # V
VT0_P = 0.495                  # |Vt| of PMOS, V
ALPHA_N = 1.30                 # Sakurai alpha (short-channel 130 nm)
ALPHA_P = 1.35
NIDEAL_N = 1.45                # subthreshold swing factor
NIDEAL_P = 1.50
DIBL_N = 0.08                  # V/V
DIBL_P = 0.07
LAMBDA_N = 0.06                # channel-length modulation, 1/V
LAMBDA_P = 0.08

# Temperature
T0_C = 25.0
T0_K = 298.15
K_VT = -1.60e-3                # Vt temperature coefficient, V/K
MU_TEMP_EXP = 1.50             # mu ~ T^{-exp}
IOFF_TEMP_DOUBLING_C = 9.0     # rule-of-thumb leakage doubling

# Process corners (global): applied as (dVt_n, dVt_p, mu_scale)
# ss = slow NMOS + slow PMOS (higher |Vt|, lower mobility)
CORNERS = {
    "ss": {"dvt_n": +0.080, "dvt_p": +0.085, "mu_scale": 0.85, "dl_um": +0.008},
    "tt": {"dvt_n":  0.000, "dvt_p":  0.000, "mu_scale": 1.00, "dl_um":  0.000},
    "ff": {"dvt_n": -0.080, "dvt_p": -0.085, "mu_scale": 1.15, "dl_um": -0.008},
}

# Pelgrom mismatch (130 nm typical)
AVT_N_V_UM = 0.0050            # AVt, V * um
AVT_P_V_UM = 0.0054
ABETA_N = 0.010                # relative beta mismatch * um
ABETA_P = 0.012

# Target FO4 inverter delay used to pin the delay prefactor (tt, 1.8 V, 25 C)
FO4_TARGET_PS = 45.0

# ---------------------------------------------------------------------------
# Operating ranges for characterization / DOE
# ---------------------------------------------------------------------------
VDD_MIN, VDD_MAX = 1.44, 1.98          # 0.8x .. 1.1x
TEMP_GRID_C = (-40.0, 0.0, 25.0, 85.0, 125.0)
CLOAD_FF_MIN, CLOAD_FF_MAX = 0.8, 40.0
SLEW_PS_MIN, SLEW_PS_MAX = 8.0, 250.0

# ---------------------------------------------------------------------------
# Dataset / ML / optimizer
# ---------------------------------------------------------------------------
RNG_SEED = 42
N_SAMPLES_FULL = 9000
N_SAMPLES_QUICK = 3500
N_MC_FULL = 400
N_MC_QUICK = 160
NSGA_POP_FULL = 48
NSGA_GEN_FULL = 30
NSGA_POP_QUICK = 28
NSGA_GEN_QUICK = 16

TEST_SIZE = 0.18
VAL_SIZE = 0.12

# Timing spec used for cell-level yield (ps) — ~ FO4 * 1.15 at worst reasonable load
CELL_DELAY_SPEC_PS = {
    "INV": 55.0,
    "NAND2": 80.0,
    "NOR2": 125.0,
    "AOI21": 100.0,
    "OAI21": 100.0,
    "MUX2": 170.0,
    "XOR2": 180.0,
    "DFF": 180.0,
}
CELL_LEAK_SPEC_NW = {
    "INV": 8.0,
    "NAND2": 12.0,
    "NOR2": 12.0,
    "AOI21": 16.0,
    "OAI21": 16.0,
    "MUX2": 18.0,
    "XOR2": 22.0,
    "DFF": 40.0,
}

# Registered 8-bit ripple-carry adder.  A 400 MHz period is a fair
# worst-corner spec for an 8-stage RCA in 130 nm (CLA would be faster).
ADDER_PERIOD_NS = 2.50          # 400 MHz sign-off
ADDER_PERIOD_NS_STRESS = 1.60   # 625 MHz stress

# ---------------------------------------------------------------------------
# Cell list
# ---------------------------------------------------------------------------
CELL_NAMES = ("INV", "NAND2", "NOR2", "AOI21", "OAI21", "MUX2", "XOR2", "DFF")
COMBINATIONAL = ("INV", "NAND2", "NOR2", "AOI21", "OAI21", "MUX2", "XOR2")
