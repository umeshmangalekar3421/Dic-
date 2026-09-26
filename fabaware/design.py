"""
FAB-32: the demonstration design (RTL-to-gate netlist).
=======================================================

A 32-bit datapath block that represents a realistic slice of an ASIC SoC:

* 32-bit carry-select adder  (eight 4-bit blocks)
* 32-bit ALU (add / and / or / xor) with 2-bit operation field
* small finite-state machine (4-bit counter driving the op field)
* 32-bit pipeline register + 4-bit counter register

The netlist is built gate-by-gate from compound standard cells, exactly as an
RTL elaboration would produce. Timing analysis runs on this gate netlist
(RTL-to-GDSII class experiment - we stop at the netlist + placement level,
which is where all the metrics this project reports are defined).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .library import LIBRARY


@dataclass
class Instance:
    idx: int
    cell: str
    in_nets: List[str]
    out_net: str          # '' for DFF (Q handled separately)
    is_dff: bool = False


@dataclass
class Netlist:
    instances: List[Instance] = field(default_factory=list)
    net_driver: Dict[str, int] = field(default_factory=dict)   # net -> instance idx or -1
    net_loads: Dict[str, List[int]] = field(default_factory=dict)
    primary_inputs: List[str] = field(default_factory=list)
    primary_outputs: List[str] = field(default_factory=list)
    dff_d: List[str] = field(default_factory=list)
    dff_q: List[str] = field(default_factory=list)
    hint: Dict[int, int] = field(default_factory=dict)     # instance idx -> placement cluster
    pi_hint: Dict[str, int] = field(default_factory=dict)  # PI net -> cluster it belongs to
    dff_q_of: Dict[int, str] = field(default_factory=dict)  # DFF instance idx -> Q net

    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        self._order: Optional[List[int]] = None

    # construction helpers ------------------------------------------------
    def _new_net(self, prefix: str) -> str:
        name = f"{prefix}{len(self.net_driver)}"
        while name in self.net_driver:
            name += "_"
        self.net_driver[name] = -1
        self.net_loads[name] = []
        return name

    def source(self, name: str) -> str:
        """A timing source: primary input or registered (Q) output."""
        self.net_driver[name] = -1
        self.net_loads[name] = []
        return name

    def gate(self, cell: str, in_nets: List[str], hint: int = 9999) -> str:
        assert cell in LIBRARY and not LIBRARY[cell].flop, cell
        out = self._new_net("n")
        inst = Instance(idx=len(self.instances), cell=cell,
                        in_nets=list(in_nets), out_net=out)
        self.instances.append(inst)
        self.hint[inst.idx] = hint
        self.net_driver[out] = inst.idx
        for n in in_nets:
            assert n in self.net_driver, f"missing net {n}"
            self.net_loads[n].append(inst.idx)
        return out

    def dff(self, d_net: str, name: str, q_net: Optional[str] = None,
            hint: int = 9999) -> str:
        """Add a DFF. If ``q_net`` is given it must already exist as a
        source net and is used as the Q output (registered-source reuse)."""
        q = q_net if q_net is not None else f"q_{name}"
        inst = Instance(idx=len(self.instances), cell="DFF", in_nets=[d_net],
                        out_net="", is_dff=True)
        self.instances.append(inst)
        self.hint[inst.idx] = hint
        self.dff_q_of[inst.idx] = q
        self.dff_d.append(d_net)
        self.dff_q.append(q)
        if q_net is None:
            self.source(q)
        self.net_loads[d_net].append(inst.idx)
        return q

    # topology -------------------------------------------------------------
    def order(self) -> List[int]:
        """Topological order of all instances (stable, computed once)."""
        if self._order is not None:
            return self._order
        layer: Dict[int, int] = {}
        ready = set(range(len(self.instances)))
        for _ in range(len(self.instances) + 1):
            for i in list(ready):
                inst = self.instances[i]
                ok = True
                ml = 0
                for n in inst.in_nets:
                    d = self.net_driver[n]
                    if d >= 0:
                        if d not in layer:
                            ok = False
                            break
                        ml = max(ml, layer[d])
                if ok:
                    layer[i] = ml
                    ready.discard(i)
        if ready:
            raise RuntimeError("netlist has a combinational loop")
        self._order = sorted(layer, key=lambda i: layer[i])
        return self._order

    def stats(self) -> Dict[str, int]:
        n = {}
        for inst in self.instances:
            n[inst.cell] = n.get(inst.cell, 0) + 1
        return {
            "gates": sum(1 for i in self.instances if not i.is_dff),
            "dffs": sum(1 for i in self.instances if i.is_dff),
            "nets": len(self.net_driver),
            "transistors": sum(LIBRARY[i.cell].ntr for i in self.instances),
            "by_type": n,
        }


# ---------------------------------------------------------------------------
# netlist construction
# ---------------------------------------------------------------------------

def build_fab32() -> Netlist:
    """Build the FAB-32 32-bit ALU datapath netlist."""
    nl = Netlist()

    def pi(name: str, hint: int) -> str:
        """Declare a primary input, tagged with the cluster it feeds."""
        net = nl.source(name)
        nl.primary_inputs.append(net)
        nl.pi_hint[net] = hint
        return net

    # placement clusters: a-bit i west / b-bit i east / FSM near cluster 40
    a = [pi(f"a{i}", 1000 + i) for i in range(32)]
    b = [pi(f"b{i}", 2000 + i) for i in range(32)]

    # counter Q outputs are timing sources for the FSM cone
    cq = [nl.source(f"c{j}") for j in range(4)]

    zero = pi("const0", 0)   # tied low
    one = pi("const1", 0)    # tied high

    # ---------------- carry-select adder (eight 4-bit blocks) ------------
    x = [None] * 32          # x[i] = a[i] XOR b[i]
    mab = [None] * 32        # a[i] AND b[i]
    s0 = [None] * 32         # sum with cin=0
    s1 = [None] * 32         # sum with cin=1
    g0 = [None] * 8          # block carry-out with cin=0
    g1 = [None] * 8          # block carry-out with cin=1

    for i in range(32):
        x[i] = nl.gate("XOR2", [a[i], b[i]], hint=i)
        mab[i] = nl.gate("NAND2", [a[i], b[i]], hint=i)

    for blk in range(8):
        bits = range(4 * blk, 4 * blk + 4)
        csel = g1[blk - 1] if blk > 0 else zero
        # chain with cin = 0
        c0 = zero
        for i in bits:
            mcx = nl.gate("NAND2", [c0, x[i]], hint=i)
            c0 = nl.gate("NAND2", [mab[i], mcx], hint=i)
            s0[i] = x[i]
        g0[blk] = c0
        # chain with cin = 1
        c1 = one
        for i in bits:
            mcx = nl.gate("NAND2", [c1, x[i]], hint=i)
            c1 = nl.gate("NAND2", [mab[i], mcx], hint=i)
            s1[i] = nl.gate("XOR2", [x[i], c1], hint=i)
        g1[blk] = c1

    # per-bit sum mux + inter-block carry mux
    sum_bits = [None] * 32
    for blk in range(8):
        csel = g1[blk - 1] if blk > 0 else zero
        for i in range(4 * blk, 4 * blk + 4):
            # MUX2(sel, a, b) = sel ? a : b  ->  csel=1 selects the cin=1 sum
            sum_bits[i] = nl.gate("MUX2", [csel, s1[i], s0[i]], hint=i)
        if blk < 7:
            g1[blk] = nl.gate("MUX2", [csel, g1[blk], g0[blk]],
                              hint=4 * blk + 3)
    csel7 = g1[6]
    cout = nl.gate("MUX2", [csel7, g1[7], g0[7]], hint=31)
    nl.primary_outputs.append(cout)

    # ---------------- ALU (add / and / or / xor) -------------------------
    # op field comes from the FSM counter: op0 = c0, op1 = c1, op2 = c1 & c2
    op0 = cq[0]
    op1 = cq[1]
    op2 = nl.gate("INV", [nl.gate("NAND2", [cq[1], cq[2]], hint=41)], hint=41)
    nl.primary_outputs.append(op2)

    # op00=add, op01=and, op10=or, op11=xor
    alu_out = [None] * 32
    for i in range(32):
        and_out = nl.gate("INV", [mab[i]], hint=i)
        or_out = nl.gate("INV", [nl.gate("NOR2", [a[i], b[i]], hint=i)], hint=i)
        t1 = nl.gate("MUX2", [op0, and_out, sum_bits[i]], hint=i)
        t2 = nl.gate("MUX2", [op0, x[i], or_out], hint=i)
        alu_out[i] = nl.gate("MUX2", [op1, t2, t1], hint=i)

    # ---------------- FSM: 4-bit up-counter feeding cq --------------------
    n0 = nl.gate("INV", [cq[0]], hint=40)
    n1 = nl.gate("XOR2", [cq[1], cq[0]], hint=40)
    k1 = nl.gate("INV", [nl.gate("NAND2", [cq[1], cq[0]], hint=40)], hint=40)
    n2 = nl.gate("XOR2", [cq[2], k1], hint=40)
    k2 = nl.gate("INV", [nl.gate("NAND2", [k1, cq[2]], hint=40)], hint=40)
    n3 = nl.gate("XOR2", [cq[3], k2], hint=40)
    for j, nxt in enumerate([n0, n1, n2, n3]):
        nl.dff(nxt, f"cnt{j}", q_net=cq[j], hint=40 + j)

    # ---------------- pipeline register ----------------------------------
    for i in range(32):
        q = nl.dff(alu_out[i], f"s{i}", hint=i)
        nl.primary_outputs.append(q)

    return nl


if __name__ == "__main__":
    print(build_fab32().stats())
