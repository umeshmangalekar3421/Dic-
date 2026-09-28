#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dic_mlopt.service import characterize_point, fo4_ps, product_manifest, sweep


def main() -> int:
    fo4 = fo4_ps()
    assert 40.0 < fo4 < 50.0, fo4
    r = characterize_point("INV", 0.84, 1.68, vdd=1.8, temp_c=25, corner="tt")
    assert r["delay_ps"] > 5, r
    slow = characterize_point("INV", 0.84, 1.68, vdd=1.62, temp_c=125, corner="ss")
    assert slow["delay_ps"] > r["delay_ps"] * 1.15, (slow["delay_ps"], r["delay_ps"])
    s = sweep("INV", axis="vdd", n=8)
    assert len(s["delay_ps"]) == 8
    m = product_manifest()
    assert m["name"] == "CellForge"
    print("service OK  FO4", round(fo4, 2), "ps  INV tt", round(r["delay_ps"], 2), "ps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
