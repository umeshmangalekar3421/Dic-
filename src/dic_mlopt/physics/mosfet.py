"""Alpha-power + subthreshold compact MOSFET model, SKY130-calibrated.

Strong inversion (Sakurai alpha-power law)
------------------------------------------
    I_dsat = k * mu_T * (W/L) * (Vgs - Vt)^alpha * (1 + lambda * Vds)

Subthreshold
------------
    I_sub  = I0 * (W/L) * exp((Vgs - Vt + eta*Vds) / (n * vT))
             * (1 - exp(-Vds / vT))

Vt includes temperature, global process and Pelgrom mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dic_mlopt import config as C

Q_E = 1.602176634e-19
K_B = 1.380649e-23


def thermal_voltage(temp_c):
    t_k = np.asarray(temp_c, dtype=float) + 273.15
    return K_B * t_k / Q_E


def mu_scale_temp(temp_c, mu_scale=1.0):
    t_k = np.asarray(temp_c, dtype=float) + 273.15
    return np.asarray(mu_scale, dtype=float) * (C.T0_K / t_k) ** C.MU_TEMP_EXP


@dataclass
class MOSFET:
    name: str
    vt0: float
    alpha: float
    nideal: float
    dibl: float
    lam: float
    avt: float
    abeta: float
    idsat_a_per_um: float
    ioff_a_per_um: float
    is_nmos: bool

    def __post_init__(self):
        # k such that I_dsat(W=1 um, L=Lmin, Vgs=Vds=VDD, tt, 25 C) matches target
        # Use the same Vt (with DIBL) that ids() will see at Vds = VDD.
        vt_on = self.vt0 - self.dibl * C.VDD_NOM
        vov = C.VDD_NOM - vt_on
        self.k_drive = (
            self.idsat_a_per_um
            * C.LMIN_UM
            / ((vov ** self.alpha) * (1.0 + self.lam * C.VDD_NOM))
        )
        # I0 such that I_sub(Vgs=0, Vds=VDD, W=1 um, L=Lmin) matches Ioff
        vth = thermal_voltage(C.T0_C)
        exp_term = np.exp((-self.vt0 + self.dibl * C.VDD_NOM) / (self.nideal * vth))
        one_m = 1.0 - np.exp(-C.VDD_NOM / vth)
        self.i0 = self.ioff_a_per_um * C.LMIN_UM / (exp_term * one_m)

    def vt_eff(self, temp_c, dvt_process=0.0, dvt_mismatch=0.0, vds=0.0):
        t_k = np.asarray(temp_c, dtype=float) + 273.15
        vt = (
            self.vt0
            + C.K_VT * (t_k - C.T0_K)
            + np.asarray(dvt_process, dtype=float)
            + np.asarray(dvt_mismatch, dtype=float)
            - self.dibl * np.asarray(vds, dtype=float)
        )
        return vt

    def sigma_vt(self, w_um, l_um):
        we = np.maximum(np.asarray(w_um, dtype=float), 0.05)
        le = np.maximum(np.asarray(l_um, dtype=float), 0.05)
        return self.avt / np.sqrt(we * le)

    def ids(self, vgs, vds, w_um, l_um, temp_c, dvt_process=0.0,
            dvt_mismatch=0.0, mu_scale=1.0):
        """Drain current (A). Vectorized. vds, vgs are magnitudes for both n and p."""
        vgs = np.asarray(vgs, dtype=float)
        vds = np.abs(np.asarray(vds, dtype=float))
        w = np.asarray(w_um, dtype=float)
        l = np.maximum(np.asarray(l_um, dtype=float), 0.05)
        vt = self.vt_eff(temp_c, dvt_process, dvt_mismatch, vds=vds)
        vth = thermal_voltage(temp_c)
        mu = mu_scale_temp(temp_c, mu_scale)
        vov = vgs - vt

        # Subthreshold exponential is only valid for Vgs ≲ Vt.  Cap the
        # argument at 0 so strong-inversion points cannot overflow.
        sub_arg = np.clip((vgs - vt) / (self.nideal * vth), -50.0, 0.0)
        i_sub = (
            self.i0
            * (w / l)
            * np.exp(sub_arg)
            * (1.0 - np.exp(-np.maximum(vds, 0.0) / np.maximum(vth, 1e-6)))
        )
        i_sat = (
            self.k_drive
            * mu
            * (w / l)
            * np.maximum(vov, 0.0) ** self.alpha
            * (1.0 + self.lam * vds)
        )
        # Smooth blend around threshold so IV plots look physical
        blend = 1.0 / (1.0 + np.exp(-vov / (3.0 * vth)))
        i_on = blend * i_sat + (1.0 - blend) * i_sub
        # Triode compression when Vds < Vdsat ~ vov / alpha
        vdsat = np.maximum(vov / max(self.alpha, 1.0), 0.05)
        triode = np.clip(vds / vdsat, 0.0, 1.0)
        #  (2 - vds/vdsat) * (vds/vdsat)  MOS linear-region shape, clipped
        shape = np.where(triode < 1.0, (2.0 - triode) * triode, 1.0)
        return np.maximum(i_on * shape, 0.0)

    def idsat(self, w_um, l_um, vdd, temp_c, dvt_process=0.0,
              dvt_mismatch=0.0, mu_scale=1.0):
        return self.ids(
            vgs=vdd, vds=vdd, w_um=w_um, l_um=l_um, temp_c=temp_c,
            dvt_process=dvt_process, dvt_mismatch=dvt_mismatch, mu_scale=mu_scale,
        )

    def ioff(self, w_um, l_um, vdd, temp_c, dvt_process=0.0,
             dvt_mismatch=0.0, mu_scale=1.0):
        return self.ids(
            vgs=0.0, vds=vdd, w_um=w_um, l_um=l_um, temp_c=temp_c,
            dvt_process=dvt_process, dvt_mismatch=dvt_mismatch, mu_scale=mu_scale,
        )


nmos = MOSFET(
    name="nfet_01v8",
    vt0=C.VT0_N,
    alpha=C.ALPHA_N,
    nideal=C.NIDEAL_N,
    dibl=C.DIBL_N,
    lam=C.LAMBDA_N,
    avt=C.AVT_N_V_UM,
    abeta=C.ABETA_N,
    idsat_a_per_um=C.IDSAT_N_A_PER_UM,
    ioff_a_per_um=C.IOFF_N_A_PER_UM,
    is_nmos=True,
)

pmos = MOSFET(
    name="pfet_01v8",
    vt0=C.VT0_P,
    alpha=C.ALPHA_P,
    nideal=C.NIDEAL_P,
    dibl=C.DIBL_P,
    lam=C.LAMBDA_P,
    avt=C.AVT_P_V_UM,
    abeta=C.ABETA_P,
    idsat_a_per_um=C.IDSAT_P_A_PER_UM,
    ioff_a_per_um=C.IOFF_P_A_PER_UM,
    is_nmos=False,
)


def calibrate_drive():
    """Return measured Ion/Ioff at the calibration point (sanity helper)."""
    ion_n = nmos.idsat(1.0, C.LMIN_UM, C.VDD_NOM, C.T0_C)
    ion_p = pmos.idsat(1.0, C.LMIN_UM, C.VDD_NOM, C.T0_C)
    ioff_n = nmos.ioff(1.0, C.LMIN_UM, C.VDD_NOM, C.T0_C)
    ioff_p = pmos.ioff(1.0, C.LMIN_UM, C.VDD_NOM, C.T0_C)
    return {
        "ion_n_uA_per_um": float(ion_n * 1e6),
        "ion_p_uA_per_um": float(ion_p * 1e6),
        "ioff_n_pA_per_um": float(ioff_n * 1e12),
        "ioff_p_pA_per_um": float(ioff_p * 1e12),
    }
