"""
Real ngspice / BSIM backend  (replaces the compact Python MOSFET model).
========================================================================

Uses the genuine ngspice circuit simulator with a BSIM3 (level 49) MOSFET
model to **characterize** the technology, then feeds those measurements into
the fast analytical model that drives the Monte-Carlo loop.

Why characterize instead of simulating everything
-------------------------------------------------
A full Monte-Carlo run needs tens of thousands of transistor-level
simulations — far too slow to run in ngspice. That is not a workaround, it is
**exactly what the industry does**: SPICE characterizes the cells once, the
results are written into a Liberty timing model, and static timing analysis
uses that model. We do the same, except the "Liberty file" is our compact
model's coefficient set.

So SPICE supplies the numbers we previously had to assume:

* on-current per unit width  -> anchors gate drive strength
* leakage per unit width     -> anchors static power
* the velocity-saturation exponent (I_on vs Vdd) -> replaces a hand-tuned 1.4
* gate capacitance from tox   -> anchors input capacitance

Running it
----------
    from fabaware.backends import ngspice
    ngspice.calibrate()                      # uses the built-in model card
    ngspice.calibrate(model="sky130.lib")    # or a real PDK
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple

from . import tools

# ---------------------------------------------------------------------------
# A generic 28nm-class BSIM3v3 (level 49) model card.
#
# This lets ngspice run with no PDK at all. Numbers are representative of a
# 28nm HKMG process. If you have a real PDK, pass model="<path>.lib" and this
# card is not used.
# ---------------------------------------------------------------------------
BSIM3_CARD = """\
* ------------------------------------------------------------------
* Generic 28nm-class BSIM3v3 model card (FabAware-Opt fallback).
* Representative parameters - NOT a foundry model.
* Replace with a real PDK (e.g. SkyWater SKY130) for real numbers.
* ------------------------------------------------------------------
.MODEL NMOS NMOS LEVEL=49
+ VERSION=3.3      TOX=1.4E-9     XJ=1.0E-8     NCH=2.2E17
+ VTH0=0.30        K1=0.42        K2=0.02       K3=0.0
+ DVT0=2.8         DVT1=0.45      DVT2=-0.05
+ U0=0.0450        UA=-1.0E-10    UB=2.0E-18    UC=0.0
+ VSAT=8.0E4       A0=1.0         KETA=-0.05    RDSW=180
+ UTE=-1.5         KT1=-0.11      KT1L=0.0      KT2=0.022
+ PRWG=0.0         PRWB=0.0       WR=1.0
+ W0=1.0E-8        LINT=2.0E-9    DLC=2.0E-9
+ CGSL=0.0         CGDL=0.0       CKAPPA=0.6    CF=0.0
+ CLC=1.0E-7       CLE=0.6        DLCIG=0.0
+ NOFF=1.0         VOFF=-0.10     NFACTOR=1.2
+ ETA0=0.08        ETAB=-0.07     PCLM=1.3      PDIBLC1=0.1
+ DROUT=0.56       PSCBE1=4.24E8  PSCBE2=1.0E-5
+ KT1=-0.11        AT=3.3E4       PRT=0.0
+ NJTS=1.0         NJTSSW=1.0     NJS=1.0       NJSW=1.0
+ XTIS=3.0         XTID=3.0       JTSS=0.0
.MODEL PMOS PMOS LEVEL=49
+ VERSION=3.3      TOX=1.4E-9     XJ=1.0E-8     NCH=1.9E17
+ VTH0=-0.31       K1=0.40        K2=0.02       K3=0.0
+ DVT0=2.8         DVT1=0.45      DVT2=-0.05
+ U0=0.0210        UA=-1.2E-10    UB=2.4E-18    UC=0.0
+ VSAT=7.0E4       A0=1.0         KETA=-0.05    RDSW=320
+ UTE=-1.5         KT1=-0.11      KT2=0.022
+ PRWG=0.0         PRWB=0.0       WR=1.0
+ W0=1.0E-8        LINT=2.0E-9    DLC=2.0E-9
+ CGSL=0.0         CGDL=0.0       CKAPPA=0.6    CF=0.0
+ CLC=1.0E-7       CLE=0.6
+ NOFF=1.0         VOFF=-0.10     NFACTOR=1.2
+ ETA0=0.08        ETAB=-0.07     PCLM=1.3      PDIBLC1=0.1
+ DROUT=0.56       PSCBE1=4.24E8  PSCBE2=1.0E-5
+ AT=3.3E4         PRT=0.0
+ NJTS=1.0         NJTSSW=1.0     NJS=1.0       NJSW=1.0
+ XTIS=3.0         XTID=3.0       JTSS=0.0
"""

#: SiO2 permittivity (F/m), for the analytic gate-capacitance estimate
EPS_SIO2 = 3.453e-11
TOX_DEFAULT = 1.4e-9


# ---------------------------------------------------------------------------
# deck generation  (pure functions - testable without ngspice)
# ---------------------------------------------------------------------------

def deck_iv(
    w_nm: float = 48.0,
    l_nm: float = 22.0,
    vgs_start: float = 0.30,
    vgs_stop: float = 0.80,
    vgs_step: float = 0.10,
    vds: float = 0.80,
    vdd: float = 0.80,
    temp_c: float = 25.0,
    pmos: bool = False,
    model: Optional[str] = None,
) -> str:
    """Build a deck that sweeps Vgs and prints the drain current each time."""
    dev = "PMOS" if pmos else "NMOS"
    card = f".include {model}" if model else BSIM3_CARD
    vds_val = f"{-abs(vds):.6g}" if pmos else f"{abs(vds):.6g}"
    start, stop, step = vgs_start, vgs_stop, vgs_step
    # pMOS is driven with negative gate/source voltages
    alter_vgs = "alter Vgs = -1.0 * vv" if pmos else "alter Vgs = vv"
    lines = [
        "* FabAware-Opt: I-V characterization (generated)",
        card,
        "",
        f"Vds  d  0  {vds_val}",
        "Vgs  g  0  0.0",
        "Vs   s  0  0",
        "Vb   b  0  0",
        "",
        f"M1 d g s b {dev} W={w_nm:.6g}n L={l_nm:.6g}n",
        "",
        ".control",
        "set nobreak",
        f"let vv = {start:.6g}",
        f"while vv <= {stop + step * 1e-6:.6g}",
        f"    {alter_vgs}",
        "    op",
        "    print i(Vds)",
        f"    let vv = vv + {step:.6g}",
        "end",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def deck_leakage(
    w_nm: float = 48.0,
    l_nm: float = 22.0,
    vdd: float = 0.80,
    temp_c: float = 25.0,
    pmos: bool = False,
    model: Optional[str] = None,
) -> str:
    """Build a deck that measures off-state (subthreshold) leakage."""
    dev = "PMOS" if pmos else "NMOS"
    card = f".include {model}" if model else BSIM3_CARD
    vds_val = f"{-abs(vdd):.6g}" if pmos else f"{abs(vdd):.6g}"
    return "\n".join([
        "* FabAware-Opt: leakage measurement (generated)",
        card,
        "",
        f"Vds  d  0  {vds_val}",
        "Vgs  g  0  0.0",
        "Vs   s  0  0",
        "Vb   b  0  0",
        "",
        f"M1 d g s b {dev} W={w_nm:.6g}n L={l_nm:.6g}n",
        "",
        ".control",
        "set nobreak",
        "op",
        "print i(Vds)",
        ".endc",
        ".end",
        "",
    ])


def deck_iv_vs_vdd(
    w_nm: float = 48.0,
    l_nm: float = 22.0,
    vdd_start: float = 0.55,
    vdd_stop: float = 0.95,
    vdd_step: float = 0.05,
    temp_c: float = 25.0,
    pmos: bool = False,
    model: Optional[str] = None,
) -> str:
    """Build a deck sweeping Vdd=Vgs=Vds - used to fit the drive exponent."""
    dev = "PMOS" if pmos else "NMOS"
    card = f".include {model}" if model else BSIM3_CARD
    alter_vds = "alter Vds = -1.0 * vv" if pmos else "alter Vds = vv"
    alter_vgs = "alter Vgs = -1.0 * vv" if pmos else "alter Vgs = vv"
    return "\n".join([
        "* FabAware-Opt: I-V vs Vdd (velocity-saturation fit)",
        card,
        "",
        "Vds  d  0  0.8",
        "Vgs  g  0  0.8",
        "Vs   s  0  0",
        "Vb   b  0  0",
        "",
        f"M1 d g s b {dev} W={w_nm:.6g}n L={l_nm:.6g}n",
        "",
        ".control",
        "set nobreak",
        f"let vv = {vdd_start:.6g}",
        f"while vv <= {vdd_stop + vdd_step * 1e-6:.6g}",
        f"    {alter_vds}",
        f"    {alter_vgs}",
        "    op",
        "    print i(Vds)",
        f"    let vv = vv + {vdd_step:.6g}",
        "end",
        ".endc",
        ".end",
        "",
    ])


# ---------------------------------------------------------------------------
# output parsing  (pure functions - testable with canned ngspice output)
# ---------------------------------------------------------------------------

#: matches  i(vds) = -1.234567e-04    /    i(vds) = 1.23e-04
_CURRENT_RE = re.compile(r"i\(\s*v\w*\s*\)\s*=\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)",
                         re.I)


def parse_currents(text: str) -> List[float]:
    """Extract every ``i(Vxx) = <value>`` printed by ngspice, in order."""
    return [float(m.group(1)) for m in _CURRENT_RE.finditer(text)]


def parse_iv(text: str, vgs_values: Sequence[float]) -> List[Tuple[float, float]]:
    """Pair each swept Vgs with the measured |Ids|."""
    cur = parse_currents(text)
    n = min(len(cur), len(vgs_values))
    return [(float(vgs_values[i]), abs(cur[i])) for i in range(n)]


def fit_exponent(vdds: Sequence[float], ions: Sequence[float]) -> float:
    """
    Fit ``I_on ~ Vdd^k`` in log-log space.

    This replaces the hand-tuned velocity-saturation exponent in
    ``fabaware.compact`` with a value measured from real device physics.
    """
    import numpy as np
    x = np.asarray(list(vdds), dtype=float)
    y = np.asarray([abs(v) for v in ions], dtype=float)
    ok = (x > 0) & (y > 0)
    if ok.sum() < 2:
        return float("nan")
    k, _ = np.polyfit(np.log(x[ok]), np.log(y[ok]), 1)
    return float(k)


def gate_cap_per_um2(tox: float = TOX_DEFAULT) -> float:
    """Gate capacitance per unit area (F/um^2) from the oxide thickness."""
    return EPS_SIO2 / tox * 1e-12      # F/m -> F/um^2


# ---------------------------------------------------------------------------
# execution  (needs ngspice)
# ---------------------------------------------------------------------------

def run_deck(deck: str, workdir: str = "build", name: str = "spice") -> str:
    """Write a deck, run ngspice on it, return stdout."""
    exe = tools.find("ngspice")
    if exe is None:
        raise RuntimeError(
            "ngspice not found. Install it with:\n"
            "    sudo apt install ngspice\n"
            "    bash scripts/install_real_tools.sh\n"
            "or set FABAWARE_NGSPICE=/path/to/ngspice"
        )
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, f"{name}.sp")
    with open(path, "w") as f:
        f.write(deck)
    proc = subprocess.run([exe, "-b", "-o", os.path.join(workdir, f"{name}.out"),
                           path],
                          capture_output=True, text=True, timeout=600)
    out_path = os.path.join(workdir, f"{name}.out")
    if os.path.exists(out_path):
        return open(out_path).read() + (proc.stdout or "")
    if proc.returncode != 0:
        raise RuntimeError(f"ngspice failed (rc={proc.returncode}):\n"
                           f"{(proc.stdout or '')[-1500:]}"
                           f"{(proc.stderr or '')[-1500:]}")
    return proc.stdout or ""


def measure_iv(
    w_nm: float = 48.0,
    l_nm: float = 22.0,
    vgs_values: Optional[Sequence[float]] = None,
    vds: float = 0.80,
    temp_c: float = 25.0,
    pmos: bool = False,
    model: Optional[str] = None,
) -> List[Tuple[float, float]]:
    """Sweep Vgs with real ngspice and return [(vgs, |Ids|), ...]."""
    if vgs_values is None:
        vgs_values = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
    vgs_values = list(vgs_values)
    step = (vgs_values[1] - vgs_values[0]) if len(vgs_values) > 1 else 0.1
    deck = deck_iv(w_nm=w_nm, l_nm=l_nm,
                   vgs_start=vgs_values[0], vgs_stop=vgs_values[-1],
                   vgs_step=step, vds=vds, temp_c=temp_c,
                   pmos=pmos, model=model)
    out = run_deck(deck, name="iv")
    return parse_iv(out, vgs_values)


def measure_leakage(
    w_nm: float = 48.0, l_nm: float = 22.0, vdd: float = 0.80,
    temp_c: float = 25.0, pmos: bool = False, model: Optional[str] = None,
) -> float:
    """Off-state leakage (A) of a single device, from real ngspice."""
    deck = deck_leakage(w_nm=w_nm, l_nm=l_nm, vdd=vdd, temp_c=temp_c,
                        pmos=pmos, model=model)
    out = run_deck(deck, name="leak")
    cur = parse_currents(out)
    return abs(cur[0]) if cur else float("nan")


def measure_exponent(
    w_nm: float = 48.0, l_nm: float = 22.0,
    vdds: Optional[Sequence[float]] = None,
    temp_c: float = 25.0, pmos: bool = False, model: Optional[str] = None,
) -> float:
    """Measure the I_on(Vdd) exponent k, replacing the hand-tuned value."""
    if vdds is None:
        vdds = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    vdds = list(vdds)
    step = (vdds[1] - vdds[0]) if len(vdds) > 1 else 0.05
    deck = deck_iv_vs_vdd(w_nm=w_nm, l_nm=l_nm, vdd_start=vdds[0],
                          vdd_stop=vdds[-1], vdd_step=step,
                          temp_c=temp_c, pmos=pmos, model=model)
    out = run_deck(deck, name="vexp")
    return fit_exponent(vdds, parse_currents(out))


def calibrate(
    w_nm: float = 48.0,
    l_nm: float = 22.0,
    vdd: float = 0.80,
    model: Optional[str] = None,
) -> Dict[str, float]:
    """
    Characterize the technology with real ngspice.

    Returns a dict of calibration constants that can be pushed into
    ``fabaware.compact``; see :func:`apply_calibration`.
    """
    iv_n = measure_iv(w_nm, l_nm, vdd=vdd, pmos=False, model=model)
    iv_p = measure_iv(w_nm, l_nm, vdd=vdd, pmos=True, model=model)
    ion_n = iv_n[-1][1] if iv_n else float("nan")
    ion_p = iv_p[-1][1] if iv_p else float("nan")
    return {
        "i_on_n_A": ion_n,
        "i_on_p_A": ion_p,
        "mu_ratio_p": (ion_p / ion_n) if ion_n else float("nan"),
        "i_leak_n_A": measure_leakage(w_nm, l_nm, vdd, pmos=False, model=model),
        "i_leak_p_A": measure_leakage(w_nm, l_nm, vdd, pmos=True, model=model),
        "vexp_n": measure_exponent(w_nm, l_nm, pmos=False, model=model),
        "vexp_p": measure_exponent(w_nm, l_nm, pmos=True, model=model),
        "cox_F_per_um2": gate_cap_per_um2(),
        "w_nm": w_nm,
        "l_nm": l_nm,
    }


def apply_calibration(cal: Dict[str, float]) -> Dict[str, float]:
    """
    Push SPICE-measured constants into the compact model.

    Only the parameters that SPICE can actually determine are overwritten;
    the geometric/relative parts of the model are left alone. Returns what
    changed so the console can report it honestly.
    """
    from .. import compact
    changed: Dict[str, float] = {}
    mr = cal.get("mu_ratio_p")
    if mr and mr == mr and 0.05 < mr < 0.95:
        compact.MU_RATIO_P = float(mr)
        changed["MU_RATIO_P"] = float(mr)
    k = cal.get("vexp_n")
    if k and k == k and 0.8 < k < 2.2:
        from .. import sta
        sta.EXP_VEFF = float(k)
        changed["EXP_VEFF"] = float(k)
    return changed
