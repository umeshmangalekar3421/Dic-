"""PVT characterization of standard cells: delay, slew, energy, leakage, area.

Delay model (Weste/Harris + Sakurai)
------------------------------------
    t_50 = kappa * C_eff * Vdd / I_drive  +  k_slew * t_slew_in

I_drive is the saturation current of the conducting network, derated by
stack depth.  C_eff includes load, diffusion, overlap and Miller gate C.

Energy
------
    E_sw = C_eff * Vdd^2
    E_sc = k_sc * Vdd * I_peak * t_slew   (short-circuit)
    P_leak = I_leak_avg * Vdd

The delay prefactor ``kappa`` is pinned once so that a fanout-4 minimum
inverter at tt/1.8 V/25 C matches ``config.FO4_TARGET_PS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from dic_mlopt import config as C
from dic_mlopt.physics.cells import CELLS, StandardCell
from dic_mlopt.physics.mosfet import nmos, pmos, thermal_voltage


def _as_arr(*values):
    arrays = [np.asarray(v, dtype=float) for v in values]
    return np.broadcast_arrays(*arrays)


class DelayCalibrator:
    """Holds the dimensionless delay prefactor, computed lazily."""

    kappa: Optional[float] = None

    @classmethod
    def get(cls) -> float:
        if cls.kappa is None:
            cls.kappa = cls._solve_kappa()
        return cls.kappa

    @classmethod
    def _solve_kappa(cls) -> float:
        # Delay = kappa * t_RC + slew_tail, so a single ratio is not exact.
        k = 1.0
        for _ in range(8):
            char = CellCharacterizer(kappa=k, calibrated=True)
            fo4 = char.fo4_ps()
            if fo4 <= 1e-9:
                return 0.45
            k *= C.FO4_TARGET_PS / fo4
        return float(k)


@dataclass
class TimingResult:
    delay_rise_ps: np.ndarray
    delay_fall_ps: np.ndarray
    delay_ps: np.ndarray
    slew_out_ps: np.ndarray
    e_sw_fj: np.ndarray
    e_sc_fj: np.ndarray
    e_dyn_fj: np.ndarray
    p_leak_nw: np.ndarray
    area_um2: np.ndarray
    vm_v: np.ndarray
    cin_ff: np.ndarray
    t_setup_ps: np.ndarray
    t_hold_ps: np.ndarray
    t_cq_ps: np.ndarray


class CellCharacterizer:
    def __init__(self, kappa: Optional[float] = None, calibrated: bool = False):
        if kappa is not None:
            self.kappa = float(kappa)
        elif calibrated:
            self.kappa = 1.0
        else:
            self.kappa = DelayCalibrator.get()
        self.k_slew = 0.22          # input-slew degradation
        self.k_sc = 0.12            # short-circuit energy factor
        self.miller = 0.55

    # ------------------------------------------------------------------
    # Primitive currents / capacitors
    # ------------------------------------------------------------------
    def _corner_params(self, corner: str):
        if corner not in C.CORNERS:
            raise KeyError(f"unknown corner {corner}")
        return C.CORNERS[corner]

    def _leff(self, l_um, corner: str):
        return np.maximum(np.asarray(l_um, dtype=float) + C.CORNERS[corner]["dl_um"], 0.08)

    def cin_ff(self, wn, wp, l_um):
        wn, wp, l_um = _as_arr(wn, wp, l_um)
        cg_n = (C.COX_FF_UM2 * wn * l_um) + C.COV_FF_PER_UM * wn
        cg_p = (C.COX_FF_UM2 * wp * l_um) + C.COV_FF_PER_UM * wp
        return cg_n + cg_p

    def cdiff_ff(self, wn, wp, cell: StandardCell):
        wn, wp = _as_arr(wn, wp)
        # contacted drain on output node: ~1 diffusion per conducting network
        c_n = C.CDIFF_FF_PER_UM * wn * (1.0 + 0.4 * (cell.n_series_n - 1))
        c_p = C.CDIFF_FF_PER_UM * wp * (1.0 + 0.4 * (cell.n_series_p - 1))
        return c_n + c_p + cell.internal_cap_weight * 0.6 * (c_n + c_p)

    def area_um2(self, wn, wp, cell: StandardCell):
        """Row-based area: hd site width scaled by device count and widths."""
        wn, wp = _as_arr(wn, wp)
        n_tracks = (
            1.15
            + 0.55 * (cell.n_nmos + cell.n_pmos)
            + 0.55 * np.maximum(wn, wp) / C.WMIN_UM
            + 0.25 * (cell.n_series_n + cell.n_series_p)
        )
        if cell.is_sequential:
            n_tracks = n_tracks + 2.5
        return C.CELL_HEIGHT_UM * C.SITE_WIDTH_UM * n_tracks

    def _idsat_n(self, wn, l_um, vdd, temp_c, corner, dvt_m=0.0):
        p = self._corner_params(corner)
        le = self._leff(l_um, corner)
        return nmos.idsat(wn, le, vdd, temp_c, p["dvt_n"], dvt_m, p["mu_scale"])

    def _idsat_p(self, wp, l_um, vdd, temp_c, corner, dvt_m=0.0):
        p = self._corner_params(corner)
        le = self._leff(l_um, corner)
        return pmos.idsat(wp, le, vdd, temp_c, p["dvt_p"], dvt_m, p["mu_scale"])

    def _ioff_n(self, wn, l_um, vdd, temp_c, corner, dvt_m=0.0):
        p = self._corner_params(corner)
        le = self._leff(l_um, corner)
        return nmos.ioff(wn, le, vdd, temp_c, p["dvt_n"], dvt_m, p["mu_scale"])

    def _ioff_p(self, wp, l_um, vdd, temp_c, corner, dvt_m=0.0):
        p = self._corner_params(corner)
        le = self._leff(l_um, corner)
        return pmos.ioff(wp, le, vdd, temp_c, p["dvt_p"], dvt_m, p["mu_scale"])

    # ------------------------------------------------------------------
    # Switching threshold
    # ------------------------------------------------------------------
    def switching_threshold(self, wn, wp, l_um, vdd, temp_c, corner):
        """Vm from equated n/p alpha-power currents (sources at rails)."""
        wn, wp, l_um, vdd, temp_c = _as_arr(wn, wp, l_um, vdd, temp_c)
        p = self._corner_params(corner)
        t_k = temp_c + 273.15
        vtn = C.VT0_N + C.K_VT * (t_k - C.T0_K) + p["dvt_n"]
        vtp = C.VT0_P + C.K_VT * (t_k - C.T0_K) + p["dvt_p"]
        kn = nmos.k_drive * p["mu_scale"] * (wn / np.maximum(l_um, 0.08))
        kp = pmos.k_drive * p["mu_scale"] * (wp / np.maximum(l_um, 0.08))
        # Iterate a few times: kn (Vm-vtn)^an = kp (Vdd-Vm-vtp)^ap
        vm = 0.5 * vdd
        for _ in range(6):
            un = np.maximum(vm - vtn, 1e-3)
            up = np.maximum(vdd - vm - vtp, 1e-3)
            fn = kn * un ** C.ALPHA_N
            fp = kp * up ** C.ALPHA_P
            # Newton step on f = fn - fp
            dfn = kn * C.ALPHA_N * un ** (C.ALPHA_N - 1.0)
            dfp = -kp * C.ALPHA_P * up ** (C.ALPHA_P - 1.0)
            den = dfn - dfp
            vm = vm - np.clip((fn - fp) / np.where(np.abs(den) < 1e-18, 1.0, den), -0.3, 0.3)
            vm = np.clip(vm, 0.05, vdd - 0.05)
        return vm

    # ------------------------------------------------------------------
    # Leakage averaged over input vectors (first-order)
    # ------------------------------------------------------------------
    def leakage_w(self, cell: StandardCell, wn, wp, l_um, vdd, temp_c,
                  corner, dvt_n=0.0, dvt_p=0.0):
        i_n = self._ioff_n(wn, l_um, vdd, temp_c, corner, dvt_n)
        i_p = self._ioff_p(wp, l_um, vdd, temp_c, corner, dvt_p)
        # Average: roughly half the states leak through n-network, half through p
        # Series stacks reduce off-current when more than one device is off.
        stack_n = cell.stack_leak_factor if cell.n_series_n > 1 else 1.0
        stack_p = cell.stack_leak_factor if cell.n_series_p > 1 else 1.0
        # Device multiplicity: parallel off devices add
        n_par_n = max(cell.n_nmos / max(cell.n_series_n, 1), 1.0)
        n_par_p = max(cell.n_pmos / max(cell.n_series_p, 1), 1.0)
        i_avg = 0.5 * (i_n * n_par_n * stack_n + i_p * n_par_p * stack_p)
        if cell.is_sequential:
            i_avg = i_avg * 1.15  # always-on clock inverters
        return i_avg

    # ------------------------------------------------------------------
    # Core timing
    # ------------------------------------------------------------------
    def characterize(
        self,
        cell: StandardCell,
        wn,
        wp,
        l_um,
        vdd,
        temp_c,
        cload_ff,
        slew_ps,
        corner: str = "tt",
        dvt_n=0.0,
        dvt_p=0.0,
    ) -> TimingResult:
        wn, wp, l_um, vdd, temp_c, cload_ff, slew_ps = _as_arr(
            wn, wp, l_um, vdd, temp_c, cload_ff, slew_ps
        )
        dvt_n = np.asarray(dvt_n, dtype=float)
        dvt_p = np.asarray(dvt_p, dtype=float)

        i_n = self._idsat_n(wn, l_um, vdd, temp_c, corner, dvt_n)
        i_p = self._idsat_p(wp, l_um, vdd, temp_c, corner, dvt_p)
        # Series derating (first-order: current ~ 1/N, extra mobility loss)
        i_pd = i_n / (cell.n_series_n ** 1.05)
        i_pu = i_p / (cell.n_series_p ** 1.08)

        cin = self.cin_ff(wn, wp, l_um)
        cdiff = self.cdiff_ff(wn, wp, cell)
        c_int = cin * self.miller * 0.35 + cdiff + cell.internal_cap_weight * cin * 0.25
        c_eff = (cload_ff + c_int) * 1e-15  # F

        # 0.69 RC with Req = Vdd / I  ->  t = kappa * 0.69 * C * V / I
        k = self.kappa * 0.69
        t_fall_s = k * c_eff * vdd / np.maximum(i_pd, 1e-18)
        t_rise_s = k * c_eff * vdd / np.maximum(i_pu, 1e-18)
        t_fall_ps = t_fall_s * 1e12 + self.k_slew * slew_ps * np.sqrt(cell.logical_effort)
        t_rise_ps = t_rise_s * 1e12 + self.k_slew * slew_ps * np.sqrt(cell.logical_effort)

        # Logical-effort parasitic delay component (p * tau), tau ~ FO1/5
        tau_ps = 0.20 * (t_fall_ps + t_rise_ps) / 2.0 / max(cell.logical_effort, 0.5)
        t_fall_ps = t_fall_ps + 0.15 * cell.parasitic_delay * tau_ps
        t_rise_ps = t_rise_ps + 0.15 * cell.parasitic_delay * tau_ps

        delay_ps = 0.5 * (t_fall_ps + t_rise_ps)
        slew_out = 2.05 * delay_ps

        e_sw_j = (cload_ff + c_int) * 1e-15 * vdd ** 2
        i_peak = 0.5 * (i_pd + i_pu)
        e_sc_j = self.k_sc * vdd * i_peak * (slew_ps * 1e-12)
        e_dyn_fj = (e_sw_j + e_sc_j) * 1e15

        i_leak = self.leakage_w(cell, wn, wp, l_um, vdd, temp_c, corner, dvt_n, dvt_p)
        p_leak_nw = i_leak * vdd * 1e9
        area = self.area_um2(wn, wp, cell)
        vm = self.switching_threshold(wn, wp, l_um, vdd, temp_c, corner)

        if cell.is_sequential:
            fo1 = self._fo1_ps(wn, wp, l_um, vdd, temp_c, corner, dvt_n, dvt_p)
            t_cq = 4.4 * fo1
            t_su = 2.7 * fo1
            t_h = 0.45 * fo1
            delay_ps = t_cq
            t_rise_ps = t_cq * 1.05
            t_fall_ps = t_cq * 0.95
        else:
            t_cq = np.zeros_like(delay_ps)
            t_su = np.zeros_like(delay_ps)
            t_h = np.zeros_like(delay_ps)

        return TimingResult(
            delay_rise_ps=t_rise_ps,
            delay_fall_ps=t_fall_ps,
            delay_ps=delay_ps,
            slew_out_ps=slew_out,
            e_sw_fj=e_sw_j * 1e15,
            e_sc_fj=e_sc_j * 1e15,
            e_dyn_fj=e_dyn_fj,
            p_leak_nw=p_leak_nw,
            area_um2=area,
            vm_v=vm,
            cin_ff=cin,
            t_setup_ps=t_su,
            t_hold_ps=t_h,
            t_cq_ps=t_cq if cell.is_sequential else delay_ps * 0.0,
        )

    def _fo1_ps(self, wn, wp, l_um, vdd, temp_c, corner, dvt_n, dvt_p):
        inv = CELLS["INV"]
        cin = self.cin_ff(wn, wp, l_um)
        r = self.characterize(
            inv, wn, wp, l_um, vdd, temp_c, cin, 15.0, corner, dvt_n, dvt_p
        )
        return r.delay_ps

    def fo4_ps(self, wn=C.WMIN_UM, wp=2.0 * C.WMIN_UM, l_um=C.LMIN_UM,
               vdd=C.VDD_NOM, temp_c=C.T0_C, corner="tt") -> float:
        inv = CELLS["INV"]
        cin = self.cin_ff(wn, wp, l_um)
        r = self.characterize(inv, wn, wp, l_um, vdd, temp_c, 4.0 * cin, 20.0, corner)
        return float(np.mean(r.delay_ps))

    def characterize_named(self, name: str, **kwargs) -> TimingResult:
        return self.characterize(CELLS[name], **kwargs)


def fo4_inverter_ps(**kwargs) -> float:
    return CellCharacterizer().fo4_ps(**kwargs)


def monte_carlo_cell(
    char: CellCharacterizer,
    cell: StandardCell,
    wn: float,
    wp: float,
    l_um: float,
    vdd: float,
    temp_c: float,
    cload_ff: float,
    slew_ps: float,
    corner: str,
    n: int,
    rng: np.random.Generator,
) -> Dict[str, np.ndarray]:
    """Local Pelgrom mismatch Monte Carlo at a fixed global corner."""
    sig_n = nmos.sigma_vt(wn, l_um)
    sig_p = pmos.sigma_vt(wp, l_um)
    dvt_n = rng.normal(0.0, sig_n, size=n)
    dvt_p = rng.normal(0.0, sig_p, size=n)
    # relative beta mismatch as extra width noise
    dwn = wn * rng.normal(0.0, nmos.abeta / np.sqrt(wn * l_um), size=n)
    dwp = wp * rng.normal(0.0, pmos.abeta / np.sqrt(wp * l_um), size=n)
    r = char.characterize(
        cell,
        wn=np.maximum(wn + dwn, 0.2),
        wp=np.maximum(wp + dwp, 0.2),
        l_um=l_um,
        vdd=vdd,
        temp_c=temp_c,
        cload_ff=cload_ff,
        slew_ps=slew_ps,
        corner=corner,
        dvt_n=dvt_n,
        dvt_p=dvt_p,
    )
    return {
        "delay_ps": np.asarray(r.delay_ps, dtype=float),
        "p_leak_nw": np.asarray(r.p_leak_nw, dtype=float),
        "e_dyn_fj": np.asarray(r.e_dyn_fj, dtype=float),
        "t_setup_ps": np.asarray(r.t_setup_ps, dtype=float),
        "t_cq_ps": np.asarray(r.t_cq_ps, dtype=float),
    }
