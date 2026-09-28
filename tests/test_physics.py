#!/usr/bin/env python3
"""Run with:  .venv/bin/python tests/test_physics.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dic_mlopt.physics.sanity import run_sanity


def main() -> int:
    info = run_sanity()
    print("sanity OK")
    for k, v in info.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
