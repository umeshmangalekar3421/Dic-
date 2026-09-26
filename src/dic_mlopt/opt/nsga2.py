"""Compact NSGA-II (Deb et al., IEEE TEC 2002) for real-valued sizing.

Objectives are all minimized.  Constraint handling uses the constrained
domination rule (feasible beats infeasible; two infeasibles compare by
violation magnitude).
"""

from __future__ import annotations

from typing import Callable, List, Tuple

import numpy as np


def _fast_nds(ranks_needed: np.ndarray) -> List[List[int]]:
    """Non-dominated sort. ranks_needed is (n, m) F with nan = infeasible already penalized."""
    n = ranks_needed.shape[0]
    S = [[] for _ in range(n)]
    n_dom = np.zeros(n, dtype=int)
    fronts: List[List[int]] = [[]]
    for p in range(n):
        fp = ranks_needed[p]
        for q in range(p + 1, n):
            fq = ranks_needed[q]
            # p dominates q?
            pdq = np.all(fp <= fq) and np.any(fp < fq)
            qdp = np.all(fq <= fp) and np.any(fq < fp)
            if pdq:
                S[p].append(q)
                n_dom[q] += 1
            elif qdp:
                S[q].append(p)
                n_dom[p] += 1
        if n_dom[p] == 0:
            fronts[0].append(p)
    i = 0
    while fronts[i]:
        nxt = []
        for p in fronts[i]:
            for q in S[p]:
                n_dom[q] -= 1
                if n_dom[q] == 0:
                    nxt.append(q)
        i += 1
        fronts.append(nxt)
    return fronts[:-1]


def _crowding(F: np.ndarray, idxs: List[int]) -> np.ndarray:
    m = F.shape[1]
    crowd = np.zeros(len(idxs))
    if len(idxs) <= 2:
        crowd[:] = np.inf
        return crowd
    Fi = F[idxs]
    for k in range(m):
        order = np.argsort(Fi[:, k])
        crowd[order[0]] = np.inf
        crowd[order[-1]] = np.inf
        span = Fi[order[-1], k] - Fi[order[0], k]
        if span <= 1e-18:
            continue
        for j in range(1, len(idxs) - 1):
            crowd[order[j]] += (Fi[order[j + 1], k] - Fi[order[j - 1], k]) / span
    return crowd


def _sbx(p1, p2, low, high, eta=15.0, rng=None):
    rng = rng or np.random.default_rng()
    u = rng.random(p1.shape)
    beta = np.where(
        u <= 0.5,
        (2.0 * u) ** (1.0 / (eta + 1.0)),
        (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (eta + 1.0)),
    )
    c1 = 0.5 * ((p1 + p2) - beta * (p2 - p1))
    c2 = 0.5 * ((p1 + p2) + beta * (p2 - p1))
    return np.clip(c1, low, high), np.clip(c2, low, high)


def _poly_mut(x, low, high, eta=20.0, pm=None, rng=None):
    rng = rng or np.random.default_rng()
    pm = 1.0 / x.size if pm is None else pm
    y = x.copy()
    for i in range(x.size):
        if rng.random() > pm:
            continue
        span = high[i] - low[i]
        if span <= 0:
            continue
        delta1 = (y[i] - low[i]) / span
        delta2 = (high[i] - y[i]) / span
        u = rng.random()
        if u < 0.5:
            xy = 1.0 - delta1
            val = 2.0 * u + (1.0 - 2.0 * u) * (xy ** (eta + 1.0))
            delta_q = val ** (1.0 / (eta + 1.0)) - 1.0
        else:
            xy = 1.0 - delta2
            val = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * (xy ** (eta + 1.0))
            delta_q = 1.0 - val ** (1.0 / (eta + 1.0))
        y[i] = np.clip(y[i] + delta_q * span, low[i], high[i])
    return y


def nsga2(
    n_var: int,
    n_obj: int,
    low: np.ndarray,
    high: np.ndarray,
    evaluate: Callable[[np.ndarray], Tuple[np.ndarray, float]],
    pop: int = 40,
    n_gen: int = 25,
    seed: int = 42,
) -> dict:
    """evaluate(x) -> (objs[n_obj], constraint_violation>=0)."""
    rng = np.random.default_rng(seed)
    low = np.asarray(low, dtype=float)
    high = np.asarray(high, dtype=float)
    X = rng.uniform(low, high, size=(pop, n_var))

    def eval_pop(Xmat):
        F = np.zeros((len(Xmat), n_obj))
        V = np.zeros(len(Xmat))
        for i, x in enumerate(Xmat):
            f, v = evaluate(x)
            F[i] = f
            V[i] = v
        # constrained domination: add large penalty so infeasible never dominate feasible
        Fpen = F.copy()
        inf = V > 1e-12
        if np.any(inf):
            Fpen[inf] = Fpen[inf] + 1e3 + 100.0 * V[inf][:, None]
        return F, V, Fpen

    F, V, Fpen = eval_pop(X)
    history = []
    for gen in range(n_gen):
        # offspring
        childs = []
        perm = rng.permutation(pop)
        for i in range(0, pop, 2):
            a = perm[i]
            b = perm[(i + 1) % pop]
            # binary tournament on (rank via Fpen, then crowding) — use Fpen dominance
            c1, c2 = _sbx(X[a], X[b], low, high, rng=rng)
            c1 = _poly_mut(c1, low, high, rng=rng)
            c2 = _poly_mut(c2, low, high, rng=rng)
            childs.append(c1)
            childs.append(c2)
        Q = np.vstack(childs)[:pop]
        Fq, Vq, Fpenq = eval_pop(Q)
        Xt = np.vstack([X, Q])
        Ft = np.vstack([F, Fq])
        Vt = np.concatenate([V, Vq])
        Fpent = np.vstack([Fpen, Fpenq])
        fronts = _fast_nds(Fpent)
        new_idx: List[int] = []
        for fr in fronts:
            if len(new_idx) + len(fr) <= pop:
                new_idx.extend(fr)
            else:
                crowd = _crowding(Fpent, fr)
                order = np.argsort(-crowd)
                need = pop - len(new_idx)
                new_idx.extend([fr[k] for k in order[:need]])
                break
        X = Xt[new_idx]
        F = Ft[new_idx]
        V = Vt[new_idx]
        Fpen = Fpent[new_idx]
        feas = V <= 1e-12
        history.append({
            "gen": gen,
            "n_feas": int(np.sum(feas)),
            "best_delay": float(np.min(F[feas, 0])) if np.any(feas) else float(np.min(F[:, 0])),
        })

    fronts = _fast_nds(Fpen)
    f0 = fronts[0]
    return {
        "X": X,
        "F": F,
        "V": V,
        "pareto_X": X[f0],
        "pareto_F": F[f0],
        "pareto_V": V[f0],
        "history": history,
    }
