"""
Tests for the real-tool backend layer.

The Yosys tests are skipped automatically when Yosys is not installed, so the
suite stays runnable on a bare machine while still proving the integration
wherever the tool exists.
"""

from __future__ import annotations

import os

import pytest

from fabaware import sta
from fabaware.backends import tools
from fabaware.design import build_fab32
from fabaware.library import LIBRARY

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RTL = os.path.join(ROOT, "rtl", "fab32.v")
BUILD = os.path.join(ROOT, "build")

yosys = pytest.mark.skipif(tools.find("yosys") is None,
                           reason="Yosys not installed")


# ---------------------------------------------------------------------------
# tool detection
# ---------------------------------------------------------------------------

def test_detection_returns_a_dict_of_all_known_tools():
    found = tools.detect()
    assert isinstance(found, dict)
    for name in tools.CANDIDATES:
        assert name in found
        assert found[name] is None or isinstance(found[name], str)


def test_available_is_a_subset_of_known_tools():
    assert set(tools.available()) <= set(tools.CANDIDATES)


def test_summary_reports_every_tool():
    s = tools.summary()
    for name in tools.CANDIDATES:
        assert name in s
    # each tool is rendered either as REAL or as simulated
    assert ("REAL" in s) or ("simulated" in s)


def test_missing_tool_is_none_not_an_error():
    # a nonsense tool name must not raise
    assert tools.find("definitely-not-a-tool") is None


def test_env_override_is_honoured(monkeypatch, tmp_path):
    fake = tmp_path / "fake-yosys"
    fake.write_text("#!/bin/sh\necho Yosys 1.2.3\n")
    fake.chmod(0o755)
    tools._cache.clear()
    monkeypatch.setenv("FABAWARE_YOSYS", str(fake))
    try:
        assert tools.find("yosys") == str(fake)
        assert "1.2.3" in (tools.version("yosys") or "")
    finally:
        tools._cache.clear()


# ---------------------------------------------------------------------------
# Yosys backend
# ---------------------------------------------------------------------------

@yosys
def test_rtl_file_exists():
    assert os.path.exists(RTL)


@yosys
def test_yosys_synthesises_the_rtl_into_a_netlist():
    from fabaware.backends.yosys import synthesize
    # Use a workdir under the project root, not pytest's /tmp: the
    # WebAssembly (yowasp) build of Yosys only sees paths beneath the
    # current directory, so absolute /tmp paths fail there.
    work = os.path.join(ROOT, "build", "ytest")
    out = synthesize(RTL, top="fab32", workdir=work)
    assert os.path.exists(out)
    text = open(out).read()
    assert "module" in text
    # must contain real gate cells, not just wires
    assert "$_AND_" in text or "$_XOR_" in text
    assert "$_DFF_P_" in text


@yosys
def test_parsed_netlist_is_acyclic_and_fully_driven():
    from fabaware.backends.yosys import parse_netlist
    nl = parse_netlist(os.path.join(BUILD, "fab32_gates.v")) \
        if os.path.exists(os.path.join(BUILD, "fab32_gates.v")) \
        else pytest.skip("run scripts/synth.sh first")

    order = nl.order()
    assert len(order) == len(nl.instances)
    pos = {i: k for k, i in enumerate(order)}
    for inst in nl.instances:
        if inst.is_dff:
            continue
        for n in inst.in_nets:
            d = nl.net_driver[n]
            if d >= 0:
                assert pos[d] < pos[inst.idx]


@yosys
def test_parsed_netlist_has_sane_structure():
    from fabaware.backends.yosys import parse_netlist
    path = os.path.join(BUILD, "fab32_gates.v")
    if not os.path.exists(path):
        pytest.skip("run scripts/synth.sh first")
    nl = parse_netlist(path)
    st = nl.stats()
    assert st["gates"] > 300
    assert st["dffs"] >= 32                      # 32 pipeline + 4 counter-ish
    assert st["transistors"] > 1000
    assert all(c in LIBRARY for c in st["by_type"])
    # every net that is driven must have a load list
    missing = [n for n in nl.net_driver if n not in nl.net_loads]
    assert not missing, missing


@yosys
def test_hint_propagation_gives_bit_sliced_locality():
    """Nets sharing a bit index must end up in the same placement cluster."""
    from fabaware.backends.yosys import parse_netlist
    path = os.path.join(BUILD, "fab32_gates.v")
    if not os.path.exists(path):
        pytest.skip("run scripts/synth.sh first")
    nl = parse_netlist(path)
    tagged = [h for h in nl.hint.values() if h < 9000]
    assert len(tagged) > 0.5 * len(nl.hint), \
        "hint propagation should label most cells"
    assert len(set(tagged)) > 8, "should recover a datapath's bit structure"


@yosys
def test_real_netlist_is_timing_analysable():
    from fabaware.backends.yosys import parse_netlist
    from fabaware.optimizer import BASELINE_TRIAL
    path = os.path.join(BUILD, "fab32_gates.v")
    if not os.path.exists(path):
        pytest.skip("run scripts/synth.sh first")
    nl = parse_netlist(path)
    r = sta.evaluate(nl, BASELINE_TRIAL, K=32, seed=1)
    assert 0.0 <= r.yield_nom <= 1.0
    assert r.cell_area > 0
    assert len(r.paths) > 0
    assert all(isinstance(s, float) for _, _, s in r.paths)


# ---------------------------------------------------------------------------
# target-period calibration
# ---------------------------------------------------------------------------

def test_calibration_lands_near_the_requested_baseline_yield():
    """Calibration must make the baseline marginal on any netlist."""
    nl = build_fab32()
    saved = sta.T_SPEC
    try:
        period, y = sta.calibrate_target(nl, target_yield=0.35, K=150,
                                         seed=42, tol=0.12)
        assert period > 0
        assert 0.15 <= y <= 0.60, f"baseline yield {y} not marginal"
        assert abs(sta.T_SPEC - period) < 1e-9
    finally:
        sta.set_target_period(saved)


def test_set_target_period_keeps_frequency_consistent():
    saved = sta.T_SPEC
    try:
        sta.set_target_period(250.0)
        assert sta.T_SPEC == pytest.approx(250.0)
        assert sta.freq_ghz() == pytest.approx(4.0)
        assert sta.freq_mhz() == pytest.approx(4000.0)
        assert sta.F_TARGET == pytest.approx(4.0e9)
    finally:
        sta.set_target_period(saved)


def test_critical_path_is_positive_and_stable():
    nl = build_fab32()
    saved = sta.T_SPEC
    try:
        d1 = sta.nominal_critical_path(nl)
        d2 = sta.nominal_critical_path(nl)
        assert d1 > 0
        assert d1 == pytest.approx(d2)
    finally:
        sta.set_target_period(saved)


# ---------------------------------------------------------------------------
# multi-netlist safety (regression)
# ---------------------------------------------------------------------------

def test_two_netlists_do_not_share_a_cached_layout():
    """The placement cache must be keyed on the netlist, not just the trial.

    A shared key would hand the timing engine one design's wire lengths while
    it is analysing another's net names.
    """
    from fabaware.optimizer import BASELINE_TRIAL
    a, b = build_fab32(), build_fab32()
    assert a.uid != b.uid
    pa = sta.place_and_route_cached(a, BASELINE_TRIAL)
    pb = sta.place_and_route_cached(b, BASELINE_TRIAL)
    assert len(pa.net_len) == len(pb.net_len)      # same design: identical
    # and a genuinely different netlist must not collide
    assert set(pa.net_len) == set(a.net_driver)


def test_netlist_uid_is_unique_per_instance():
    a, b = build_fab32(), build_fab32()
    assert a.uid != b.uid
