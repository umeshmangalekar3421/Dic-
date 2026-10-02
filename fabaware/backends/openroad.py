"""
OpenROAD backend — real place & route.
======================================

OpenROAD is the open-source RTL-to-GDSII flow: floorplan, global placement,
detailed placement, clock tree synthesis and detailed routing. It replaces
``fabaware/pd.py``'s analytic model with a genuine physical implementation.

Unlike the ngspice and OpenSTA backends, this one **requires a real PDK**.
Placement needs actual cell *shapes* (LEF) and routing needs a real layer
stack — there is nothing meaningful to fall back to, so :func:`run_pnr`
raises with an actionable message when no PDK is available.

What it gives back
------------------
The point of routing for real is that **wire length and DRC count stop being
estimates**. Our model predicts them; OpenROAD measures them. Feeding those
measurements back is what makes the rest of the numbers defensible.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Sequence

from . import tools


# ---------------------------------------------------------------------------
# TCL generation  (pure - testable without OpenROAD)
# ---------------------------------------------------------------------------

def write_tcl(
    netlist: str,
    liberty: Sequence[str],
    lefs: Sequence[str],
    sdc: str,
    top: str = "fab32",
    out_dir: str = "build/openroad",
    core_w_um: float = 60.0,
    core_h_um: float = 60.0,
    density: float = 0.70,
    site: Optional[str] = None,
    clock_net: str = "clk",
    do_cts: bool = False,
    do_route: bool = True,
) -> str:
    """
    Generate an OpenROAD script: floorplan -> place -> (CTS) -> route.

    Returns the TCL text. Paths are written as given, so pass absolute paths
    (OpenROAD is a native binary and has no sandbox path restrictions).
    """
    L: List[str] = []
    w = L.append
    w("# FabAware-Opt: generated OpenROAD script")
    w(f"set output_dir {out_dir}")
    w("file mkdir $output_dir")
    w("")

    for lib in liberty:
        w(f"read_liberty {lib}")
    for lef in lefs:
        w(f"read_lef {lef}")
    w(f"read_verilog {netlist}")
    w(f"link_design {top}")
    w(f"read_sdc {sdc}")
    w("")

    # --- floorplan -----------------------------------------------------
    margin = 5.0
    die_w, die_h = core_w_um + 2 * margin, core_h_um + 2 * margin
    fp = (f"initialize_floorplan -die_area \"0 0 {die_w:.3f} {die_h:.3f}\" "
          f"-core_area \"{margin:.3f} {margin:.3f} "
          f"{margin + core_w_um:.3f} {margin + core_h_um:.3f}\"")
    if site:
        fp += f" -site {site}"
    w(fp)
    w("")

    # --- pin placement -------------------------------------------------
    w("place_pins -random_seed 42 -random")
    w("")

    # --- power rails ---------------------------------------------------
    w("# optional power grid - skipped for a standard-cell only experiment")
    w("")

    # --- placement -----------------------------------------------------
    w(f"global_placement -density {density:.3f} -pad_left 2 -pad_right 2 "
      f"-overflow 0.2")
    w("detailed_placement")
    w("")

    # --- timing repair + clock tree ------------------------------------
    w("estimate_parasitics -placement")
    w("repair_design")
    if do_cts:
        w("repair_clock_nets")
        w("clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_16 "
          "-buf_list sky130_fd_sc_hd__clkbuf_16 -sink_clustering_size 10 "
          "-sink_clustering_max_diameter 50")
        w("set_propagated_clock [all_clocks]")
        w("detailed_placement")
    w("")

    # --- routing -------------------------------------------------------
    if do_route:
        w("global_route -guide_file $output_dir/route.guide "
          "-congestion_iterations 50 -verbose")
        w("detailed_route -output_drc $output_dir/route_drc.rpt "
          "-output_maze $output_dir/route_maze.log -verbose 0")
        w("")

    # --- reports -------------------------------------------------------
    for name, cmd in (
        ("area", "report_design_area"),
        ("timing_setup", "report_worst_slack -max"),
        ("timing_hold", "report_worst_slack -min"),
        ("checks", "report_checks -path_delay max -fields {slew cap input nets fanout} -digits 4"),
    ):
        w(f"{cmd} > $output_dir/sta_{name}.rpt")

    if do_route:
        w(f"write_def $output_dir/{top}.def")
    w("exit")
    w("")
    return "\n".join(L)


def write_sdc(path: str, period_ps: float, clock_net: str = "clk") -> str:
    """Minimal SDC for place & route."""
    text = (
        "# FabAware-Opt: generated constraints for P&R\n"
        f"create_clock -name {clock_net} -period {period_ps:.6g} "
        f"[get_ports {{{clock_net}}}]\n"
        "set_clock_uncertainty 0.0 [get_clocks *]\n"
        f"set_input_transition 0.010 [all_inputs]\n"
        f"set_load 0.005 [all_outputs]\n"
        "\n"
    )
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    return text


# ---------------------------------------------------------------------------
# result container + parsers  (pure - testable with canned output)
# ---------------------------------------------------------------------------

@dataclass
class PnrResult:
    """What we can extract from an OpenROAD run."""
    ok: bool = False
    area_um2: Optional[float] = None
    cell_area_um2: Optional[float] = None
    utilization: Optional[float] = None
    worst_slack_ps: Optional[float] = None
    hold_slack_ps: Optional[float] = None
    wirelength_um: Optional[float] = None
    drc_count: Optional[int] = None
    def_path: Optional[str] = None
    raw: str = ""
    error: str = ""

    @property
    def summary(self) -> str:
        bits = []
        if self.area_um2 is not None:
            bits.append(f"area {self.area_um2:.0f} um2")
        if self.worst_slack_ps is not None:
            bits.append(f"slack {self.worst_slack_ps:+.1f} ps")
        if self.wirelength_um is not None:
            bits.append(f"wire {self.wirelength_um:.0f} um")
        bits.append(f"DRC {self.drc_count if self.drc_count is not None else 'n/a'}")
        return ", ".join(bits)


#: OpenROAD: "Design area 1504 u^2 38% utilization"
_AREA_RE = re.compile(
    r"design\s+area\s+([-\d.eE+]+)\s*u\^2\s*(?:([-\d.eE+]+)\s*u\^2)?"
    r"\s*(?:([-\d.eE+]+)\s*%\s*utilization)?", re.I)

#: global_route: "Total wire length = 12345.6 um"
_WL_RE = re.compile(r"total\s+wire\s+length\s*[=:]\s*([-\d.eE+]+)\s*um", re.I)

#: detailed_route DRC report: "Number of violations = 12"
_DRC_RE = re.compile(r"(?:number\s+of\s+violations|total\s+violations)"
                     r"\s*[=:]\s*(\d+)", re.I)
#: ALT: the .drc.rpt file lists "violation" lines
_DRC_ALT_RE = re.compile(r"^\s*(\d+)\s+(?:short|metspc|endspc|offgrid)\b",
                         re.I | re.M)

_WS_RE = re.compile(
    r"worst\s+slack(?:\s+(?:max|min))*\s*(-?[\d.]+)", re.I)


def parse_area(text: str) -> Optional[float]:
    """Design area in um^2."""
    m = _AREA_RE.search(text)
    return float(m.group(1)) if m else None


def parse_utilization(text: str) -> Optional[float]:
    m = _AREA_RE.search(text)
    if m and m.group(3):
        try:
            return float(m.group(3))
        except ValueError:
            return None
    return None


def parse_wirelength(text: str) -> Optional[float]:
    m = _WL_RE.search(text)
    return float(m.group(1)) if m else None


def parse_drc(text: str) -> Optional[int]:
    """Number of DRC violations from OpenROAD's routing output."""
    m = _DRC_RE.search(text)
    if m:
        return int(m.group(1))
    # the .drc.rpt format counts one line per violation type
    total = sum(int(x) for x in _DRC_ALT_RE.findall(text))
    return total if total else _count_violation_lines(text)


def _count_violation_lines(text: str) -> Optional[int]:
    """Fallback: count lines that look like individual violations."""
    n = 0
    for line in text.splitlines():
        low = line.lower()
        if "violation" in low and "number of violations" not in low \
                and "total violations" not in low:
            if re.search(r"\b(short|spacing|width|area|enclosure)\b", low):
                n += 1
    return n if n else None


def parse_worst_slack(text: str) -> Optional[float]:
    m = _WS_RE.search(text)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# running OpenROAD
# ---------------------------------------------------------------------------

def run_pnr(
    netlist: str,
    liberty: Sequence[str],
    lefs: Sequence[str],
    sdc: str,
    top: str = "fab32",
    out_dir: str = "build/openroad",
    density: float = 0.70,
    core_w_um: float = 60.0,
    core_h_um: float = 60.0,
    site: Optional[str] = None,
    do_cts: bool = False,
    do_route: bool = True,
    timeout_s: int = 1800,
    metrics: str = "",
) -> PnrResult:
    """
    Run OpenROAD floorplan -> place -> route on a netlist.

    Requires LEF files (i.e. a real PDK); raises if they are missing, because
    placement without real cell geometry is not a meaningful experiment.
    """
    if not lefs:
        raise RuntimeError(
            "OpenROAD needs LEF files (physical cell layouts). Install the "
            "SKY130 PDK with:  pip install volare && volare enable --pdk sky130 <version>")
    exe = tools.find("openroad")
    if exe is None:
        raise RuntimeError(
            "OpenROAD not found. Install it or set FABAWARE_OPENROAD=/path/to/openroad")

    os.makedirs(out_dir, exist_ok=True)
    tcl = os.path.join(out_dir, "pnr.tcl")
    with open(tcl, "w") as f:
        f.write(write_tcl(netlist, liberty, lefs, sdc, top=top, out_dir=out_dir,
                          density=density, core_w_um=core_w_um,
                          core_h_um=core_h_um, site=site, do_cts=do_cts,
                          do_route=do_route))
    if metrics:
        with open(os.path.join(out_dir, "metrics.tcl"), "w") as f:
            f.write(metrics)

    proc = subprocess.run([exe, "-no_splash", "-exit", tcl],
                          capture_output=True, text=True, timeout=timeout_s)
    out = (proc.stdout or "") + (proc.stderr or "")

    res = PnrResult(raw=out)
    if proc.returncode != 0:
        res.error = out[-2000:]
        return res

    res.ok = True

    def _read(name: str) -> str:
        p = os.path.join(out_dir, name)
        return open(p, errors="ignore").read() if os.path.exists(p) else ""

    area_txt = _read("sta_area.rpt")
    if area_txt:
        res.area_um2 = parse_area(area_txt)
        res.utilization = parse_utilization(area_txt)
    else:
        res.area_um2 = parse_area(out)
        res.utilization = parse_utilization(out)

    setup = _read("sta_timing_setup.rpt") or out
    res.worst_slack_ps = parse_worst_slack(setup)
    hold = _read("sta_timing_hold.rpt")
    if hold:
        res.hold_slack_ps = parse_worst_slack(hold)

    res.wirelength_um = parse_wirelength(out)

    drc_txt = _read("route_drc.rpt")
    if drc_txt:
        res.drc_count = parse_drc(drc_txt) or 0
    else:
        res.drc_count = parse_drc(out)

    dpath = os.path.join(out_dir, f"{top}.def")
    if os.path.exists(dpath):
        res.def_path = dpath
    return res
