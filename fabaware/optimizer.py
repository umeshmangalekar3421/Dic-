"""
AI-assisted optimization: Gaussian-process surrogate + expected improvement.
=============================================================================

Decision variables (13, encoded as x in [0,1]^13):

  x[0..6]   standard-cell drive selection for the seven resizable cell types
            (level 0/1/2 -> drive 1/2/4 - i.e. cell selection from the library)
  x[7]      Wp/Wn transistor sizing ratio  (0.80 .. 1.40)
  x[8]      number of buffers inserted on the longest wires (0 .. 4)
  x[9..11]  metal layer for short / mid / long net classes (M5/M6/M7)
  x[12]     placement density (0.55 .. 0.85)

The AI loop
-----------
1.  a small initial design of experiments (Sobol) + baseline + heuristics
2.  a Gaussian-process surrogate (Matern 2.5) is fitted to (x -> score)
3.  expected-improvement acquisition over a Halton candidate grid selects the
    next configuration to evaluate (true Monte-Carlo statistical timing)
4.  after the search budget, coordinate-ascent refinement polishes the best
    point so the reported configuration is a (local) optimum

Score
-----
    score = timing_yield
            - w * max(0, area/area0 - AREA_BUDGET)
            - w * max(0, power/power0 - PWR_BUDGET)
            - 0.15 * drc/100
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from .design import Netlist
from .library import RESIZABLE_TYPES
from .pd import Trial
from . import sta

# budgets (relative to the baseline configuration)
AREA_BUDGET = 1.30
PWR_BUDGET = 1.50
PEN_W = 2.5
DRC_WEIGHT = 0.15
LAYER_INV_PENALTY = 0.004   # per inverted (shorter class on higher layer) pair

N_DRIVE = len(RESIZABLE_TYPES)          # 7
NDIM = N_DRIVE + 1 + 1 + 3 + 1          # 13


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------

def decode(x: np.ndarray) -> Trial:
    """x in [0,1]^13 -> Trial configuration."""
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    drives = {}
    for i, name in enumerate(RESIZABLE_TYPES):
        level = int(np.clip(round(2.0 * x[i]), 0, 2))
        drives[name] = float((1.0, 2.0, 4.0)[level])
    ratio = 0.80 + 0.60 * x[N_DRIVE]
    nbuf = int(round(4.0 * x[N_DRIVE + 1]))
    lay = lambda j: int(5 + round(2.0 * x[N_DRIVE + 2 + j]))
    density = 0.55 + 0.30 * x[NDIM - 1]
    return Trial(
        drives=drives, ratio=round(ratio, 3), nbuf=nbuf,
        layer_short=lay(0), layer_mid=lay(1), layer_long=lay(2),
        density=round(density, 3),
    )


def encode(trial: Trial) -> np.ndarray:
    """Trial -> x in [0,1]^13."""
    x = np.zeros(NDIM)
    for i, name in enumerate(RESIZABLE_TYPES):
        d = trial.drives.get(name, 1.0)
        x[i] = {1.0: 0.0, 2.0: 0.5, 4.0: 1.0}.get(d, 0.0)
    x[N_DRIVE] = (trial.ratio - 0.80) / 0.60
    x[N_DRIVE + 1] = trial.nbuf / 4.0
    for j, l in enumerate((trial.layer_short, trial.layer_mid, trial.layer_long)):
        x[N_DRIVE + 2 + j] = (l - 5) / 2.0
    x[NDIM - 1] = (trial.density - 0.55) / 0.30
    return np.clip(x, 0.0, 1.0)


BASELINE_TRIAL = Trial(
    drives={c: 1.0 for c in RESIZABLE_TYPES},
    ratio=1.0, nbuf=0,
    layer_short=5, layer_mid=5, layer_long=5,
    density=0.84,
)

#: heuristic seeds (in x-space) that give the surrogate strong starting points
HEURISTICS: Dict[str, np.ndarray] = {
    "upsized": np.array([1.0, 0.0, 0.5, 1.0, 0.0, 0.0, 0.0,   # drives nand4 aoi1 xor2 mux4 a21:1 n3:1 buf:1
                         0.25, 0.5,                              # ratio 1.15, nbuf 2
                         0.0, 0.5, 1.0,                          # M5, M6, M7
                         0.5]),                                  # density 0.70
    "lean":    np.array([0.5, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0,
                         0.83, 0.25,
                         0.0, 0.5, 1.0,
                         0.43]),
    "metal":   np.array([0.5, 0.5, 0.5, 0.5, 0.0, 0.0, 0.0,
                         0.33, 0.75,
                         1.0, 1.0, 1.0,
                         0.33]),
}


# ---------------------------------------------------------------------------
@dataclass
class OptHistory:
    xs: List[np.ndarray] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    yields: List[float] = field(default_factory=list)
    areas: List[float] = field(default_factory=list)
    powers: List[float] = field(default_factory=list)
    drcs: List[int] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    best_idx: int = 0


@dataclass
class OptResult:
    trial: Trial
    result: "sta.EvalResult"
    score: float
    history: OptHistory
    n_evals: int


# ---------------------------------------------------------------------------
def make_score(base_area: float, base_power: float) -> Callable[[sta.EvalResult], float]:
    def score(r: sta.EvalResult) -> float:
        s = r.yield_nom
        s -= PEN_W * max(0.0, r.cell_area / base_area - AREA_BUDGET)
        s -= PEN_W * max(0.0, r.p_total / base_power - PWR_BUDGET)
        s -= DRC_WEIGHT * (r.drc / 100.0)
        # discourage counter-intuitive layer inversions (short nets on
        # higher layers than longer nets)
        t = r.trial
        inv = 0
        if t.layer_short > t.layer_mid:
            inv += 1
        if t.layer_mid > t.layer_long:
            inv += 1
        if t.layer_short > t.layer_long:
            inv += 1
        s -= LAYER_INV_PENALTY * inv
        return float(s)
    return score


def _sobol_points(n: int, dim: int, seed: int) -> np.ndarray:
    from scipy.stats import qmc
    s = qmc.Sobol(d=dim, scramble=True, seed=seed)
    return s.random(n)


def _halton_candidates(n: int, dim: int, seed: int) -> np.ndarray:
    from scipy.stats import qmc
    s = qmc.Halton(d=dim, scramble=True, seed=seed)
    return s.random(n)


def _ei(mu, sd, best, xi=0.005):
    z = (mu - best - xi) / np.maximum(sd, 1e-9)
    from scipy.stats import norm
    return (mu - best - xi) * norm.cdf(z) + sd * norm.pdf(z)


def optimize(
    nl: Netlist,
    K: int = 160,
    seed: int = 42,
    n_doe: int = 8,
    n_iter: int = 20,
    time_budget: float = 180.0,
    progress: Optional[Callable[[str], None]] = None,
) -> OptResult:
    """Run the AI search. ``progress`` is a callback for console updates."""
    import time
    t_start = time.time()

    def say(msg: str) -> None:
        if progress:
            progress(msg)

    history = OptHistory()

    # ---------------- 1. initial design of experiments ---------------------
    say("[AI] 1) initial design of experiments ...")
    base_x = encode(BASELINE_TRIAL)
    doe = _sobol_points(n_doe, NDIM, seed)
    candidates = [base_x] + [row for row in doe] + [HEURISTICS[k] for k in HEURISTICS]
    seen = {tuple(np.round(v, 4)) for v in [base_x]}
    picked = []
    for v in candidates:
        key = tuple(np.round(v, 4))
        if key in seen:
            continue
        seen.add(key)
        picked.append(v)

    # evaluate the baseline FIRST so the score budgets are anchored to it
    trial0 = decode(base_x)
    res0 = sta.evaluate(nl, trial0, K=K, seed=seed)
    score_fn = make_score(res0.cell_area, res0.p_total)

    def record(x: np.ndarray, res: sta.EvalResult, tag: str) -> None:
        s = score_fn(res)
        history.xs.append(np.array(x, dtype=float))
        history.scores.append(s)
        history.yields.append(res.yield_nom)
        history.areas.append(res.cell_area)
        history.powers.append(res.p_total)
        history.drcs.append(res.drc)
        history.tags.append(tag)
        history.best_idx = int(np.argmax(history.scores))
        say("  %-14s yield %6.1f%%  score %7.3f  area %7.1f um2  pwr %7.3f mW  drc %3d"
            % (tag, 100 * res.yield_nom, s, res.cell_area, res.p_total, res.drc))

    record(base_x, res0, "baseline")

    for v in picked[1:]:
        trial = decode(v)
        res = sta.evaluate(nl, trial, K=K, seed=seed)
        record(v, res, "doe")
        if time.time() - t_start > time_budget * 0.35:
            break

    # ---------------- 2. GP + expected improvement loop ---------------------
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern

    X = np.array(history.xs)
    y = np.array(history.scores)
    best_x = X[history.best_idx]
    best_score = float(y[history.best_idx])

    say("[AI] 2) gaussian-process surrogate + expected-improvement search ...")
    kernel = ConstantKernel(1.0) * Matern(length_scale=0.35, nu=2.5)
    n_cand = 600
    for it in range(n_iter):
        if best_score >= 0.999:
            say("  target reached (score >= 0.999) after %d iterations" % it)
            break
        gp = GaussianProcessRegressor(kernel=kernel, alpha=1e-10,
                                      normalize_y=True, n_restarts_optimizer=0)
        try:
            gp.fit(X, y)
        except Exception:
            gp = None
        cand = _halton_candidates(n_cand, NDIM, seed + it + 7)
        # keep candidates reasonably spread from training points
        if gp is not None:
            mu, sd = gp.predict(cand, return_std=True)
            acq = _ei(mu, sd, best_score)
        else:  # degenerate fallback: random search
            acq = np.random.default_rng(seed + it).random(n_cand)
        x_next = cand[int(np.argmax(acq))]
        trial = decode(x_next)
        res = sta.evaluate(nl, trial, K=K, seed=seed)
        record(x_next, res, "gp%d" % (it + 1))
        X = np.vstack([X, x_next])
        y = np.append(y, history.scores[-1])
        if history.scores[-1] > best_score:
            best_score = float(history.scores[-1])
            best_x = x_next
        if time.time() - t_start > time_budget * 0.8:
            say("  time budget reached")
            break

    # ---------------- 3. local refinement -----------------------------------
    say("[AI] 3) local refinement around the best point ...")
    cur = best_x
    cur_score = best_score
    rng = np.random.default_rng(seed + 999)
    steps = 0
    max_steps = 12
    while steps < max_steps and time.time() - t_start < time_budget:
        d = int(rng.integers(0, NDIM))
        delta = float(rng.choice((0.33, -0.33, 0.66, -0.66)))
        x_try = cur.copy()
        x_try[d] = np.clip(x_try[d] + delta, 0.0, 1.0)
        if np.allclose(x_try, cur):
            continue
        if any(np.allclose(x_try, h, atol=1e-6) for h in history.xs):
            continue
        trial = decode(x_try)
        res = sta.evaluate(nl, trial, K=K, seed=seed)
        record(x_try, res, "refine")
        steps += 1
        s = score_fn(res)
        if s > cur_score:
            cur, cur_score = x_try, s
    history.best_idx = int(np.argmax(history.scores))
    best_x = history.xs[history.best_idx]
    best_score = float(history.scores[history.best_idx])

    # final authoritative evaluation of the best configuration
    best_trial = decode(best_x)
    best_res = sta.evaluate(nl, best_trial, K=K, seed=seed)
    best_score = score_fn(best_res)
    if best_score < history.scores[0]:      # never report worse than baseline
        best_trial, best_res = trial0, res0
        best_score = history.scores[0]

    return OptResult(
        trial=best_trial,
        result=best_res,
        score=float(best_score),
        history=history,
        n_evals=len(history.xs),
    )
