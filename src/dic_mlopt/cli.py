"""CellForge command line.

    python -m dic_mlopt lab          # open the product UI
    python -m dic_mlopt run          # regenerate the full flow
    python -m dic_mlopt run --quick
    python -m dic_mlopt fo4
    python -m dic_mlopt char --cell NAND2 --wn 1.6 --wp 2.1 --corner ss
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="cellforge",
        description="CellForge — PVT-robust standard-cell lab",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lab = sub.add_parser("lab", help="launch the interactive lab (browser)")
    lab.add_argument("--host", default="0.0.0.0")
    lab.add_argument("--port", type=int, default=8000)

    run = sub.add_parser("run", help="run the full characterization → ML → STA pipeline")
    run.add_argument("--quick", action="store_true")

    sub.add_parser("fo4", help="print FO4 inverter delay at three corners")

    ch = sub.add_parser("char", help="characterize one cell at one PVT point")
    ch.add_argument("--cell", default="INV")
    ch.add_argument("--wn", type=float, default=0.84)
    ch.add_argument("--wp", type=float, default=1.68)
    ch.add_argument("--vdd", type=float, default=1.8)
    ch.add_argument("--temp", type=float, default=25.0)
    ch.add_argument("--cload", type=float, default=8.0)
    ch.add_argument("--slew", type=float, default=30.0)
    ch.add_argument("--corner", default="tt")

    args = p.parse_args(argv)

    if args.cmd == "lab":
        return _lab(args.host, args.port)
    if args.cmd == "run":
        sys.path.insert(0, str(ROOT))
        from run_project import main as run_main
        return run_main(["--quick"] if args.quick else [])
    if args.cmd == "fo4":
        from dic_mlopt.service import fo4_ps

        print(f"FO4  tt  1.80 V  25 °C   {fo4_ps():.2f} ps")
        print(f"FO4  ss  1.62 V 125 °C   {fo4_ps(1.62, 125, 'ss'):.2f} ps")
        print(f"FO4  ff  1.98 V -40 °C   {fo4_ps(1.98, -40, 'ff'):.2f} ps")
        return 0
    if args.cmd == "char":
        from dic_mlopt.service import characterize_point

        r = characterize_point(
            cell=args.cell, wn_um=args.wn, wp_um=args.wp,
            vdd=args.vdd, temp_c=args.temp, cload_ff=args.cload,
            slew_ps=args.slew, corner=args.corner,
        )
        print(json.dumps(r, indent=2))
        return 0
    return 1


def _lab(host: str, port: int) -> int:
    import os
    import uvicorn

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    print()
    print("  CellForge lab")
    print(f"  listening on http://{host}:{port}")
    print("  open that URL in a browser — this is the product demo")
    print()
    uvicorn.run("app.server:app", host=host, port=port, reload=False, log_level="info")
    return 0
