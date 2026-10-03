"""
Charts for the FabAware-Opt report.

All charts are produced from *evaluated simulation data* - no synthetic
numbers are drawn.  They are rendered with matplotlib into PNG files and
embedded into the self-contained HTML report.
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# plot styling
# ---------------------------------------------------------------------------
C_BASE = "#e05252"     # baseline - red (problem)
C_OPT = "#2b8aef"      # optimized - blue (solution)
C_GREY = "#9aa4b2"
C_ACCENT = "#7b5ea7"

PALETTE = {"baseline": C_BASE, "optimized": C_OPT}

plt.rcParams.update({
    "figure.facecolor": "#0e1420",
    "axes.facecolor": "#141c2b",
    "savefig.facecolor": "#0e1420",
    "axes.edgecolor": "#2c3a52",
    "axes.labelcolor": "#d6dbe3",
    "text.color": "#d6dbe3",
    "xtick.color": "#9aa4b2",
    "ytick.color": "#9aa4b2",
    "grid.color": "#222d42",
    "grid.linewidth": 0.7,
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
})


def _nice(ax) -> None:
    ax.grid(True, alpha=0.35, linestyle="--", linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#2c3a52")


def fig_iv(nl=None, path: str = "fig_iv.png") -> str:
    """MOSFET I-V family from the compact model, with variation band."""
    from .compact import VTH0_N, on_current

    vds = np.linspace(0.0, 0.8, 120)
    vgs_list = [0.35, 0.45, 0.55, 0.65, 0.80]
    fig, ax = plt.subplots(figsize=(6.2, 4.0), dpi=140)

    for vgs in vgs_list:
        ids_nom = np.array([on_current(48.0, vgs, v, VTH0_N, 300.0) * 1e6
                            for v in vds])
        ids_slow = np.array([on_current(48.0, vgs, v, VTH0_N + 0.040, 300.0) * 1e6
                             for v in vds])
        ids_fast = np.array([on_current(48.0, vgs, v, VTH0_N - 0.040, 300.0) * 1e6
                             for v in vds])
        ax.plot(vds, ids_nom, lw=1.8, label=f"Vgs={vgs:.2f} V")
        ax.fill_between(vds, ids_slow, ids_fast, alpha=0.18)

    ax.set_xlabel("Vds (V)")
    ax.set_ylabel("Ids (µA)")
    ax.set_title("nMOS I-V family — compact model, ±40 mV Vth spread")
    ax.legend(fontsize=8, ncol=2, frameon=False, loc="upper left")
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_iv_bar(nl=None, path: str = "fig_iv_bars.png") -> str:
    """On-drive vs. supply voltage, showing the velocity-saturation effect."""
    from .compact import VTH0_N, on_current

    vdds = np.array([0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90])
    ids = np.array([on_current(48.0, v, v, VTH0_N, 300.0) * 1e6 for v in vdds])
    fig, ax = plt.subplots(figsize=(6.2, 3.6), dpi=140)
    ax.bar([f"{v:.2f}" for v in vdds], ids, color=C_OPT, alpha=0.9,
           edgecolor="#0e1420", linewidth=0.5)
    for x, y in zip(range(len(vdds)), ids):
        ax.text(x, y * 1.02, f"{y:.0f}", ha="center", va="bottom",
                fontsize=8, color="#9aa4b2")
    ax.set_xlabel("Vdd = Vgs = Vds (V)")
    ax.set_ylabel("Ids (µA)")
    ax.set_title("Drive current vs. supply voltage (velocity saturation)")
    ax.set_ylim(0, max(ids) * 1.18)
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_yield_dist(base_r, opt_r, path: str = "fig_yield.png") -> str:
    """Monte-Carlo worst-slack distributions, baseline vs optimized."""
    fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=140)
    b = base_r.slack_samples
    o = opt_r.slack_samples

    lo = min(b.min(), o.min())
    hi = max(b.max(), o.max())
    bins = np.linspace(lo, hi, 44)

    ax.hist(b, bins=bins, color=C_BASE, alpha=0.72, label="Baseline",
            edgecolor="#0e1420", linewidth=0.4)
    ax.hist(o, bins=bins, color=C_OPT, alpha=0.72, label="AI-optimized",
            edgecolor="#0e1420", linewidth=0.4)

    ax.axvline(0.0, color="#ffd76a", lw=1.6, ls="--", zorder=5)
    ax.text(0.0, ax.get_ylim()[1] * 0.94, " timing spec  ",
            color="#ffd76a", fontsize=8, ha="right", va="top")

    yb = 100 * (b >= 0).mean()
    yo = 100 * (o >= 0).mean()
    ax.set_title(f"Worst-slack distribution — {len(b)} Monte-Carlo chips\n"
                 f"baseline {yb:.1f}% timing yield  →  optimized {yo:.1f}%")
    ax.set_xlabel("Worst-case slack (ps)")
    ax.set_ylabel("Number of chips")
    ax.legend(frameon=False, fontsize=9)
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_metrics_compare(base_r, opt_r, path: str = "fig_metrics.png") -> str:
    """Normalized radar-style comparison of the headline metrics."""
    labels = ["Timing yield", "Worst slack", "Area", "Power", "DRC", "Vmin margin"]
    # each metric normalized so that "better" is always further out (0..1)
    def n_better(v, worse, best):
        if abs(best - worse) < 1e-12:
            return 0.5
        return float(np.clip((v - worse) / (best - worse), 0.0, 1.0))

    yb, yo = base_r.yield_nom, opt_r.yield_nom
    sb, so = base_r.worst_slack_nom, opt_r.worst_slack_nom
    ab, ao = base_r.cell_area, opt_r.cell_area
    pb, po = base_r.p_total, opt_r.p_total
    db, do = base_r.drc, opt_r.drc
    vb, vo = base_r.vmin_mean, opt_r.vmin_mean

    data = [
        (yb, yo, 0.0, 1.0),
        (sb, so, -max(abs(sb), abs(so)) * 1.05, max(sb, so) * 1.05),
        (ab, ao, max(ab, ao) * 1.25, min(ab, ao) * 0.75),
        (pb, po, max(pb, po) * 1.25, min(pb, po) * 0.75),
        (db, do, max(db, do, 1) * 1.2, 0.0),
        (vb, vo, max(vb, vo) * 1.1, min(vb, vo) * 0.85),
    ]
    vals_b = [n_better(v[0], v[2], v[3]) for v in data]
    vals_o = [n_better(v[1], v[2], v[3]) for v in data]

    ang = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    vals_b += vals_b[:1]
    vals_o += vals_o[:1]
    ang += ang[:1]

    fig, ax = plt.subplots(figsize=(6.0, 5.0), dpi=140,
                           subplot_kw=dict(polar=True))
    ax.set_facecolor("#141c2b")
    ax.plot(ang, vals_b, color=C_BASE, lw=2.0, label="Baseline")
    ax.fill(ang, vals_b, color=C_BASE, alpha=0.22)
    ax.plot(ang, vals_o, color=C_OPT, lw=2.0, label="AI-optimized")
    ax.fill(ang, vals_o, color=C_OPT, alpha=0.22)
    ax.set_xticks(ang[:-1])
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["", "", "", ""], fontsize=7)
    ax.set_ylim(0, 1.05)
    ax.grid(color="#2c3a52", linewidth=0.7)
    ax.spines["polar"].set_color("#2c3a52")
    ax.set_title("Headline metrics (outward = better)", pad=18)
    ax.legend(frameon=False, fontsize=9, loc="upper right",
              bbox_to_anchor=(1.18, 1.12))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_vmin(base_r, opt_r, path: str = "fig_vmin.png") -> str:
    """Per-chip Vmin distributions."""
    fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=140)
    b = base_r.vmin_samples[~np.isnan(base_r.vmin_samples)] * 1000
    o = opt_r.vmin_samples[~np.isnan(opt_r.vmin_samples)] * 1000
    if len(b) == 0:
        b = np.array([np.nan])
    if len(o) == 0:
        o = np.array([np.nan])
    lo = float(np.nanmin([b.min(), o.min()]))
    hi = float(np.nanmax([b.max(), o.max()]))
    bins = np.linspace(lo, hi, 36)
    ax.hist(b, bins=bins, color=C_BASE, alpha=0.72, label="Baseline",
            edgecolor="#0e1420", linewidth=0.4)
    ax.hist(o, bins=bins, color=C_OPT, alpha=0.72, label="AI-optimized",
            edgecolor="#0e1420", linewidth=0.4)
    ax.axvline(800, color="#ffd76a", lw=1.5, ls="--")
    ax.text(800, ax.get_ylim()[1] * 0.93, " 800 mV nominal ",
            color="#ffd76a", fontsize=8, ha="left", va="top")
    ax.set_xlabel("Per-chip minimum operating voltage (mV)")
    ax.set_ylabel("Number of chips")
    ax.set_title("Vmin distribution — lower is better (more voltage margin)")
    ax.legend(frameon=False, fontsize=9)
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_learning(history, path: str = "fig_learning.png") -> str:
    """AI search learning curve."""
    fig, ax = plt.subplots(figsize=(6.6, 3.8), dpi=140)
    s = np.array(history.scores)
    best = np.maximum.accumulate(s)
    x = np.arange(1, len(s) + 1)
    ax.plot(x, s, color=C_GREY, lw=1.0, marker="o", ms=3, alpha=0.55,
            label="evaluated configuration")
    ax.plot(x, best, color=C_OPT, lw=2.4, label="best score so far")
    ax.fill_between(x, best, best.min() - 0.05, color=C_OPT, alpha=0.12)

    # mark phase boundaries
    tags = history.tags
    for i, t in enumerate(tags):
        if tags[i - 1] != t and i > 0:
            ax.axvline(i + 0.5, color="#2c3a52", lw=0.9, ls=":")
    seen = set()
    for i, t in enumerate(tags):
        if t not in seen:
            seen.add(t)
            ax.text(i + 1, ax.get_ylim()[1] * 0.97, t, fontsize=7,
                    color="#7f8ea6", rotation=90, va="top", ha="center")

    ax.set_xlabel("Statistical-timing evaluation #")
    ax.set_ylabel("Objective score")
    ax.set_title(f"AI search convergence — {len(s)} evaluations")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_pareto(points: Sequence[Tuple[float, float, float]],
               base_pt: Tuple[float, float],
               opt_pt: Tuple[float, float],
               path: str = "fig_pareto.png") -> str:
    """Area vs. yield Pareto scatter over the search history."""
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=140)
    if points:
        arr = np.array(points)
        sc = ax.scatter(arr[:, 0], 100 * arr[:, 1], c=arr[:, 2],
                        cmap="viridis", s=26, alpha=0.85,
                        edgecolors="#0e1420", linewidths=0.4)
        cb = fig.colorbar(sc, ax=ax, pad=0.02)
        cb.set_label("power (mW)", color="#9aa4b2", fontsize=8)
        cb.ax.yaxis.set_tick_params(color="#9aa4b2", labelsize=7)
        plt.setp(plt.getp(cb.ax, "yticklabels"), color="#9aa4b2")
    ax.scatter([base_pt[0]], [100 * base_pt[1]], marker="D", s=110,
               color=C_BASE, edgecolors="white", linewidths=1.2,
               zorder=6, label="Baseline")
    ax.scatter([opt_pt[0]], [100 * opt_pt[1]], marker="*", s=260,
               color="#ffd76a", edgecolors="#0e1420", linewidths=0.6,
               zorder=7, label="AI-optimized")
    ax.set_xlabel("Standard-cell area (µm²)")
    ax.set_ylabel("Timing yield (%)")
    ax.set_title("Design space explored — area / yield / power")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_path(base_r, opt_r, path: str = "fig_paths.png") -> str:
    """Critical-path slack comparison, top-N paths."""
    bp = sorted(base_r.paths, key=lambda t: t[2])[:14]
    bo = {n: s for n, d, s in opt_r.paths}
    names = [n for n, d, s in bp]
    sb = [s for n, d, s in bp]
    so = [bo.get(n, np.nan) for n in names]
    x = np.arange(len(names))
    w = 0.38

    fig, ax = plt.subplots(figsize=(8.4, 3.8), dpi=140)
    ax.bar(x - w / 2, sb, w, color=C_BASE, alpha=0.9, label="Baseline")
    ax.bar(x + w / 2, so, w, color=C_OPT, alpha=0.9, label="AI-optimized")
    ax.axhline(0, color="#ffd76a", lw=1.3, ls="--")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Slack (ps)")
    ax.set_title("Worst 14 timing endpoints — slack before and after optimization")
    ax.legend(frameon=False, fontsize=9)
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_corners(corners_b: Dict[str, float], corners_o: Dict[str, float],
                path: str = "fig_corners.png") -> str:
    """Deterministic PVT-corner slack comparison."""
    keys = list(corners_b.keys())
    x = np.arange(len(keys))
    w = 0.38
    fig, ax = plt.subplots(figsize=(7.6, 3.8), dpi=140)
    ax.bar(x - w / 2, [corners_b[k] for k in keys], w, color=C_BASE,
           alpha=0.9, label="Baseline")
    ax.bar(x + w / 2, [corners_o[k] for k in keys], w, color=C_OPT,
           alpha=0.9, label="AI-optimized")
    ax.axhline(0, color="#ffd76a", lw=1.3, ls="--")
    ax.set_xticks(x)
    ax.set_xticklabels(keys, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Worst slack (ps)")
    ax.set_title("Deterministic PVT-corner analysis")
    ax.legend(frameon=False, fontsize=9)
    _nice(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
