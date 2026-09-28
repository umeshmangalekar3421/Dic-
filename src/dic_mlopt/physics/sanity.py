"""Physical sanity checks. Fail loud if the compact model is unphysical."""

from __future__ import annotations

from dic_mlopt import config as C
from dic_mlopt.physics.cells import CELLS
from dic_mlopt.physics.characterize import CellCharacterizer
from dic_mlopt.physics.mosfet import calibrate_drive, nmos


class SanityError(RuntimeError):
    pass


def _chk(cond: bool, msg: str):
    if not cond:
        raise SanityError(msg)


def run_sanity() -> dict:
    ion = calibrate_drive()
    _chk(400 < ion["ion_n_uA_per_um"] < 700, f"Ion_n out of SKY130 band: {ion}")
    _chk(150 < ion["ion_p_uA_per_um"] < 400, f"Ion_p out of SKY130 band: {ion}")
    _chk(50 < ion["ioff_n_pA_per_um"] < 2000, f"Ioff_n out of band: {ion}")

    char = CellCharacterizer()
    fo4 = char.fo4_ps()
    _chk(25.0 < fo4 < 80.0, f"FO4 {fo4:.1f} ps is not a 130 nm number")

    fo4_ss = char.fo4_ps(corner="ss", temp_c=125.0, vdd=1.62)
    fo4_ff = char.fo4_ps(corner="ff", temp_c=-40.0, vdd=1.98)
    _chk(fo4_ss > fo4 * 1.15, f"ss/125/1.62 should be slower than tt FO4 ({fo4_ss:.1f} vs {fo4:.1f})")
    _chk(fo4_ff < fo4 * 0.90, f"ff/-40/1.98 should be faster ({fo4_ff:.1f} vs {fo4:.1f})")

    r_small = char.characterize(CELLS["INV"], C.WMIN_UM, 2 * C.WMIN_UM, C.LMIN_UM, 1.8, 25, 8, 30, "tt")
    r_big = char.characterize(CELLS["INV"], 3.0, 6.0, C.LMIN_UM, 1.8, 25, 8, 30, "tt")
    _chk(float(r_big.delay_ps) < float(r_small.delay_ps), "upsizing must reduce delay at fixed load")
    _chk(float(r_big.p_leak_nw) > float(r_small.p_leak_nw), "upsizing must increase leakage")
    _chk(float(r_big.area_um2) > float(r_small.area_um2), "upsizing must increase area")

    r_nand = char.characterize(CELLS["NAND2"], 0.84, 0.84, C.LMIN_UM, 1.8, 25, 8, 30, "tt")
    _chk(float(r_nand.delay_ps) > float(r_small.delay_ps) * 0.9, "NAND2 should not be faster than INV")

    r_hot = char.characterize(CELLS["INV"], C.WMIN_UM, 2 * C.WMIN_UM, C.LMIN_UM, 1.8, 125, 8, 30, "tt")
    _chk(float(r_hot.p_leak_nw) > 3.0 * float(r_small.p_leak_nw), "leakage must explode with T")

    # Ids increases with W
    i1 = float(nmos.idsat(1.0, C.LMIN_UM, 1.8, 25))
    i2 = float(nmos.idsat(2.0, C.LMIN_UM, 1.8, 25))
    _chk(i2 > 1.7 * i1, "Idsat must scale with W")

    return {
        "fo4_ps": fo4,
        "fo4_ss_hot_lowv_ps": fo4_ss,
        "fo4_ff_cold_highv_ps": fo4_ff,
        "ion": ion,
        "inv_delay_tt_ps": float(r_small.delay_ps),
        "nand2_delay_tt_ps": float(r_nand.delay_ps),
    }
