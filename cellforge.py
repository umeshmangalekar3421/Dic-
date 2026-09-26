#!/usr/bin/env python3
"""Root launcher so `python cellforge.py lab` works without PYTHONPATH."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from dic_mlopt.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
