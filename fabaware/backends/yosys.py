"""
Real Yosys synthesis backend  (replaces the hand-built netlist).
===============================================================

Runs the genuine, industry-standard Yosys synthesis tool on the Verilog RTL in
``rtl/`` and imports the resulting gate-level netlist into the FabAware-Opt
timing engine.

Cell mapping
------------
Yosys ``synth`` (without ABC technology mapping) emits its generic internal
cell types. We map them onto the project's virtual 28 nm library:

    $_AND_     -> NAND2 + INV      (the library has no native AND2)
    $_OR_      -> NOR2  + INV
    $_NOT_     -> INV
    $_XOR_     -> XOR2
    $_MUX_     -> MUX2
    $_DFF_P_   -> DFF

With a real PDK you would instead run ``abc -liberty sky130.lib`` and Yosys
would map directly onto the foundry's cells; pass ``liberty=...`` to
:func:`synthesize` to do that. The rest of the flow is unchanged either way.

Locality hints
--------------
The importer recovers placement locality from the net names Yosys emits
(``alu[7]``, ``cnt[2]``, ``s[31]`` ...). Bit-indexed names in the same datapath
are given the same placement cluster hint, so the placer keeps bit *i*'s logic
together — the same effect the hand-built netlist achieved with explicit hints.
"""

from __future__ import annotations

import os
import re
import subprocess
import zlib
from typing import Dict, List, Optional, Tuple

from ..design import Netlist
from . import tools

# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

#: matches  \ $_AND_  _317_  /* comment */ ( ... );
#: group 1 = cell type (without the leading $), 2 = instance, 3 = port list
_INST_RE = re.compile(
    r"^\s*\\?\$?([A-Za-z0-9_]+)\s+\\?([^\s(]+)\s*(?:/\*.*?\*/)?\s*\(([^;]*)\)",
    re.M | re.S,
)
_PORT_RE = re.compile(r"\.(\w+)\s*\(\s*\\?([^\s)]+?)\s*\)")

#: Yosys generic cell -> our library cell(s)
#:   value = list of (cell, [port names feeding it in order])
_MAP: Dict[str, List[Tuple[str, List[str]]]] = {
    "$_AND_":   [("NAND2", ["A", "B"]), ("INV", ["-"])],
    "$_OR_":    [("NOR2",  ["A", "B"]), ("INV", ["-"])],
    "$_NOT_":   [("INV",   ["A"])],
    "$_XOR_":   [("XOR2",  ["A", "B"])],
    "$_MUX_":   [("MUX2",  ["S", "B", "A"])],
    "$_DFF_P_": [("DFF",   ["D"])],
}


def _expand_bits(direction: str, text: str) -> List[str]:
    """Collect declared ``input``/``output`` net names, expanding buses."""
    out: List[str] = []
    pattern = (r"^\s*" + direction + r"\s+(?:\[(\d+):(\d+)\]\s*)?"
               r"([\\A-Za-z_][\w]*)\s*;")
    for m in re.finditer(pattern, text, re.M):
        msb, lsb, name = m.group(1), m.group(2), m.group(3).lstrip("\\")
        if msb is None:
            out.append(name)
            continue
        hi, lo = int(msb), int(lsb)
        step = 1 if hi >= lo else -1
        for i in range(lo, hi + step, step):
            out.append(f"{name}[{i}]")
    return out


def _stable_hash(s: str) -> int:
    """Process-independent string hash.

    Python's built-in ``hash()`` is salted per process, which would make
    placement (and therefore every downstream number) irreproducible.
    """
    return zlib.crc32(s.encode("utf-8"))


def _hint_for(net: str) -> int:
    """Placement cluster hint recovered from a net name.

    ``alu[7]`` and ``s[7]`` share hint 7, so bit 7's logic stays together.
    Nets without a bit index land in a shared bucket.
    """
    m = re.search(r"\[(\d+)\]", net)
    if m:
        base = re.sub(r"\[\d+\]", "", net)
        return (_stable_hash(base) & 0xFFF) * 64 + (int(m.group(1)) % 64)
    return 9000 + (_stable_hash(net) & 0x3F)


def parse_netlist(path: str) -> Netlist:
    """Import a Yosys structural-Verilog netlist into a :class:`Netlist`."""
    text = open(path, encoding="utf-8").read()
    nl = Netlist()

    pis = _expand_bits("input", text)
    pos = _expand_bits("output", text)

    # ---- collect instances -------------------------------------------------
    insts: List[Tuple[str, str, Dict[str, str]]] = []
    for m in _INST_RE.finditer(text):
        ctype = "$" + m.group(1)
        if ctype not in _MAP:
            continue
        name = m.group(2)
        ports = {k: v for k, v in _PORT_RE.findall(m.group(3))}
        insts.append((ctype, name, ports))

    # ---- declare every net up front ---------------------------------------
    driven: List[str] = []
    for ctype, name, ports in insts:
        out = ports.get("Y") or ports.get("Q")
        if out:
            driven.append(out)
    for n in pis + driven:
        if n not in nl.net_driver:
            nl.source(n)
    for n in pis:
        nl.primary_inputs.append(n)
    for n in pos:
        nl.primary_outputs.append(n)

    # ---- place the cells (hints are assigned afterwards) -------------------
    for ctype, name, ports in insts:
        out_net = ports.get("Y") or ports.get("Q")
        hint = 9999
        chain = _MAP[ctype]

        if chain[0][0] == "DFF":
            nl.dff(ports["D"], name, q_net=out_net, hint=hint)
            continue

        # a Yosys gate may expand to several library cells; "-" means
        # "output of the previous cell in the chain"
        cur_out = None
        for i, (cell, srcs) in enumerate(chain):
            is_last = (i == len(chain) - 1)
            ins: List[str] = []
            for s in srcs:
                ins.append(cur_out if s == "-" else ports[s])
            target = out_net if is_last else f"{name}__x{i}"
            if not is_last and target not in nl.net_driver:
                nl.source(target)
            nl.gate_named(cell, ins, target, hint=hint)
            cur_out = target

    _propagate_hints(nl)
    return nl


def _propagate_hints(nl: Netlist, rounds: int = 8) -> None:
    """Recover placement locality for a netlist we did not build ourselves.

    Yosys names most internal wires ``_317_`` — they carry no structural
    information, so naming alone cannot tell us that a wire belongs to bit 7
    of the datapath. Placing on such names is effectively random, which
    inflates wire length by an order of magnitude and swamps the DRC model.

    Instead we seed the nets that *do* carry a bit index (``alu[7]``,
    ``s[7]``, ``cnt[2]`` ...) and propagate those labels through the gate
    graph, so every wire wired to bit 7 inherits cluster 7. The result is the
    same bit-sliced locality the hand-built netlist gets from explicit hints.
    """
    net_hint: Dict[str, int] = {}
    for net in nl.net_driver:
        m = re.search(r"\[(\d+)\]", net)
        if m:
            net_hint[net] = int(m.group(1)) % 64

    def out_of(inst) -> Optional[str]:
        if inst.out_net:
            return inst.out_net
        return nl.dff_q_of.get(inst.idx)

    for _ in range(rounds):
        changed = False
        for inst in nl.instances:
            cand: List[int] = []
            out = out_of(inst)
            if out and out in net_hint:
                cand.append(net_hint[out])
            for n in inst.in_nets:
                if n in net_hint:
                    cand.append(net_hint[n])
            if not cand:
                continue
            h = max(set(cand), key=cand.count)
            if out and out not in net_hint:
                net_hint[out] = h
                changed = True
            for n in inst.in_nets:
                if n not in net_hint:
                    net_hint[n] = h
                    changed = True
        if not changed:
            break

    for inst in nl.instances:
        out = out_of(inst)
        h = net_hint.get(out) if out else None
        if h is None:
            for n in inst.in_nets:
                if n in net_hint:
                    h = net_hint[n]
                    break
        nl.hint[inst.idx] = h if h is not None else 9999


# ---------------------------------------------------------------------------
# synthesis
# ---------------------------------------------------------------------------

def synthesize(
    verilog: str,
    top: str = "fab32",
    workdir: str = "build",
    liberty: Optional[str] = None,
    flatten: bool = True,
) -> str:
    """
    Run real Yosys on a Verilog file and return the path to the netlist.

    Parameters
    ----------
    verilog  : path to the RTL source
    top      : top module name
    workdir  : directory for intermediate files
    liberty  : optional .lib file. When given, Yosys runs ``abc -liberty`` and
               maps directly onto that cell library (the real-PDK path).
               Without it we use the generic-cell mapping documented above.
    """
    exe = tools.find("yosys")
    if exe is None:
        raise RuntimeError(
            "Yosys not found. Install it with:\n"
            "    apt install yosys          # Debian/Ubuntu\n"
            "    pip install yowasp-yosys   # any platform, no root needed\n"
            "or set FABAWARE_YOSYS=/path/to/yosys"
        )
    os.makedirs(workdir, exist_ok=True)
    out = os.path.join(workdir, f"{top}_yosys.v")

    # Note: the WebAssembly build of Yosys (yowasp-yosys, used when no
    # native binary is available) only sees paths beneath the current
    # directory. Callers should pass a project-relative workdir.

    steps = [f"read_verilog {verilog}"]
    if flatten:
        steps.append(f"hierarchy -check -top {top}")
    if liberty:
        # real technology mapping onto a foundry/PDK cell library
        steps += [f"synth -top {top} -noabc",
                  f"dfflibmap -liberty {liberty}",
                  f"abc -liberty {liberty} -D 1"]
    else:
        steps.append(f"synth -top {top} -noabc")
    steps.append(f"write_verilog -noattr -noexpr {out}")

    script = "; ".join(steps)
    proc = subprocess.run([exe, "-p", script], capture_output=True,
                          text=True, timeout=1800)
    if proc.returncode != 0 or not os.path.exists(out):
        tail = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:]
        raise RuntimeError(f"Yosys failed (rc={proc.returncode}):\n{tail}")
    return out


def build_from_verilog(
    verilog: str = "rtl/fab32.v",
    top: str = "fab32",
    workdir: str = "build",
    liberty: Optional[str] = None,
    use_cache: bool = True,
) -> Netlist:
    """Synthesize with real Yosys and import the netlist.

    Falls back to the hand-built Python netlist if Yosys is unavailable.
    """
    from ..design import build_fab32

    if tools.find("yosys") is None:
        return build_fab32()
    netlist_path = os.path.join(workdir, f"{top}_yosys.v")
    if not (use_cache and os.path.exists(netlist_path)):
        netlist_path = synthesize(verilog, top=top, workdir=workdir,
                                  liberty=liberty)
    return parse_netlist(netlist_path)
