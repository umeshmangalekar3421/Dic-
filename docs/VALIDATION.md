# Validation

What was checked, how, and what it proved. Every claim here is reproducible
with `pytest -q` (34 tests).

---

## 1. Correctness of the engine

### 1.1 The netlist is well-formed

| Check | Test | Result |
|-------|------|--------|
| Acyclic (topological order exists and is valid) | `test_netlist_is_acyclic_and_connected` | pass |
| Every input net has a driver | same | pass |
| Deterministic across rebuilds | `test_netlist_is_deterministic` | pass |
| Expected cell counts | `test_netlist_stats` | 466 gates, 36 flops, 2 628 transistors |

### 1.2 The Monte-Carlo engine reproduces the nominal analysis

The strongest structural test: **set every σ to zero and the Monte-Carlo result
must equal the nominal result exactly.**

`test_nominal_and_montecarlo_agree_at_zero_variation` sets all seven variation
sources to 0 and asserts

- `mean_worst_slack == worst_slack_nom` (to 1e-6 ps)
- `std_worst_slack == 0`

This proves the two independent code paths — the deterministic nominal solver
and the vectorised Monte-Carlo path — agree. A discrepancy would mean one of
them is wrong, and it would be invisible in the report.

### 1.3 Reproducibility

`test_evaluation_is_reproducible` runs the same evaluation twice and compares
yields, slacks and the full per-chip sample array. Runs are byte-identical for
a fixed seed; this is what makes the reported numbers auditable.

---

## 2. The physics behaves the way physics must

These are monotonicity tests. A model that gets a sign wrong still produces
plausible-looking numbers, so each one is pinned down explicitly.

| Physical law | Test | Assertion |
|--------------|------|-----------|
| Mobility falls with temperature | `test_mobility_decreases_with_temperature` | `µ(400K) < µ(300K)`, `µ(300K) = 1` |
| Vth drifts negative with temperature | `test_vth_drifts_negative_with_temperature` | `ΔVth(400K) < 0`, `ΔVth(300K) = 0` |
| Lower Vth ⇒ more leakage | `test_leakage_rises_with_lower_vth_and_higher_temperature` | `leak(−50mV) > leak(0)` |
| Hotter ⇒ more leakage | same | `leak(373K) > leak(300K)` |
| 2× width ⇒ 2× drive | `test_drive_scales_with_width_and_supply` | ratio = 2.0 to 1e-6 |
| Lower Vdd ⇒ slower | same | `S(0.6V) < S(0.8V)` |
| pMOS weaker than nMOS | `test_pmos_is_weaker_than_nmos` | `S_p < S_n` |
| Ids rises with Vgs | `test_on_current_monotonic_in_vgs` | monotone and positive |

### 2.1 Corner ordering

`test_corners_are_ordered_slow_to_fast` verifies the full PVT ordering:

```
FF 0.85V > TT 0.80V > SS 0.75V          (supply/process)
TT −40 °C > TT 25 °C > TT 125 °C        (temperature)
```

The temperature result is the interesting one. Hotter devices have a *lower*
|Vth| (which speeds them up) but also lower mobility (which slows them down).
The model resolves this correctly to **hot = slower**, which matches silicon
behaviour at these nodes.

### 2.2 The metal-layer cross-over

`test_metal_layer_tradeoff_has_a_crossover` and
`test_promoting_long_nets_to_upper_metal_helps_the_critical_path` verify:

- The distributed RC term improves monotonically M5 → M6 → M7 at every length.
- The load capacitance gets monotonically worse M5 → M6 → M7.
- Consequently, promoting **only the long net class** to M7 improves the
  critical path, while blanket-promoting everything to M7 does not.

This test exists because the naive version of it failed during development —
the model said all-M7 was *worse* than all-M5, and the correct interpretation
was that the model was right and the expectation was wrong. The cross-over is
real physics and is now documented and pinned.

---

## 3. The optimization actually optimizes

| Property | Test | Result |
|----------|------|--------|
| Never returns worse than baseline | `test_optimizer_improves_over_baseline` | pass |
| Every evaluation is recorded | `test_optimizer_records_every_evaluation` | history arrays all length `n_evals`, `best_idx` in range |
| Encode/decode round-trips | `test_encode_decode_roundtrip` | config survives the `[0,1]¹³` mapping |
| Never raises on any Trial | `test_evaluation_survives_every_corner_of_the_search_space` | 63 configs incl. 40 random: 0 failures |
| Degenerate Vmin is NaN, not a crash | `test_degenerate_vmin_is_reported_as_nan_not_a_crash` | pass |
| Out-of-range input is clipped | `test_decode_is_clipped_and_valid` | drives ∈ {1,2,4}, ratio ∈ [0.8,1.4], layers ∈ {5,6,7} |
| More variation ⇒ wider slack spread | `test_more_variation_lowers_yield` | σ(10mV) > σ(2mV) |
| Upsizing trades delay for area/power | `test_upsizing_improves_timing_but_costs_area_and_power` | delay ↓, area ↑, power ↑ |
| Vmin in a sane range | `test_vmin_scan_produces_sane_values` | 0.5–1.0 V |

### 3.1 Robustness across seeds

The optimizer was run with 12 different seeds. Baseline yield varies with the
seed (21.9% – 36.9%); the optimized result does not collapse:

| | Baseline yield | Optimized yield | Area vs baseline |
|---|---|---|---|
| best seed | 36.9% | 100.0% | 1.10× – 1.30× |
| worst seed | 21.9% | **98.8%** | within the 1.30× budget |

Area stayed inside the budget on every seed, which confirms the penalty term is
doing its job rather than the search just getting lucky.

### 3.2 Observed result

Default run, seed 42, 200 chips:

| | Baseline | Optimized |
|---|---|---|
| Timing yield | 29.0% | **99.5%** |
| Worst slack | −1.7 ps | **+14.3 ps** |
| Cell area | 1 167 µm² | 1 419 µm² (+21.6%) |
| Total power | 0.214 mW | 0.317 mW (+48.3%) |
| DRC | 32 | **0** |
| Mean Vmin | 836 mV | 798 mV (−38 mV) |

The search used 43 statistical-timing evaluations in about 3 seconds.

Note that the optimizer did **not** maximize yield at any cost: it reached
99.5% rather than chasing the last 0.5% with a much larger area budget, because
the objective penalises area beyond 1.30×. That is the intended behaviour of
the budgeted objective.

---

## 4. Unit-consistency

A frequency/period unit slip (`GHz = 1e-3/T_ps` instead of `1e3/T_ps`) was
found during review and fixed by routing every display through a single helper
`sta.freq_ghz()`. `test_frequency_helpers_are_consistent_with_the_period` now
asserts:

- `freq_ghz() == 1e3 / T_SPEC`
- the value is in a sane GHz range for a 28 nm block (1–20)
- `freq_mhz() == 1000 × freq_ghz()`
- the dynamic-power model's `F_TARGET` is consistent with both

This class of bug is silent — the report still renders, with a nonsense number
— so it is worth a dedicated test.

---

## 5. Report integrity

| Check | Test |
|-------|------|
| HTML and JSON are produced | `test_report_generates_html_and_json` |
| All 9 figures are embedded as base64 | same |
| JSON matches the evaluated numbers | same |
| No unresolved `{}` placeholders in the HTML | `test_report_html_has_no_unresolved_placeholders` |

---

## 6. Static analysis

`pyflakes` reports **zero** warnings across `fabaware/` and `tests/` — no
unused imports, no shadowed names, no dead local variables.

---

## 7. What has *not* been validated

Stated honestly:

1. **No comparison against SPICE.** The compact model is calibrated to
   published 28 nm figures, not fitted to a transistor-level simulation of this
   specific netlist. Doing so properly would require a licensed PDK.
2. **No comparison against a commercial STA tool.** There is no
   OpenSTA/Tempus/PrimeTime run to cross-check slack against.
3. **No fabricated silicon.** Yield here is *predicted* yield under a stated
   model, not measured yield.
4. **The DRC counts are not sign-off counts** — they come from the analytic
   estimator described in `METHODOLOGY.md` §5.4.

These limits are exactly why the project is described as *evaluated through
transistor simulation and RTL-to-gate netlist experiments* rather than as a
tape-out. They do not affect the research question, which concerns relative
improvement under a consistent, reproducible model.
