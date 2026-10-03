"""
Test suite for FabAware-Opt.

Run with:  pytest -q        (or:  python -m pytest -q)
"""

from __future__ import annotations

import numpy as np
import pytest

from fabaware import compact, optimizer, sta
from fabaware.design import build_fab32
from fabaware.library import LIBRARY, RESIZABLE_TYPES, cin_of, area_of, leakage_of
from fabaware.pd import Trial, place_and_route


# ---------------------------------------------------------------------------
# design / netlist
# ---------------------------------------------------------------------------

def test_netlist_is_acyclic_and_connected():
    nl = build_fab32()
    order = nl.order()
    assert len(order) == len(nl.instances)
    # every combinational input must be driven
    for inst in nl.instances:
        for n in inst.in_nets:
            assert n in nl.net_driver, f"undriven net {n}"
    # topological order really is topological
    pos = {i: k for k, i in enumerate(order)}
    for inst in nl.instances:
        if inst.is_dff:
            continue
        for n in inst.in_nets:
            d = nl.net_driver[n]
            if d >= 0:
                assert pos[d] < pos[inst.idx]


def test_netlist_stats():
    st = build_fab32().stats()
    assert st["gates"] > 400
    assert st["dffs"] == 36
    assert st["transistors"] > 2000
    assert st["by_type"]["NAND2"] > 100


def test_netlist_is_deterministic():
    a = build_fab32().stats()
    b = build_fab32().stats()
    assert a == b


# ---------------------------------------------------------------------------
# compact model
# ---------------------------------------------------------------------------

def test_mobility_decreases_with_temperature():
    assert compact.mobility_scale(400.0) < compact.mobility_scale(300.0)
    assert compact.mobility_scale(300.0) == pytest.approx(1.0)


def test_vth_drifts_negative_with_temperature():
    assert compact.vth_drift(400.0) < 0.0
    assert compact.vth_drift(300.0) == pytest.approx(0.0)


def test_leakage_rises_with_lower_vth_and_higher_temperature():
    base = compact.leakage_factor(0.0, 300.0)
    assert compact.leakage_factor(-0.05, 300.0) > base     # lower Vth → leaky
    assert compact.leakage_factor(0.0, 373.0) > base       # hotter → leaky
    assert base == pytest.approx(1.0)


def test_drive_scales_with_width_and_supply():
    W = np.array([48.0, 96.0])
    L = np.array([22.0, 22.0])
    vth = np.array([0.3, 0.3])
    s = compact.drive_factor(W, L, vth, 0.8, 300.0, np.array([False, False]))
    assert s[1] / s[0] == pytest.approx(2.0, rel=1e-6)     # 2x width → 2x drive
    s_low = compact.drive_factor(W[:1], L[:1], vth[:1], 0.6, 300.0,
                                 np.array([False]))
    assert s_low[0] < s[0]                                  # lower Vdd → slower


def test_pmos_is_weaker_than_nmos():
    W = np.array([48.0, 48.0])
    L = np.array([22.0, 22.0])
    vth = np.array([0.3, 0.3])
    s = compact.drive_factor(W, L, vth, 0.8, 300.0, np.array([False, True]))
    assert s[1] < s[0]


def test_on_current_monotonic_in_vgs():
    i1 = compact.on_current(48.0, 0.5, 0.5, 0.3, 300.0)
    i2 = compact.on_current(48.0, 0.8, 0.8, 0.3, 300.0)
    assert i2 > i1 > 0.0


# ---------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------

def test_library_scaling_functions():
    inv = LIBRARY["INV"]
    assert cin_of(inv, 4.0) == pytest.approx(4 * inv.cin)
    assert area_of(inv, 4.0) > area_of(inv, 1.0)
    assert leakage_of(inv, 4.0) > leakage_of(inv, 1.0)
    assert area_of(inv, 1.0, 1.4) > area_of(inv, 1.0, 1.0)


# ---------------------------------------------------------------------------
# physical design
# ---------------------------------------------------------------------------

def test_placement_stays_inside_the_die():
    nl = build_fab32()
    t = Trial(drives={}, ratio=1.0, nbuf=0, layer_short=5, layer_mid=5,
              layer_long=5, density=0.8)
    p = place_and_route(nl, t)
    for i, (x, y) in p.pos.items():
        assert 0.0 <= x <= p.die_w + 1e-6, f"instance {i} outside die in x"
        assert 0.0 <= y <= p.die_h + 1e-6, f"instance {i} outside die in y"


def test_higher_density_gives_smaller_die():
    nl = build_fab32()
    lo = place_and_route(nl, Trial(drives={}, density=0.60))
    hi = place_and_route(nl, Trial(drives={}, density=0.90))
    assert hi.die_area < lo.die_area


def test_bigger_drives_give_bigger_area():
    nl = build_fab32()
    small = place_and_route(nl, Trial(drives={c: 1.0 for c in LIBRARY}))
    big = place_and_route(nl, Trial(drives={c: 4.0 for c in LIBRARY}))
    assert big.cell_area > small.cell_area


def test_drc_counts_are_non_negative():
    nl = build_fab32()
    p = place_and_route(nl, Trial(drives={}, density=0.95))
    assert p.drc >= 0
    for k, v in p.drc_detail.items():
        assert v >= 0, k


def test_promoting_long_nets_to_upper_metal_helps_the_critical_path():
    """Upper metal has lower R but higher C/µm, so it pays off on long nets.

    This is the real physical trade-off: the RC (Elmore) term always improves
    on the upper layer, but the extra capacitance slows the driving gate, so
    short nets are better off on M5.  Promoting *only the long net class*
    must therefore improve the critical path.
    """
    nl = build_fab32()
    m5 = Trial(drives={}, layer_short=5, layer_mid=5, layer_long=5)
    m7 = Trial(drives={}, layer_short=5, layer_mid=5, layer_long=7)
    r5 = sta.evaluate(nl, m5, K=64, seed=1, do_vmin=False)
    r7 = sta.evaluate(nl, m7, K=64, seed=1, do_vmin=False)
    assert r7.worst_slack_nom > r5.worst_slack_nom


def test_metal_layer_tradeoff_has_a_crossover():
    """M7 beats M5 on the distributed RC term, but costs more load capacitance.

    So blanket-promoting *every* net to M7 is not free - which is why layer
    assignment is a genuine optimization variable rather than a fixed rule.
    """
    from fabaware.pd import LAYER_DATA
    for L in (20.0, 100.0):
        elmore = {l: 0.5 * LAYER_DATA[l]["r"] * (L * LAYER_DATA[l]["detour"]) ** 2
                  * LAYER_DATA[l]["c"] for l in (5, 6, 7)}
        cap = {l: 0.5 * LAYER_DATA[l]["c"] * L * LAYER_DATA[l]["detour"]
               for l in (5, 6, 7)}
        assert elmore[7] < elmore[6] < elmore[5]     # R wins on the RC term
        assert cap[7] > cap[6] > cap[5]              # but C is worse


# ---------------------------------------------------------------------------
# statistical timing
# ---------------------------------------------------------------------------

def test_evaluation_is_reproducible():
    nl = build_fab32()
    t = optimizer.BASELINE_TRIAL
    a = sta.evaluate(nl, t, K=64, seed=11)
    b = sta.evaluate(nl, t, K=64, seed=11)
    assert a.yield_nom == pytest.approx(b.yield_nom)
    assert a.worst_slack_nom == pytest.approx(b.worst_slack_nom)
    assert np.allclose(a.slack_samples, b.slack_samples)


def test_nominal_and_montecarlo_agree_at_zero_variation():
    """With variability switched off, MC must reproduce the nominal delay."""
    nl = build_fab32()
    t = optimizer.BASELINE_TRIAL
    saved = (sta.SIG_GW, sta.SIG_GL, sta.SIG_GVT, sta.SIG_LW, sta.SIG_LL,
             sta.SIG_LVT, sta.SIG_WIRE)
    try:
        sta.SIG_GW = sta.SIG_GL = sta.SIG_GVT = 0.0
        sta.SIG_LW = sta.SIG_LL = sta.SIG_LVT = sta.SIG_WIRE = 0.0
        r = sta.evaluate(nl, t, K=16, seed=3, do_vmin=False)
        # with zero variability every chip reproduces the nominal analysis
        assert r.mean_worst_slack == pytest.approx(r.worst_slack_nom, abs=1e-6)
        assert r.std_worst_slack == pytest.approx(0.0, abs=1e-6)
    finally:
        (sta.SIG_GW, sta.SIG_GL, sta.SIG_GVT, sta.SIG_LW, sta.SIG_LL,
         sta.SIG_LVT, sta.SIG_WIRE) = saved


def test_evaluation_survives_every_corner_of_the_search_space():
    """Fuzz the whole encoded space - evaluate() must never raise.

    This is the integration contract between the three team work packages:
    any Trial the optimizer can produce must be evaluable.
    """
    rng = np.random.default_rng(0)
    trials = []
    for d in (1.0, 2.0, 4.0):
        trials.append(Trial(drives={c: d for c in RESIZABLE_TYPES}, ratio=1.0,
                            nbuf=0, layer_short=5, layer_mid=5, layer_long=5,
                            density=0.84))
    for ratio in (0.80, 1.40):
        for dens in (0.55, 0.85):
            for lay in ((5, 5, 5), (7, 7, 7), (5, 6, 7), (7, 5, 5)):
                for nb in (0, 4):
                    trials.append(Trial(
                        drives={c: 1.0 for c in RESIZABLE_TYPES}, ratio=ratio,
                        nbuf=nb, layer_short=lay[0], layer_mid=lay[1],
                        layer_long=lay[2], density=dens))
    trials += [optimizer.decode(rng.random(optimizer.NDIM)) for _ in range(40)]

    nl = build_fab32()
    endpoints = len(nl.dff_d) + len(nl.primary_outputs)
    for t in trials:
        r = sta.evaluate(nl, t, K=32, seed=1)
        assert 0.0 <= r.yield_nom <= 1.0
        assert r.cell_area > 0.0 and r.p_total > 0.0
        assert r.drc >= 0
        assert len(r.paths) == endpoints
        assert r.slack_samples.shape == (32,)


def test_degenerate_vmin_is_reported_as_nan_not_a_crash():
    """If no chip meets timing anywhere in the Vdd scan, Vmin must be NaN.

    Guards a past RuntimeWarning from nanmean over an all-NaN array.
    """
    nl = build_fab32()
    saved = sta.T_SPEC
    try:
        sta.T_SPEC = 40.0          # impossible target
        r = sta.evaluate(nl, optimizer.BASELINE_TRIAL, K=32, seed=1)
        assert r.yield_nom == 0.0
        assert np.isnan(r.vmin_mean) and np.isnan(r.vmin_min)
        assert r.vmin_fail_frac == pytest.approx(1.0)
    finally:
        sta.T_SPEC = saved


def test_frequency_helpers_are_consistent_with_the_period():
    """211 ps must be ~4.7 GHz - guards a past ps/Hz unit slip."""
    assert sta.freq_ghz() == pytest.approx(1e3 / sta.T_SPEC)
    assert 1.0 < sta.freq_ghz() < 20.0          # sane GHz for a 28 nm block
    assert sta.freq_mhz() == pytest.approx(sta.freq_ghz() * 1000.0)
    # the dynamic-power model must use the same frequency
    assert sta.F_TARGET == pytest.approx(1.0 / (sta.T_SPEC * 1e-12))
    assert sta.F_TARGET == pytest.approx(sta.freq_ghz() * 1e9)


def test_yield_is_a_valid_fraction():
    nl = build_fab32()
    r = sta.evaluate(nl, optimizer.BASELINE_TRIAL, K=64, seed=5)
    assert 0.0 <= r.yield_nom <= 1.0


def test_more_variation_lowers_yield():
    nl = build_fab32()
    saved = sta.SIG_LVT
    try:
        sta.SIG_LVT = 0.002
        r_low = sta.evaluate(nl, optimizer.BASELINE_TRIAL, K=200, seed=5,
                             do_vmin=False)
        sta.SIG_LVT = 0.010
        r_high = sta.evaluate(nl, optimizer.BASELINE_TRIAL, K=200, seed=5,
                              do_vmin=False)
        assert r_high.std_worst_slack > r_low.std_worst_slack
    finally:
        sta.SIG_LVT = saved


def test_upsizing_improves_timing_but_costs_area_and_power():
    nl = build_fab32()
    base = sta.evaluate(nl, optimizer.BASELINE_TRIAL, K=64, seed=5)
    up = Trial(drives={c: 4.0 for c in LIBRARY if not LIBRARY[c].flop},
               ratio=1.0, nbuf=0, layer_short=5, layer_mid=5, layer_long=5,
               density=0.84)
    r = sta.evaluate(nl, up, K=64, seed=5)
    assert r.mean_path_delay < base.mean_path_delay
    assert r.cell_area > base.cell_area
    assert r.p_total > base.p_total


def test_vmin_scan_produces_sane_values():
    nl = build_fab32()
    r = sta.evaluate(nl, optimizer.BASELINE_TRIAL, K=48, seed=5)
    assert 0.5 <= r.vmin_mean <= 1.0
    assert r.vmin_min >= 0.5


def test_corners_are_ordered_slow_to_fast():
    nl = build_fab32()
    c = sta.evaluate_corners(nl, optimizer.BASELINE_TRIAL)
    assert set(c) == {"TT 0.80V 25C", "FF 0.85V 25C", "SS 0.75V 25C",
                      "TT 0.80V 125C", "TT 0.80V -40C"}
    assert c["FF 0.85V 25C"] > c["TT 0.80V 25C"] > c["SS 0.75V 25C"]
    assert c["TT 0.80V 125C"] < c["TT 0.80V 25C"]   # hot is slower
    assert c["TT 0.80V -40C"] > c["TT 0.80V 25C"]   # cold is faster


def test_path_extraction_reports_every_endpoint():
    nl = build_fab32()
    r = sta.evaluate(nl, optimizer.BASELINE_TRIAL, K=32, seed=5, do_vmin=False)
    assert len(r.paths) == len(nl.dff_d) + len(nl.primary_outputs)
    assert all(isinstance(s, float) for _, _, s in r.paths)


# ---------------------------------------------------------------------------
# optimizer
# ---------------------------------------------------------------------------

def test_encode_decode_roundtrip():
    t = Trial(drives={"NAND2": 2.0, "MUX2": 4.0, "XOR2": 1.0}, ratio=1.20,
              nbuf=2, layer_short=5, layer_mid=6, layer_long=7, density=0.70)
    x = optimizer.encode(t)
    assert x.shape == (optimizer.NDIM,)
    assert np.all((x >= 0) & (x <= 1))
    back = optimizer.decode(x)
    assert back.layer_short == 5 and back.layer_mid == 6 and back.layer_long == 7
    assert back.nbuf == 2


def test_decode_is_clipped_and_valid():
    x = np.array([-5.0] * optimizer.NDIM)
    t = optimizer.decode(x)
    assert all(v in (1.0, 2.0, 4.0) for v in t.drives.values())
    assert 0.80 <= t.ratio <= 1.40
    assert 0 <= t.nbuf <= 4
    assert t.layer_short in (5, 6, 7)
    assert 0.55 <= t.density <= 0.85
    x = np.array([5.0] * optimizer.NDIM)
    t = optimizer.decode(x)
    assert all(v in (1.0, 2.0, 4.0) for v in t.drives.values())
    assert t.nbuf == 4


def test_optimizer_improves_over_baseline():
    nl = build_fab32()
    opt = optimizer.optimize(nl, K=64, seed=42, n_doe=8, n_iter=12,
                             time_budget=60)
    assert opt.score >= opt.history.scores[0] - 1e-9
    assert opt.result.yield_nom >= sta.evaluate(
        nl, optimizer.BASELINE_TRIAL, K=64, seed=42).yield_nom - 1e-9


def test_optimizer_records_every_evaluation():
    nl = build_fab32()
    opt = optimizer.optimize(nl, K=32, seed=1, n_doe=4, n_iter=4,
                             time_budget=30)
    n = opt.n_evals
    assert len(opt.history.scores) == n
    assert len(opt.history.yields) == n
    assert len(opt.history.areas) == n
    assert len(opt.history.powers) == n
    assert len(opt.history.drcs) == n
    assert len(opt.history.tags) == n
    assert 0 <= opt.history.best_idx < n


def test_optimizer_never_returns_worse_than_baseline():
    nl = build_fab32()
    for seed in (1, 2, 3):
        opt = optimizer.optimize(nl, K=32, seed=seed, n_doe=4, n_iter=3,
                                 time_budget=20)
        # the returned config's yield must not be catastrophically worse
        assert opt.result.yield_nom >= 0.0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def test_report_generates_html_and_json(tmp_path):
    from fabaware import report as report_mod
    nl = build_fab32()
    base_trial = optimizer.BASELINE_TRIAL
    base_r = sta.evaluate(nl, base_trial, K=32, seed=42)
    opt = optimizer.optimize(nl, K=32, seed=42, n_doe=4, n_iter=4,
                             time_budget=30)
    out = str(tmp_path / "rep")
    paths = report_mod.build_report(nl, base_trial, base_r, opt, out_dir=out,
                                    K=32, runtime_s=1.0)
    import json
    import os
    assert os.path.exists(paths["html"])
    assert os.path.exists(paths["json"])
    html = open(paths["html"], encoding="utf-8").read()
    assert html.count("data:image/png;base64,") == 9
    assert "FabAware-Opt" in html
    assert "{" not in html.split("<style>")[0]
    data = json.load(open(paths["json"]))
    assert data["baseline"]["yield"] == pytest.approx(base_r.yield_nom)
    assert len(data["search"]["history"]) == opt.n_evals


def test_report_html_has_no_unresolved_placeholders(tmp_path):
    from fabaware import report as report_mod
    nl = build_fab32()
    base_trial = optimizer.BASELINE_TRIAL
    base_r = sta.evaluate(nl, base_trial, K=32, seed=42)
    opt = optimizer.optimize(nl, K=32, seed=42, n_doe=4, n_iter=3,
                             time_budget=25)
    paths = report_mod.build_report(nl, base_trial, base_r, opt,
                                    out_dir=str(tmp_path / "r2"), K=32)
    html = open(paths["html"], encoding="utf-8").read()
    assert "{yield_b}" not in html
    assert "{cards}" not in html
    assert "{metric_rows}" not in html
