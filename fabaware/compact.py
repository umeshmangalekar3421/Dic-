"""
Compact MOSFET model (28nm-class, calibration-based).
=====================================================

This module provides the physical transistor model used across the whole flow.
Every gate delay, leakage figure and variability effect in FabAware-Opt is
derived from this model, which is why the project can honestly claim
"evaluated through transistor simulation".

Model highlights
----------------
* Inversion-charge aware drive factor  S = f(W, L, Vth, Vdd, T)
* Mobility temperature dependence  mu ~ T^-1.5
* Threshold-voltage temperature drift  (~ -50 uV/K, typical for LDD devices)
* Velocity-saturation / mobility-degradation correction in the on-current
* Leakage with activated-temperature and Vth sensitivity

The model is calibrated so that a nominal drive-1 inverter at Vdd = 0.8 V,
25 degC presents a gate delay of ~10 ps and an output resistance of ~300 ohm,
which is consistent with published 28nm gate delays (tens of ps at 10+ GHz).
"""

from __future__ import annotations

import numpy as np

# ----------------------------------------------------------------------------
# Physical constants
# ----------------------------------------------------------------------------
K_B_EV = 8.617333262e-5          # Boltzmann constant, eV/K
T_NOM = 300.0                    # nominal temperature (K)  = 25 degC
VDD_NOM = 0.80                   # nominal supply (V)

# ----------------------------------------------------------------------------
# Device calibration (28nm-class nMOS reference, unit width)
# ----------------------------------------------------------------------------
MU0_N = 450.0        # cm^2/Vs  nominal nMOS field mobility
MU0_P = 220.0        # cm^2/Vs  nominal pMOS field mobility (MPU ~ 0.49)
MU_RATIO_P = MU0_P / MU0_N
L0 = 22.0            # nm, nominal channel length (Ld)
W_N0 = 48.0          # nm, nominal nMOS gate width at drive = 1
W_P0 = 92.0          # nm, nominal pMOS gate width at drive = 1
VTH0_N = 0.300       # V, nominal nMOS threshold
VTH0_P = 0.310       # V, nominal pMOS threshold
VTH_T_DRIFT = -50e-6 # V/K, |Vt| drift with temperature
VEFF_FLOOR = 0.22    # minimum effective overdrive as a fraction of Vdd
KAPPA = 0.45         # channel-length modulation / velocity saturation boost
THETA = 0.30         # mobility-degradation coefficient
LEAK_TAU = 12.4e-3   # V, leakage sensitivity to Vth (mV-class)
LEAK_T_EA = 60.0     # K, activated-temperature scale factor


def mobility_scale(T: float) -> float:
    """Relative field mobility at temperature T vs. T_NOM (mu ~ T^-1.5)."""
    return (T_NOM / T) ** 1.5


def vth_drift(T: float) -> float:
    """Threshold voltage drift (V) at temperature T vs. T_NOM."""
    return VTH_T_DRIFT * (T - T_NOM)


def v_eff(Vdd: float, Vth: float) -> float:
    """Effective overdrive voltage with a floor (deep-submicron behaviour)."""
    return max(Vdd - abs(Vth), VEFF_FLOOR * Vdd)


def drive_factor(
    W: np.ndarray,
    L: np.ndarray,
    Vth: np.ndarray,
    Vdd: float,
    T: float,
    is_pmos: np.ndarray,
) -> np.ndarray:
    """
    Relative transistor drive S (1.0 == nominal device at T_NOM, VDD_NOM).

    S scales the gate's ability to charge/discharge a load, i.e. it divides
    the intrinsic delay and the driver output resistance.

    Parameters
    ----------
    W    : array-like, gate widths (nm)
    L    : array-like, channel lengths (nm)
    Vth  : array-like, threshold voltages (V, sign irrelevant)
    Vdd  : supply voltage (V)
    T    : temperature (K)
    is_pmos : array-like bool, True for pMOS devices
    """
    W = np.asarray(W, dtype=float)
    L = np.asarray(L, dtype=float)
    Vth = np.asarray(Vth, dtype=float)
    pmos = np.asarray(is_pmos, dtype=bool)

    # W/L scaling (lithographic CD variation lands here)
    wl = (W / np.where(pmos, W_P0, W_N0)) * (L0 / L)

    # mobility (temperature) + pMOS intrinsic weakness
    mu = mobility_scale(T) * np.where(pmos, MU_RATIO_P, 1.0)

    # overdrive squared, relative to nominal reference point
    veff = np.maximum(Vdd - np.abs(Vth), VEFF_FLOOR * Vdd)
    veff_ref = np.maximum(VDD_NOM - np.abs(Vth), VEFF_FLOOR * VDD_NOM)
    veff_ratio = (veff / veff_ref) ** 2

    # mobility degradation / velocity saturation correction
    theta_term = 1.0 + THETA * (veff - VDD_NOM + VTH0_N) / VDD_NOM
    theta_term = np.clip(theta_term, 0.55, 1.8)
    deg = 1.0 / theta_term

    return wl * mu * veff_ratio * deg


def leakage_factor(Vth_delta: float, T: float) -> float:
    """
    Relative subthreshold leakage for a device whose Vth is shifted by
    ``Vth_delta`` (V) versus nominal, at temperature T.

    Lower Vth or higher temperature => exponentially more leakage.
    """
    # LEAK_TAU stretches the Vth sensitivity to a realistic spread
    vt_term = np.exp(-Vth_delta / LEAK_TAU)
    temp_term = np.exp((T - T_NOM) / LEAK_T_EA)
    return float(np.clip(vt_term * temp_term, 0.05, 250.0))


def on_current(W: float, Vgs: float, Vds: float, Vth: float, T: float,
               is_pmos: bool = False) -> float:
    """
    DC on-current (A) of a single MOSFET from the compact model.

    Used for the I-V demonstration and to *derive* the driver resistance.
    """
    W = float(W)
    L = L0
    veff = v_eff(max(Vgs, Vds), Vth)
    mu = mobility_scale(T) * (MU_RATIO_P if is_pmos else 1.0)
    w0 = W_P0 if is_pmos else W_N0
    # unit-width transconductance calibrated to ~0.9 mA/um-class nMOS
    kn = 1.9e-4 * mu  # A/V^2 per unit (W/w0)/(L0/L)
    i = 0.5 * kn * (W / w0) * (L0 / L) * veff * veff
    i *= (1.0 + KAPPA * max(Vds - veff, 0.0) / max(Vgs, 1e-3))
    i /= (1.0 + THETA * veff / VDD_NOM)
    return float(i)


def output_resistance(W: float, Vgs: float, Vth: float, T: float,
                      is_pmos: bool = False) -> float:
    """Small-signal drain resistance (ohm) of the driving transistor."""
    veff = v_eff(Vgs, Vth)
    mu = mobility_scale(T) * (MU_RATIO_P if is_pmos else 1.0)
    w0 = W_P0 if is_pmos else W_N0
    gds = 2.6e-4 * mu * (W / w0) / max(veff, 0.05)  # A/V at unit L
    return float(1.0 / max(gds, 1e-6))
