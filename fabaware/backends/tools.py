"""
Detection of real EDA tools.

No tool here is mandatory. Each backend reports whether it is available and
the caller falls back to the equivalent Python model when it is not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, List, Optional

#: candidate executable names, in preference order
CANDIDATES: Dict[str, List[str]] = {
    "yosys":    ["yosys", "yowasp-yosys"],
    "ngspice":  ["ngspice"],
    "opensta":  ["sta", "opensta"],
    "openroad": ["openroad"],
    "iverilog": ["iverilog"],
    "klayout":  ["klayout"],
}

#: what each tool is used for in this project
ROLE: Dict[str, str] = {
    "yosys":    "RTL synthesis  (replaces fabaware/design.py)",
    "ngspice":  "transistor simulation (replaces fabaware/compact.py)",
    "opensta":  "static timing analysis (replaces fabaware/sta.py)",
    "openroad": "place & route  (replaces fabaware/pd.py)",
    "iverilog": "functional simulation of the netlist",
    "klayout":  "layout viewing and DRC",
}

_cache: Dict[str, Optional[str]] = {}


def find(tool: str) -> Optional[str]:
    """Absolute path to a tool's executable, or None if not installed."""
    if tool in _cache:
        return _cache[tool]
    override = os.environ.get(f"FABAWARE_{tool.upper()}")
    if override and os.path.exists(override):
        _cache[tool] = override
        return override
    for name in CANDIDATES.get(tool, [tool]):
        path = shutil.which(name)
        if path:
            _cache[tool] = path
            return path
    _cache[tool] = None
    return None


def version(tool: str) -> Optional[str]:
    """Best-effort version string for a tool."""
    exe = find(tool)
    if not exe:
        return None
    flags = {
        "yosys": ["-V"],
        "ngspice": ["--version"],
        "opensta": ["-version"],
        "openroad": ["-version"],
        "iverilog": ["-V"],
        "klayout": ["-v"],
    }.get(tool, ["--version"])
    try:
        out = subprocess.run([exe, *flags], capture_output=True, text=True,
                             timeout=120)
        txt = (out.stdout or "") + (out.stderr or "")
        for line in txt.splitlines():
            line = line.strip()
            if line and not line.startswith("Preparing"):
                return line[:90]
    except Exception:
        return "unknown"
    return "unknown"


def detect() -> Dict[str, Optional[str]]:
    """Map tool name -> executable path (None when missing)."""
    return {t: find(t) for t in CANDIDATES}


def available() -> List[str]:
    """Names of the tools that are installed."""
    return [t for t in CANDIDATES if find(t)]


def summary() -> str:
    """Human-readable table of what is installed and what is used."""
    lines = ["Real-tool backends", "-------------------"]
    for tool in CANDIDATES:
        exe = find(tool)
        if exe:
            lines.append(f"  {tool:<9} REAL      {version(tool)}")
            lines.append(f"            -> {ROLE[tool]}")
        else:
            lines.append(f"  {tool:<9} simulated -> {ROLE[tool]} "
                         f"(Python model)")
    return "\n".join(lines)
