"""
PDK (process design kit) support.
=================================

A PDK is the foundry's data package: the Liberty timing models, the LEF
physical layouts, the layer stack and the design rules. This module finds an
installed PDK on disk and maps our virtual cell library onto its real cells.

Why mapping needs care
----------------------
Our library speaks our own names (``NAND2_X2``). A real PDK speaks its own
(``sky130_fd_sc_hd__nand2_2``). Cell *names* differ between foundries and even
between libraries from the same foundry, so this module never trusts a
hard-coded name. Instead:

1. each of our cell types lists **candidate** names, most-preferred first;
2. the candidate list is checked against the cells that actually exist in the
   Liberty file we just read;
3. the first candidate that exists wins.

If the PDK lacks a cell entirely, the caller is told so explicitly rather than
silently emitting something that will not link.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# PDK descriptions
# ---------------------------------------------------------------------------

@dataclass
class Pdk:
    """Where a PDK lives and which files matter to us."""
    name: str
    root: str
    corner_lib: str = ""
    lefs: List[str] = field(default_factory=list)      # technology + stdcell LEF
    tech_lef: str = ""
    sram_lib: Optional[str] = None
    lib_dir: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.corner_lib and os.path.exists(self.corner_lib)
                    and self.lefs and all(os.path.exists(p) for p in self.lefs))

    def summary(self) -> str:
        return (f"{self.name}: lib={os.path.basename(self.corner_lib) or '-'} "
                f"refs={len(self.refs)}")

    @property
    def refs(self) -> List[str]:
        return [p for p in self.lefs if os.path.exists(p)]

    def lib_files(self, *corners: str) -> List[str]:
        """All Liberty files matching the given corner substrings."""
        out = []
        for f in sorted(glob.glob(os.path.join(self.lib_dir, "*.lib"))):
            low = os.path.basename(f).lower()
            if not corners or any(c.lower() in low for c in corners):
                out.append(f)
        return out


#: where volare / open_pdks install things
_VOLARE = os.path.expanduser("~/.volare")


def find_sky130(root: Optional[str] = None) -> Optional[Pdk]:
    """
    Locate an installed SKY130 PDK.

    Checks, in order: ``--pdk-root`` / ``PDK_ROOT``, the volare default
    (``~/.volare/sky130A``), and the classic ``$PDK_ROOT/sky130A``.
    """
    candidates: List[str] = []
    if root:
        candidates.append(root)
    env = os.environ.get("PDK_ROOT")
    if env:
        candidates += [os.path.join(env, "sky130A"), env]
    candidates += [os.path.join(_VOLARE, "sky130A"),
                   os.path.expanduser("~/sky130A"),
                   "/usr/local/share/pdk/sky130A",
                   "/opt/pdk/sky130A"]

    for base in candidates:
        if not base or not os.path.isdir(base):
            continue
        pdk = _sky130_from(base)
        if pdk is not None:
            return pdk
    return None


def _sky130_from(base: str) -> Optional[Pdk]:
    ref = os.path.join(base, "libs.ref")
    tech = os.path.join(base, "libs.tech")
    lib_dir = os.path.join(ref, "sky130_fd_sc_hd", "lib")
    if not os.path.isdir(lib_dir):
        return None

    # pick the typical-typical corner: 25 C, nominal voltage
    preferred = [
        "sky130_fd_sc_hd__tt_025C_1v80.lib",
        "sky130_fd_sc_hd__tt_025C_1v65.lib",
    ]
    corner = ""
    for name in preferred:
        p = os.path.join(lib_dir, name)
        if os.path.exists(p):
            corner = p
            break
    if not corner:
        found = sorted(glob.glob(os.path.join(lib_dir, "*tt_025C*.lib")))
        if not found:
            found = sorted(glob.glob(os.path.join(lib_dir, "*.lib")))
        corner = found[0] if found else ""

    # technology LEF first, then the stdcell LEF
    lefs: List[str] = []
    for pat in (os.path.join(tech, "sky130_fd_sc_hd", "*.tlef"),
                os.path.join(ref, "sky130_fd_sc_hd", "techlef", "*.tlef")):
        lefs += sorted(glob.glob(pat))
    for pat in (os.path.join(ref, "sky130_fd_sc_hd", "lef", "*.lef"),):
        lefs += sorted(glob.glob(pat))

    return Pdk(name="sky130", root=base, corner_lib=corner,
               lefs=lefs, lib_dir=lib_dir)


def find_pdk(name: str = "sky130", root: Optional[str] = None) -> Optional[Pdk]:
    if name.lower() in ("sky130", "sky130a", "skywater130"):
        return find_sky130(root)
    return None


# ---------------------------------------------------------------------------
# cell mapping
# ---------------------------------------------------------------------------

#: Our cell type -> candidate SKY130 names, most-preferred first.
#: %d is filled with the drive strength. Not every variant exists in every
#: library, which is exactly why these are candidates and not certainties.
SKY130_CANDIDATES: Dict[str, Sequence[str]] = {
    "INV":   ("sky130_fd_sc_hd__inv_%d",),
    "BUF":   ("sky130_fd_sc_hd__buf_%d",),
    "NAND2": ("sky130_fd_sc_hd__nand2_%d",),
    "NAND3": ("sky130_fd_sc_hd__nand3_%d",),
    "NOR2":  ("sky130_fd_sc_hd__nor2_%d",),
    "XOR2":  ("sky130_fd_sc_hd__xor2_%d",),
    "MUX2":  ("sky130_fd_sc_hd__mux2_%d",),
    # our A21 is ((A*B)+C): a 2-input AND into a 2-input OR
    "A21":   ("sky130_fd_sc_hd__a21o_%d", "sky130_fd_sc_hd__a21oi_%d"),
    # our AOI22 is ((A*B)+(C*D))'  ->  and-or-invert
    "AOI22": ("sky130_fd_sc_hd__o221a_%d", "sky130_fd_sc_hd__o22a_%d",
              "sky130_fd_sc_hd__a22o_%d"),
    "DFF":   ("sky130_fd_sc_hd__dfxtp_%d", "sky130_fd_sc_hd__dfrtp_%d",
              "sky130_fd_sc_hd__dfsbp_%d"),
}

#: drive strengths we are willing to ask a real PDK for, best-effort order
DRIVE_LADDER: Sequence[int] = (1, 2, 4, 8)

_CELL_RE = re.compile(r'^\s*cell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{', re.M)


def liberty_cells(path: str) -> set:
    """The set of cell names defined in a Liberty file (cheap regex scan)."""
    try:
        with open(path, errors="ignore") as f:
            return set(_CELL_RE.findall(f.read()))
    except OSError:
        return set()


def pin_names(lib_path: str, cell: str) -> Optional[List[str]]:
    """Ordered input pin names of ``cell`` in a Liberty file (best effort)."""
    try:
        text = open(lib_path, errors="ignore").read()
    except OSError:
        return None
    m = re.search(r'cell\s*\(\s*"?%s"?\s*\)\s*\{' % re.escape(cell), text)
    if not m:
        return None
    body = text[m.end():]
    depth = 1
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = body[:i]
                break
    ins, out, clock = [], [], []
    for pm in re.finditer(r'pin\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{', body):
        name = pm.group(1)
        # brace-match this pin's own block - a fixed-size window would bleed
        # into the next pin and misread its direction
        seg = body[pm.end():]
        depth = 1
        for i, ch in enumerate(seg):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    seg = seg[:i]
                    break
        if "direction : output" in seg:
            out.append(name)
        elif "direction : input" in seg:
            if "clock : true" in seg:
                clock.append(name)
            else:
                ins.append(name)
    return ins + out


class CellMap:
    """
    Maps our (cell type, drive) pairs onto real PDK cell names.

    Built from an actual Liberty file so that a missing cell is discovered
    here, with a clear error, rather than as a link failure inside OpenROAD.
    """

    def __init__(self, pdk: Pdk, drives: Sequence[int] = DRIVE_LADDER):
        self.pdk = pdk
        self.available: set = liberty_cells(pdk.corner_lib)
        self.drives = list(drives)
        self.map: Dict[Tuple[str, float], str] = {}
        self.unmapped: List[str] = []
        self._build()

    def _lookup(self, our_cell: str, drive: int) -> Optional[str]:
        for cand in SKY130_CANDIDATES.get(our_cell, ()):
            for d in sorted(self.drives, key=lambda x: abs(x - drive)):
                name = cand % d
                if name in self.available:
                    return name
        return None

    def _build(self) -> None:
        from ..library import LIBRARY
        for our_cell in LIBRARY:
            for drive in (1.0, 2.0, 4.0):
                want = self._lookup(our_cell, int(drive))
                if want:
                    self.map[(our_cell, drive)] = want
                else:
                    self.unmapped.append(f"{our_cell}_X{int(drive)}")

    def name_for(self, cell: str, drive: float) -> Optional[str]:
        return self.map.get((cell, float(drive)))

    def pins_for(self, cell: str, drive: float) -> Optional[List[str]]:
        real = self.name_for(cell, drive)
        if not real:
            return None
        pins = pin_names(self.pdk.corner_lib, real)
        return pins

    def report(self) -> str:
        L = [f"  PDK            : {self.pdk.name} ({self.pdk.root})",
             f"  cells in .lib  : {len(self.available)}",
             f"  mapped         : {len(self.map)}"]
        if self.unmapped:
            L.append(f"  NOT AVAILABLE  : {', '.join(self.unmapped)}")
            L.append("    -> those cell types will keep the built-in model")
        return "\n".join(L)
