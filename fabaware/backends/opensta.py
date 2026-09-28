"""
Real OpenSTA backend  (replaces the Python static-timing engine).
================================================================

Runs the genuine OpenSTA static timing analyzer on a gate-level netlist and
parses real ``report_timing`` / ``report_power`` output.

Why OpenSTA instead of our own engine
-------------------------------------
Our ``sta.py`` is a longest-path dynamic programme over a simple
``(A + B*Cload)`` delay model. OpenSTA does proper STA: real Liberty
non-linear delay models (NLDM / CCS), clock-network timing, reconvergent
fanout analysis, and per-corner multi-mode analysis. Where OpenSTA is
available it is strictly more trustworthy than our engine.

What stays ours
---------------
OpenSTA answers "what is the worst slack of *this* configuration?" It does
not decide *which* configuration to try. The Monte-Carlo loop, the
variability model and the GP optimizer remain ours — they simply call OpenSTA
as the timing oracle instead of our engine.

Running it
----------
    fabaware-run --real --sta opensta --liberty sky130.lib
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from . import tools


# ---------------------------------------------------------------------------
# SDC / TCL generation  (pure functions - testable without OpenSTA)
# ---------------------------------------------------------------------------

def write_sdc(clock_net: str = "clk", period_ps: float = 211.0,
              inputs: Sequence[str] = (), outputs: Sequence[str] = (),
              input_delay_ps: float = 0.0,
              output_delay_ps: float = 0.0) -> str:
    """Generate an SDC constraint file."""
    lines = [
        "# FabAware-Opt: generated constraints",
        f"create_clock -name clk -period {period_ps:.6g} [get_ports {{{clock_net}}}]",
        "set_clock_uncertainty 0.0 [get_clocks clk]",
        "set_clock_latency 0.0 [get_clocks clk]",
        "set_input_transition 0.010 [all_inputs]",
        "",
    ]
    if inputs:
        ports = " ".join(f"[get_ports {{{p}}}]" for p in inputs)
        lines.append(f"set_input_delay {input_delay_ps:.6g} -clock clk {ports}")
    if outputs:
        ports = " ".join(f"[get_ports {{{p}}}]" for p in outputs)
        lines.append(f"set_output_delay {output_delay_ps:.6g} -clock clk {ports}")
    lines.append("")
    return "\n".join(lines)


def write_tcl(netlist: str, liberty: Sequence[str], sdc: str,
              top: str = "fab32", out_dir: str = "build",
              reports: Sequence[str] = ("timing", "power")) -> str:
    """Generate the OpenSTA script that reads a design and writes reports."""
    lines = [
        "# FabAware-Opt: generated OpenSTA script",
        "set_units -time ps -capacitance fF -current mA -voltage V -resistance kOhm",
        "",
    ]
    for lib in liberty:
        lines.append(f"read_liberty {lib}")
    lines += [
        f"read_verilog {netlist}",
        f"link_design {top}",
        f"read_sdc {sdc}",
        "",
    ]
    for r in reports:
        path = os.path.join(out_dir, f"sta_{r}.rpt")
        if r == "timing":
            lines.append(f"report_checks -path_delay max -fields {{slew cap input nets fanout}} "
                         f"-digits 4 > {path}")
            lines.append(f"report_worst_slack -max -digits 4 >> {path}")
        elif r == "power":
            lines.append(f"report_power -digits 4 > {path}")
        elif r == "area":
            lines.append(f"report_area -digits 4 > {path}")
    lines += ["exit", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# report parsing  (pure functions - testable with canned OpenSTA output)
# ---------------------------------------------------------------------------

@dataclass
class StaResult:
    """What we can extract from OpenSTA's reports."""
    worst_slack_ps: float = float("nan")
    worst_arrival_ps: float = float("nan")
    endpoints: int = 0
    power_mW: Optional[float] = None
    area_um2: Optional[float] = None
    path_nets: List[str] = field(default_factory=list)
    raw: str = ""


#: OpenSTA prints "worst slack max -12.3456", "worst slack -12.3456", or
#: "worst slack max rise -12.3456" depending on flags and version.
_WS_RE = re.compile(
    r"worst\s+slack(?:\s+(?:max|min|rise|fall))*[\s:=]+(-?[\d.]+)", re.I)
#: endpoint count line:  "endpoint_count 70"
_EP_RE = re.compile(r"endpoint[_\s]count\s+(\d+)", re.I)
#: "Total   9.3e-05   2.85e-05   3.1e-05   1.52e-04 W"
#: The Total row has several columns; the value we want is the LAST number,
#: and the unit may sit at the end of the line.
_NUM_RE = re.compile(r"([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s*(mW|uW|nW|W)?", re.I)
#: "Total area: 1234.5 u^2"  / "Design area 1234.5"
_AREA_RE = re.compile(r"(?:total\s+)?(?:design\s+)?area\s*:?\s*([\d.]+)", re.I)


def parse_worst_slack(text: str) -> float:
    """Worst (max-delay) slack in ps, from ``report_worst_slack``."""
    m = _WS_RE.search(text)
    return float(m.group(1)) if m else float("nan")


def parse_endpoint_count(text: str) -> int:
    m = _EP_RE.search(text)
    return int(m.group(1)) if m else 0


_SCALE = {"w": 1e3, "mw": 1.0, "uw": 1e-3, "nw": 1e-6}


def parse_power(text: str) -> Optional[float]:
    """Total power in mW, from an OpenSTA ``report_power`` table.

    The ``Total`` row carries several columns (internal / switching /
    leakage / total); we take the last number on that row and the unit that
    follows it, falling back to a unit elsewhere on the line.
    """
    for line in text.splitlines():
        if not line.strip().lower().startswith("total"):
            continue
        pairs = _NUM_RE.findall(line)
        if not pairs:
            continue
        # last token that actually parsed as a number
        val = None
        for num, _unit in reversed(pairs):
            try:
                val = float(num)
                break
            except ValueError:
                continue
        if val is None:
            continue
        unit = next((u.lower() for _n, u in pairs if u), None) or "w"
        return val * _SCALE.get(unit, 1.0)
    return None


def parse_area(text: str) -> Optional[float]:
    m = _AREA_RE.search(text)
    return float(m.group(1)) if m else None


def parse_timing_report(text: str) -> StaResult:
    """Parse a combined timing report into a :class:`StaResult`."""
    return StaResult(
        worst_slack_ps=parse_worst_slack(text),
        endpoints=parse_endpoint_count(text),
        path_nets=re.findall(r"^\s*\S+\s+\S+\s+(\S+)\s*\(", text, re.M)[:64],
        raw=text,
    )


def parse_power_report(text: str) -> Optional[float]:
    return parse_power(text)


# ---------------------------------------------------------------------------
# execution  (needs OpenSTA)
# ---------------------------------------------------------------------------

def run_sta(netlist: str, liberty: Sequence[str], top: str = "fab32",
            period_ps: float = 211.0, clock_net: str = "clk",
            workdir: str = "build",
            reports: Sequence[str] = ("timing", "power")) -> StaResult:
    """
    Run real OpenSTA on a netlist and return the parsed results.

    Requires a Liberty file — OpenSTA has no built-in cell timing, and
    inventing one would defeat the point of using the real tool.
    """
    exe = tools.find("opensta")
    if exe is None:
        raise RuntimeError(
            "OpenSTA not found. Build it from https://github.com/parallaxsw/OpenSTA "
            "or set FABAWARE_OPENSTA=/path/to/sta"
        )
    if not liberty:
        raise RuntimeError(
            "OpenSTA needs a Liberty (.lib) timing file. Supply one with "
            "--liberty, e.g. the open SkyWater SKY130 PDK."
        )
    os.makedirs(workdir, exist_ok=True)
    sdc_path = os.path.join(workdir, "fabaware.sdc")
    tcl_path = os.path.join(workdir, "fabaware.tcl")
    with open(sdc_path, "w") as f:
        f.write(write_sdc(clock_net=clock_net, period_ps=period_ps))
    with open(tcl_path, "w") as f:
        f.write(write_tcl(netlist, liberty, sdc_path, top=top,
                          out_dir=workdir, reports=reports))

    proc = subprocess.run([exe, "-no_splash", "-exit", tcl_path],
                          capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(
            f"OpenSTA failed (rc={proc.returncode}):\n"
            f"{(proc.stdout or '')[-1500:]}{(proc.stderr or '')[-1500:]}")

    res = StaResult(raw=proc.stdout or "")
    tpath = os.path.join(workdir, "sta_timing.rpt")
    ppath = os.path.join(workdir, "sta_power.rpt")
    if os.path.exists(tpath):
        r = parse_timing_report(open(tpath).read())
        res.worst_slack_ps = r.worst_slack_ps
        res.endpoints = r.endpoints
        res.path_nets = r.path_nets
    if "power" in reports and os.path.exists(ppath):
        res.power_mW = parse_power(open(ppath).read())
    return res


def slack_to_yield(slack_ps: float, sigma_ps: float) -> float:
    """
    Convert a deterministic OpenSTA slack into an estimated timing yield.

    OpenSTA gives one number for a nominal (or corner) analysis; it does not
    know about our within-die variation. We combine them: the chip passes if
    the random variation does not eat the slack.
    """
    from math import erf, sqrt
    if sigma_ps <= 0:
        return 1.0 if slack_ps >= 0 else 0.0
    z = slack_ps / (sigma_ps * sqrt(2.0))
    return 0.5 * (1.0 + erf(z))
