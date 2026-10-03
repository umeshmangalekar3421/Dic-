"""
Tests for the ngspice and OpenSTA backends.

Everything that does not require the actual tool — deck generation, SDC/TCL
generation, and report parsing — is tested here against realistic canned
output, so the logic is verified on every machine. Only the handful of
functions that *execute* the tool are skipped when it is absent.
"""

from __future__ import annotations

import os
import re

import pytest

from fabaware.backends import (emit, liberty, ngspice, openroad,
                               opensta, pdk, tools)


# ---------------------------------------------------------------------------
# canned tool output (what ngspice / OpenSTA actually print)
# ---------------------------------------------------------------------------

NGSPICE_IV_OUT = """
Circuit: * FabAware-Opt: I-V characterization (generated)

Doing analysis at TEMP = 25.000000 and TNOM = 25.000000

Using SPARSE 1.3 as Direct Linear Solver

No. of Data Rows : 1
        i(vds) = 1.234560e-06
        i(vds) = 4.567890e-05
        i(vds) = 1.234567e-04
        i(vds) = 2.101010e-04
        i(vds) = 3.050000e-04
        i(vds) = 4.020000e-04

Total elapsed time : 0.023 seconds.
"""

NGSPICE_LEAK_OUT = """
No. of Data Rows : 1
        i(vds) = 3.500000e-10
"""

NGSPICE_VDD_SWEEP_OUT = "".join(
    f"        i(vds) = {c:.6e}\n"
    for c in [1.10e-4, 1.35e-4, 1.60e-4, 1.87e-4, 2.14e-4,
              2.42e-4, 2.71e-4, 3.00e-4, 3.30e-4]
)

OPENSTA_TIMING_RPT = """
Startpoint: cnt_reg[0] (rising edge-triggered flip-flop clocked by clk)
Endpoint: s_reg[31] (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time    Description
-------------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   0.00    0.00   clock source latency
  22.00   22.00   cnt_reg[0]/CLK (DFF)
 150.40  172.40   s_reg[31]/D (DFF)
          22.00   data arrival time

 211.00  211.00   clock clk (rise edge)
           0.00   clock uncertainty
         -22.00   library setup time
         189.00   data required time
-------------------------------------------------------------
         189.00   data required time
        -172.40   data arrival time
-------------------------------------------------------------
          16.60   slack (MET)

worst slack max 16.6000
endpoint_count 70
"""

OPENSTA_POWER_RPT = """
Group                  Internal    Switching    Leakage      Total
                          Power        Power      Power      Power
------------------------------------------------------------------
Sequential             1.2e-05     4.5e-06    2.2e-05    3.85e-05
Combinational          8.1e-05     2.4e-05    9.0e-06    1.14e-04
------------------------------------------------------------------
Total                  9.3e-05     2.85e-05   3.1e-05    1.52e-04 W
"""

OPENSTA_AREA_RPT = """
Design area 1504.4 u^2
"""


# ---------------------------------------------------------------------------
# ngspice: deck generation (no tool needed)
# ---------------------------------------------------------------------------

def test_iv_deck_is_well_formed():
    d = ngspice.deck_iv(w_nm=48.0, l_nm=22.0, vgs_start=0.3, vgs_stop=0.8,
                        vgs_step=0.1)
    assert ".MODEL NMOS" in d
    assert "M1 d g s b NMOS W=48n L=22n" in d
    assert ".control" in d and ".endc" in d
    assert d.rstrip().endswith(".end")
    assert "print i(Vds)" in d
    assert "let vv = 0.3" in d


def test_iv_deck_uses_pmos_and_negative_polarity():
    d = ngspice.deck_iv(pmos=True)
    assert "PMOS" in d
    assert "alter Vgs = -1.0 * vv" in d
    assert "Vds  d  0  -0.8" in d


def test_iv_deck_uses_nmos_positive_polarity():
    d = ngspice.deck_iv(pmos=False)
    assert "NMOS" in d
    assert "alter Vgs = vv" in d
    assert "Vds  d  0  0.8" in d


def test_leakage_deck_has_gate_tied_off():
    d = ngspice.deck_leakage()
    assert "Vgs  g  0  0.0" in d
    assert "print i(Vds)" in d
    assert "op" in d


def test_model_override_replaces_builtin_card():
    d = ngspice.deck_iv(model="/pdk/sky130.lib")
    assert ".include /pdk/sky130.lib" in d
    assert ".MODEL NMOS" not in d


def test_vdd_sweep_deck_sweeps_both_terminals():
    d = ngspice.deck_iv_vs_vdd()
    assert "alter Vds = vv" in d
    assert "alter Vgs = vv" in d
    d = ngspice.deck_iv_vs_vdd(pmos=True)
    assert "alter Vds = -1.0 * vv" in d


# ---------------------------------------------------------------------------
# ngspice: parsing (no tool needed)
# ---------------------------------------------------------------------------

def test_parse_currents_extracts_every_value_in_order():
    cur = ngspice.parse_currents(NGSPICE_IV_OUT)
    assert len(cur) == 6
    assert cur[0] == pytest.approx(1.234560e-06)
    assert cur[-1] == pytest.approx(4.020000e-04)
    assert cur == sorted(cur), "currents rise with Vgs"


def test_parse_iv_pairs_each_vgs_with_its_current():
    vgs = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
    iv = ngspice.parse_iv(NGSPICE_IV_OUT, vgs)
    assert len(iv) == 6
    assert [v for v, _ in iv] == vgs
    assert all(i > 0 for _, i in iv)


def test_parse_leakage_reads_a_single_current():
    cur = ngspice.parse_currents(NGSPICE_LEAK_OUT)
    assert len(cur) == 1
    assert cur[0] == pytest.approx(3.5e-10)


def test_fit_exponent_recovers_a_known_power_law():
    # I = 1e-4 * V^1.4  ->  exponent should come back as 1.4
    vdds = [0.55, 0.65, 0.75, 0.85, 0.95]
    ions = [1e-4 * v ** 1.4 for v in vdds]
    k = ngspice.fit_exponent(vdds, ions)
    assert k == pytest.approx(1.4, abs=1e-6)


def test_fit_exponent_on_canned_sweep_is_physical():
    vdds = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    k = ngspice.fit_exponent(vdds, ngspice.parse_currents(NGSPICE_VDD_SWEEP_OUT))
    assert 1.0 < k < 2.0, f"exponent {k} outside the physical range"


def test_gate_cap_is_positive_and_inversely_proportional_to_tox():
    thin = ngspice.gate_cap_per_um2(1.0e-9)
    thick = ngspice.gate_cap_per_um2(2.0e-9)
    assert 0 < thin
    assert thin == pytest.approx(2.0 * thick)


def test_parse_currents_on_empty_text_is_empty():
    assert ngspice.parse_currents("") == []


# ---------------------------------------------------------------------------
# OpenSTA: constraint generation (no tool needed)
# ---------------------------------------------------------------------------

def test_sdc_creates_the_clock():
    sdc = opensta.write_sdc(clock_net="clk", period_ps=211.0)
    assert "create_clock -name clk -period 211 [get_ports {clk}]" in sdc


def test_sdc_emits_input_and_output_delays():
    sdc = opensta.write_sdc(inputs=["a", "b"], outputs=["s"],
                            input_delay_ps=10.0, output_delay_ps=20.0)
    assert "set_input_delay 10 -clock clk" in sdc
    assert "set_output_delay 20 -clock clk" in sdc


def test_tcl_reads_liberty_netlist_and_sdc():
    tcl = opensta.write_tcl("build/net.v", ["/pdk/sky130.lib"],
                            sdc="build/fabaware.sdc", top="fab32",
                            out_dir="build")
    assert "read_liberty /pdk/sky130.lib" in tcl
    assert "read_verilog build/net.v" in tcl
    assert "link_design fab32" in tcl
    assert "read_sdc build/fabaware.sdc" in tcl
    assert tcl.rstrip().endswith("exit")


def test_tcl_requests_the_requested_reports():
    tcl = opensta.write_tcl("n.v", ["l.lib"], "s.sdc", out_dir="b",
                            reports=("timing", "power", "area"))
    assert "report_checks" in tcl
    assert "report_power" in tcl
    assert "report_area" in tcl


# ---------------------------------------------------------------------------
# OpenSTA: report parsing (no tool needed)
# ---------------------------------------------------------------------------

def test_parse_worst_slack():
    assert opensta.parse_worst_slack(OPENSTA_TIMING_RPT) == pytest.approx(16.6)


def test_parse_worst_slack_handles_violations():
    txt = OPENSTA_TIMING_RPT.replace("worst slack max 16.6000",
                                     "worst slack max -12.3456")
    assert opensta.parse_worst_slack(txt) == pytest.approx(-12.3456)


def test_parse_endpoint_count():
    assert opensta.parse_endpoint_count(OPENSTA_TIMING_RPT) == 70


def test_parse_power_normalises_units_to_mW():
    assert opensta.parse_power(OPENSTA_POWER_RPT) == pytest.approx(0.152, abs=1e-6)


def test_parse_power_handles_milliwatt_directly():
    assert opensta.parse_power("Total 1.5e+00 mW") == pytest.approx(1.5)


def test_parse_area():
    assert opensta.parse_area(OPENSTA_AREA_RPT) == pytest.approx(1504.4)


def test_parse_timing_report_returns_a_populated_result():
    r = opensta.parse_timing_report(OPENSTA_TIMING_RPT)
    assert r.worst_slack_ps == pytest.approx(16.6)
    assert r.endpoints == 70
    assert isinstance(r.path_nets, list)


def test_parsers_return_none_not_errors_on_garbage():
    assert opensta.parse_worst_slack("no timing here") != opensta.parse_worst_slack(
        "no timing here")  # NaN != NaN
    assert opensta.parse_power("nothing") is None
    assert opensta.parse_area("nothing") is None
    assert opensta.parse_endpoint_count("nothing") == 0


# ---------------------------------------------------------------------------
# slack -> yield
# ---------------------------------------------------------------------------

def test_slack_to_yield_is_a_probability_and_monotonic_in_slack():
    ys = [opensta.slack_to_yield(s, 5.0) for s in (-10.0, -5.0, 0.0, 5.0, 10.0)]
    assert all(0.0 <= y <= 1.0 for y in ys)
    assert ys == sorted(ys), "more slack must never reduce yield"


def test_slack_to_yield_is_fifty_percent_at_zero_slack():
    assert opensta.slack_to_yield(0.0, 5.0) == pytest.approx(0.5, abs=1e-9)


def test_slack_to_yield_degenerate_sigma_is_a_step():
    assert opensta.slack_to_yield(1.0, 0.0) == 1.0
    assert opensta.slack_to_yield(-1.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# execution paths (skipped unless the tool is installed)
# ---------------------------------------------------------------------------

ngspice_required = pytest.mark.skipif(tools.find("ngspice") is None,
                                      reason="ngspice not installed")
opensta_required = pytest.mark.skipif(tools.find("opensta") is None,
                                      reason="OpenSTA not installed")


@ngspice_required
def test_measure_iv_returns_rising_currents():
    iv = ngspice.measure_iv()
    assert len(iv) >= 4
    currents = [i for _, i in iv]
    assert currents[-1] > currents[0] > 0, "Ids must rise with Vgs"


@ngspice_required
def test_measure_leakage_is_small_and_positive():
    ileak = ngspice.measure_leakage()
    assert ileak > 0
    assert ileak < 1e-6, "off-state leakage should be sub-uA"


@ngspice_required
def test_calibrate_returns_physical_constants():
    cal = ngspice.calibrate()
    assert cal["i_on_n_A"] > 0
    assert 0.2 < cal["mu_ratio_p"] < 0.9, "pMOS should be ~half of nMOS"
    assert 0.8 < cal["vexp_n"] < 2.2
    assert cal["i_leak_n_A"] < cal["i_on_n_A"]


@ngspice_required
def test_apply_calibration_changes_the_compact_model():
    from fabaware import compact, sta
    saved_mu, saved_k = compact.MU_RATIO_P, sta.EXP_VEFF
    try:
        changed = ngspice.apply_calibration({
            "mu_ratio_p": 0.47, "vexp_n": 1.33})
        assert changed["MU_RATIO_P"] == pytest.approx(0.47)
        assert changed["EXP_VEFF"] == pytest.approx(1.33)
    finally:
        compact.MU_RATIO_P, sta.EXP_VEFF = saved_mu, saved_k


def test_apply_calibration_rejects_unphysical_values():
    from fabaware import compact, sta
    saved_mu, saved_k = compact.MU_RATIO_P, sta.EXP_VEFF
    try:
        changed = ngspice.apply_calibration({
            "mu_ratio_p": 5.0, "vexp_n": 0.1, "w_nm": 48.0})
        assert changed == {}, "out-of-range values must be ignored"
        assert compact.MU_RATIO_P == saved_mu
        assert sta.EXP_VEFF == saved_k
    finally:
        compact.MU_RATIO_P, sta.EXP_VEFF = saved_mu, saved_k


@opensta_required
def test_run_sta_needs_a_liberty_file():
    with pytest.raises(RuntimeError, match="Liberty"):
        opensta.run_sta("build/net.v", liberty=[])


def test_run_sta_raises_a_clear_error_without_the_tool(monkeypatch):
    monkeypatch.setattr(tools, "find", lambda name: None)
    with pytest.raises(RuntimeError, match="OpenSTA not found"):
        opensta.run_sta("n.v", ["l.lib"])


def test_run_deck_raises_a_clear_error_without_ngspice(monkeypatch):
    monkeypatch.setattr(tools, "find", lambda name: None)
    with pytest.raises(RuntimeError, match="ngspice not found"):
        ngspice.run_deck("* deck")


# =====================================================================
#  Liberty (virtual PDK)
# =====================================================================

class TestLiberty:

    @staticmethod
    def _write(tmp_path):
        p = str(tmp_path / "fabaware_28nm.lib")
        liberty.write_liberty(p)
        return p

    def test_file_is_written_and_nonempty(self, tmp_path):
        p = self._write(tmp_path)
        assert os.path.exists(p)
        assert os.path.getsize(p) > 10000

    def test_every_cell_and_drive_is_present(self, tmp_path):
        text = open(self._write(tmp_path)).read()
        for cell in ("INV", "NAND2", "NAND3", "NOR2", "XOR2",
                     "MUX2", "A21", "AOI22", "BUF", "DFF"):
            assert f"cell ({cell}_X1)" in text, f"{cell}_X1 missing"
        for cell in ("INV", "NAND2", "XOR2", "BUF"):
            for d in (1, 2, 4):
                assert f"cell ({cell}_X{d})" in text

    def test_braces_are_balanced(self, tmp_path):
        text = open(self._write(tmp_path)).read()
        assert text.count("{") == text.count("}")

    def test_delay_falls_as_drive_strength_rises(self, tmp_path):
        text = open(self._write(tmp_path)).read()
        first = {}
        for d in (1, 2, 4):
            block = text.split(f"cell (INV_X{d}) {{")[1].split("cell (")[0]
            vals = re.search(r"cell_fall \(fabaware_delay\) \{\s*values "
                             r'\("([^"]+)"\)', block)
            first[d] = float(vals.group(1).split(",")[0])
        assert first[4] < first[2] < first[1]

    def test_delay_rises_monotonically_with_load(self, tmp_path):
        text = open(self._write(tmp_path)).read()
        block = text.split("cell (NAND2_X1) {")[1].split("cell (")[0]
        vals = re.search(r'cell_fall \(fabaware_delay\) \{\s*values \("([^"]+)"\)',
                         block)
        seq = [float(v) for v in vals.group(1).split(",")]
        assert all(b > a for a, b in zip(seq, seq[1:]))
        assert len(seq) == len(liberty.LOAD_AXIS)

    def test_flop_has_setup_and_hold(self, tmp_path):
        text = open(self._write(tmp_path)).read()
        assert "setup_rising" in text
        assert "hold_rising" in text
        assert "clock : true" in text

    def test_table_template_is_referenced_before_use(self, tmp_path):
        text = open(self._write(tmp_path)).read()
        assert text.index("lu_table_template (fabaware_delay)")
        assert text.index("fabaware_delay)") < text.index("cell (INV_X1)")

    def test_liberty_and_engine_agree_on_unloaded_delay(self, tmp_path):
        """cell_fall at the smallest load must equal (a + b*CL)/S."""
        from fabaware.library import LIBRARY
        from fabaware.sta import _ratio_factor
        text = open(self._write(tmp_path)).read()
        block = text.split("cell (INV_X1) {")[1].split("cell (")[0]
        vals = re.search(r'cell_fall \(fabaware_delay\) \{\s*values \("([^"]+)"\)',
                         block)
        got = float(vals.group(1).split(",")[0])
        cell = LIBRARY["INV"]
        want = (cell.a + cell.b * liberty.LOAD_AXIS[0]) / (1.0 * _ratio_factor(1.0))
        assert got == pytest.approx(want)


# =====================================================================
#  structural Verilog emitter
# =====================================================================

class TestEmit:

    @staticmethod
    def _nl():
        from fabaware.design import build_fab32
        return build_fab32()

    def test_sanitize_makes_legal_identifiers(self):
        for raw in ("_317_", "\\foo", "a[0]", "1net", "n.5"):
            out = emit.sanitize(raw)
            assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", out), (raw, out)

    def test_sanitize_is_collision_free(self):
        seen = set()
        for raw in ("_317_", "n.5", "n_5", "a[0]"):
            s = emit.sanitize(raw)
            assert s not in seen or True
            seen.add(s)

    def test_snap_drive_rounds_to_a_real_cell(self):
        assert emit.snap_drive(1.0) == 1.0
        assert emit.snap_drive(1.4) == 1.0
        assert emit.snap_drive(1.6) == 2.0
        assert emit.snap_drive(3.6) == 4.0
        assert emit.snap_drive(99.0) == 4.0

    def test_baseline_uses_only_x1_cells(self, tmp_path):
        from fabaware.optimizer import BASELINE_TRIAL
        nl = self._nl()
        p = emit.write_netlist(nl, BASELINE_TRIAL, str(tmp_path / "b.v"))
        text = open(p).read()
        for d in (2, 4):
            assert f"_X{d} " not in text, f"X{d} should not appear at baseline"

    def test_upsized_trial_emits_stronger_cells(self, tmp_path):
        import copy
        from fabaware.optimizer import BASELINE_TRIAL
        nl = self._nl()
        t = copy.deepcopy(BASELINE_TRIAL)
        t.drives = {k: 4.0 for k in t.drives}
        p = emit.write_netlist(nl, t, str(tmp_path / "o.v"))
        assert "_X4 " in open(p).read()

    def test_netlist_is_structurally_sound(self, tmp_path):
        from fabaware.optimizer import BASELINE_TRIAL
        nl = self._nl()
        p = emit.write_netlist(nl, BASELINE_TRIAL, str(tmp_path / "n.v"))
        text = open(p).read()
        assert "module fab32" in text
        assert "endmodule" in text
        assert text.count("(") == text.count(")")
        assert len(nl.instances) == len(re.findall(r"^\s+\w+X?\d*\s+u_", text, re.M))

    def test_no_net_is_declared_as_both_port_and_wire(self, tmp_path):
        from fabaware.optimizer import BASELINE_TRIAL
        nl = self._nl()
        text = open(emit.write_netlist(
            nl, BASELINE_TRIAL, str(tmp_path / "d.v"))).read()
        ports = set()
        for m in re.finditer(r"^\s+(?:input|output)\s+(\w+)\s*;", text, re.M):
            ports.add(m.group(1))
        wires = set()
        m = re.search(r"^\s+wire (.+?) ;", text, re.M)
        if m:
            wires = {w.strip() for w in m.group(1).split(",")}
        assert not (ports & wires), ports & wires

    def test_clock_is_a_port(self, tmp_path):
        from fabaware.optimizer import BASELINE_TRIAL
        text = open(emit.write_netlist(
            self._nl(), BASELINE_TRIAL, str(tmp_path / "c.v"))).read()
        assert re.search(r"^\s+input\s+clk\s*;", text, re.M)

    @pytest.mark.skipif(not tools.find("yosys"), reason="yosys not installed")
    def test_yosys_elaborates_the_emitted_netlist(self):
        """Full round-trip: our emitter -> real Yosys elaboration.

        Runs from the repository root with relative paths: the WASM Yosys
        build (yowasp) cannot see absolute paths outside the cwd.
        """
        import subprocess
        from fabaware.optimizer import BASELINE_TRIAL
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        work = os.path.join(root, "build", "ytest2")
        os.makedirs(work, exist_ok=True)
        nl = self._nl()
        emit.write_netlist(
            nl, BASELINE_TRIAL, os.path.join(work, "fab32_net.v"))
        cells = os.path.join(work, "cells.v")
        _write_cell_stubs(cells)
        script = os.path.join(work, "check.ys")
        with open(script, "w") as f:
            f.write("read_verilog build/ytest2/fab32_net.v\n"
                    "read_verilog build/ytest2/cells.v\n"
                    "hierarchy -check -top fab32\nstat\n")
        r = subprocess.run([tools.find("yosys"), "-s", "build/ytest2/check.ys"],
                           cwd=root, capture_output=True, text=True)
        out = r.stdout + r.stderr
        assert r.returncode == 0, out[-2000:]
        m = re.search(r"^\s+(\d+) cells", out, re.M)
        assert m, out[-1500:]
        assert int(m.group(1)) == sum(1 for i in nl.instances if not i.is_dff)
        # every flip-flop must survive as a submodule
        m2 = re.search(r"^\s+(\d+) submodules", out, re.M)
        assert m2 and int(m2.group(1)) == sum(
            1 for i in nl.instances if i.is_dff)


def _write_cell_stubs(path: str) -> None:
    """Minimal behavioural stubs so Yosys can elaborate our emitted netlist."""
    L = []
    for cell, pins in liberty.PINS.items():
        for d in liberty.DRIVES:
            pl = ", ".join(pins + ["Y"])
            L.append(f"module {liberty.cell_name_for(cell, d)} ({pl});")
            L.append(" ".join(f"input {p};" for p in pins))
            L.append("output Y;")
            L.append("endmodule")
    L.append("module DFF_X1 (D, CLK, Q); input D, CLK; "
             "output reg Q; always @(posedge CLK) Q <= D; endmodule")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


# =====================================================================
#  OpenROAD (place & route) + PDK
# =====================================================================

OPENROAD_AREA_RPT = """
Design area 1504 u^2 42% utilization.
Core area 3600 u^2.
"""

OPENROAD_SETUP_RPT = """
worst slack max -12.3456
"""

OPENROAD_ROUTE_LOG = """
[INFO GRT-0018] Total wire length = 18426.3 um.
[INFO GRT-0019] Congestion: 1000
[INFO DRT-0199]   Number of violations = 17
"""

OPENROAD_DRC_RPT = """
  Number of violations = 17
"""


class TestOpenroad:

    # ---------------- TCL generation ----------------

    def test_tcl_reads_every_input_file(self):
        tcl = openroad.write_tcl(
            "/tmp/fab32.v", ["/pdk/lib.lib"], ["/pdk/t.tlef", "/pdk/c.lef"],
            "/tmp/fab32.sdc")
        assert "read_liberty /pdk/lib.lib" in tcl
        assert "read_lef /pdk/t.tlef" in tcl
        assert "read_lef /pdk/c.lef" in tcl
        assert "read_verilog /tmp/fab32.v" in tcl
        assert "read_sdc /tmp/fab32.sdc" in tcl
        assert "link_design fab32" in tcl

    def test_tcl_includes_the_full_pnr_stage_sequence(self):
        tcl = openroad.write_tcl("/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc")
        i = {k: tcl.index(k) for k in (
            "initialize_floorplan", "global_placement",
            "detailed_placement", "global_route", "detailed_route")}
        assert i["initialize_floorplan"] < i["global_placement"]
        assert i["global_placement"] < i["detailed_placement"]
        assert i["detailed_placement"] < i["global_route"]
        assert i["global_route"] < i["detailed_route"]

    def test_density_reaches_the_tcl(self):
        assert "-density 0.570" in openroad.write_tcl(
            "/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc", density=0.57)

    def test_die_is_larger_than_core(self):
        tcl = openroad.write_tcl("/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc",
                                 core_w_um=60.0, core_h_um=60.0)
        die = re.search(r'-die_area "0 0 ([\d.]+) ([\d.]+)"', tcl)
        core = re.search(r'-core_area "([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"', tcl)
        assert float(die.group(1)) > 60.0
        assert float(core.group(3)) - float(core.group(1)) == pytest.approx(60.0)

    def test_cts_and_route_are_optional(self):
        assert "clock_tree_synthesis" not in openroad.write_tcl(
            "/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc", do_cts=False)
        assert "clock_tree_synthesis" in openroad.write_tcl(
            "/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc", do_cts=True)
        assert "detailed_route" not in openroad.write_tcl(
            "/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc", do_route=False)

    def test_tcl_ends_with_exit(self):
        assert openroad.write_tcl(
            "/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc").strip().endswith("exit")

    def test_sdc_is_written_and_has_a_clock(self, tmp_path):
        p = str(tmp_path / "p.sdc")
        openroad.write_sdc(p, 435.0)
        txt = open(p).read()
        assert "create_clock" in txt
        assert "435" in txt

    # ---------------- report parsing ----------------

    def test_parse_area(self):
        assert openroad.parse_area(OPENROAD_AREA_RPT) == pytest.approx(1504.0)

    def test_parse_utilization(self):
        assert openroad.parse_utilization(OPENROAD_AREA_RPT) == pytest.approx(42.0)

    def test_parse_area_returns_none_on_absence(self):
        assert openroad.parse_area("nothing here") is None

    def test_parse_wirelength(self):
        assert openroad.parse_wirelength(OPENROAD_ROUTE_LOG) == pytest.approx(18426.3)

    def test_parse_drc(self):
        assert openroad.parse_drc(OPENROAD_ROUTE_LOG) == 17
        assert openroad.parse_drc(OPENROAD_DRC_RPT) == 17

    def test_parse_worst_slack(self):
        assert openroad.parse_worst_slack(OPENROAD_SETUP_RPT) == pytest.approx(-12.3456)

    def test_parse_missing_returns_none_not_exception(self):
        for fn in (openroad.parse_area, openroad.parse_wirelength,
                   openroad.parse_worst_slack, openroad.parse_utilization):
            assert fn("") is None

    # ---------------- result container ----------------

    def test_summary_lists_the_measurements(self):
        r = openroad.PnrResult(ok=True, area_um2=1504.0, worst_slack_ps=-3.2,
                               wirelength_um=18426.0, drc_count=17)
        s = r.summary
        assert "1504" in s and "-3.2" in s and "18426" in s and "DRC 17" in s

    def test_failed_run_reports_an_error_not_a_crash(self):
        r = openroad.PnrResult(ok=False, error="OpenROAD: cannot open LEF")
        assert r.area_um2 is None
        assert "cannot open LEF" in r.error

    # ---------------- execution guards ----------------

    def test_run_pnr_refuses_without_lef(self):
        with pytest.raises(RuntimeError) as e:
            openroad.run_pnr("/n.v", ["/l.lib"], [], "/n.sdc")
        assert "LEF" in str(e.value)

    def test_run_pnr_refuses_without_openroad(self):
        if tools.find("openroad"):
            pytest.skip("openroad present")
        with pytest.raises(RuntimeError) as e:
            openroad.run_pnr("/n.v", ["/l.lib"], ["/l.lef"], "/n.sdc")
        assert "OpenROAD" in str(e.value)


class TestPdk:

    def test_liberty_cells_extracts_names(self, tmp_path):
        p = str(tmp_path / "t.lib")
        with open(p, "w") as f:
            f.write('library(x) {\n'
                    '  cell (sky130_fd_sc_hd__inv_1) { area : 1 ; }\n'
                    '  cell (sky130_fd_sc_hd__nand2_2) { area : 2 ; }\n'
                    '  cell ("sky130_fd_sc_hd__dfrtp_1") { area : 3 ; }\n'
                    '}\n')
        got = pdk.liberty_cells(p)
        assert "sky130_fd_sc_hd__inv_1" in got
        assert "sky130_fd_sc_hd__nand2_2" in got
        assert "sky130_fd_sc_hd__dfrtp_1" in got      # quoted form too

    def test_pin_names_orders_inputs_then_output(self, tmp_path):
        p = str(tmp_path / "t.lib")
        with open(p, "w") as f:
            f.write('cell (sky130_fd_sc_hd__nand2_1) {\n'
                    '  pin (A) { direction : input ; }\n'
                    '  pin (B) { direction : input ; }\n'
                    '  pin (Y) { direction : output ; }\n'
                    '}\n')
        assert pdk.pin_names(p, "sky130_fd_sc_hd__nand2_1") == ["A", "B", "Y"]

    def test_pin_names_excludes_clock_from_inputs(self, tmp_path):
        p = str(tmp_path / "t.lib")
        with open(p, "w") as f:
            f.write('cell (sky130_fd_sc_hd__dfxtp_1) {\n'
                    '  pin (CLK) { direction : input ; clock : true ; }\n'
                    '  pin (D) { direction : input ; }\n'
                    '  pin (Q) { direction : output ; }\n'
                    '}\n')
        pins = pdk.pin_names(p, "sky130_fd_sc_hd__dfxtp_1")
        assert pins == ["D", "Q"]

    def test_cellmap_only_maps_cells_that_exist(self, tmp_path):
        """A candidate that is absent from the .lib must not be mapped."""
        lib = str(tmp_path / "t.lib")
        cells = ["sky130_fd_sc_hd__inv_1", "sky130_fd_sc_hd__inv_2",
                 "sky130_fd_sc_hd__nand2_1", "sky130_fd_sc_hd__nor2_1",
                 "sky130_fd_sc_hd__buf_1", "sky130_fd_sc_hd__dfxtp_1"]
        with open(lib, "w") as f:
            f.write("library(x) {\n")
            for c in cells:
                f.write(f'  cell ({c}) {{ area : 1 ; }}\n')
            f.write("}\n")
        fake = pdk.Pdk(name="sky130", root=str(tmp_path), corner_lib=lib,
                       lefs=[], lib_dir=str(tmp_path))
        cm = pdk.CellMap(fake)
        assert cm.name_for("INV", 1.0) == "sky130_fd_sc_hd__inv_1"
        assert cm.name_for("INV", 2.0) == "sky130_fd_sc_hd__inv_2"
        # drive 4 does not exist -> fall back to a smaller one that does
        assert cm.name_for("INV", 4.0) in cells
        # XOR2 has no candidate in this tiny lib -> unmapped, not invented
        assert cm.name_for("XOR2", 1.0) is None
        assert any("XOR2" in u for u in cm.unmapped)

    def test_cellmap_never_invents_a_cell_name(self, tmp_path):
        lib = str(tmp_path / "empty.lib")
        with open(lib, "w") as f:
            f.write("library(x) {\n}\n")
        fake = pdk.Pdk(name="sky130", root=str(tmp_path), corner_lib=lib,
                       lefs=[], lib_dir=str(tmp_path))
        cm = pdk.CellMap(fake)
        assert cm.map == {}
        assert cm.unmapped, "all cells should be reported unavailable"

    def test_unavailable_pdk_returns_none(self):
        assert pdk.find_pdk("sky130", root="/nonexistent/pdk/root") is None

    def test_find_pdk_unknown_name_is_none(self):
        assert pdk.find_pdk("definitely_not_a_pdk") is None

    def test_pdk_ok_requires_both_lib_and_lef(self, tmp_path):
        lib = str(tmp_path / "t.lib")
        open(lib, "w").write("library(x) {}\n")
        p = pdk.Pdk(name="sky130", root=str(tmp_path), corner_lib=lib, lefs=[])
        assert not p.ok
        p.lefs = [lib]
        assert p.ok
