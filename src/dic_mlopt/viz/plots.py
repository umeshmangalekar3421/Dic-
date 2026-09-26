"""Publication-style figures for the course report."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np
import pandas as pd
import seaborn as sns

from dic_mlopt import config as C
from dic_mlopt.physics.cells import CELLS
from dic_mlopt.physics.characterize import CellCharacterizer
from dic_mlopt.physics.mosfet import nmos, pmos

sns.set_theme(style="whitegrid", context="talk", font="DejaVu Sans")
plt.rcParams.update({
    "figure.figsize": (8.2, 5.2),
    "savefig.bbox": "tight",
    "savefig.facecolor": "white",
    "axes.titlesize": 13,
    "axes.labelsize": 12,
    "legend.fontsize": 9,
    "figure.dpi": 120,
})
PAL = sns.color_palette("deep")


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_iv(fig_dir: Path):
    vds = np.linspace(0, 1.8, 80)
    fig, ax = plt.subplots()
    for vgs, col in zip([0.6, 0.9, 1.2, 1.5, 1.8], PAL):
        ids = nmos.ids(vgs, vds, 1.0, C.LMIN_UM, 25.0) * 1e3
        ax.plot(vds, ids, color=col, label=f"Vgs={vgs:.1f} V")
    ax.set_xlabel("Vds (V)")
    ax.set_ylabel("Ids (mA)  [W = 1 µm]")
    ax.set_title("SKY130-calibrated NMOS I–V (α-power + subthreshold)")
    ax.legend(frameon=False, ncol=2)
    _save(fig, fig_dir / "01_nmos_iv.png")

    fig, ax = plt.subplots()
    vgs = np.linspace(0, 1.8, 120)
    for temp, col in zip([-40, 25, 85, 125], PAL):
        ids = nmos.ids(vgs, 1.8, 1.0, C.LMIN_UM, temp)
        ax.semilogy(vgs, np.maximum(ids, 1e-15), color=col, label=f"T={temp:.0f} °C")
    ax.set_xlabel("Vgs (V)")
    ax.set_ylabel("Ids (A)  [log]")
    ax.set_title("NMOS subthreshold swing vs temperature")
    ax.legend(frameon=False)
    _save(fig, fig_dir / "02_nmos_subthreshold.png")


def plot_pvt_surfaces(fig_dir: Path, char: CellCharacterizer):
    vdd = np.linspace(1.44, 1.98, 16)
    fig, ax = plt.subplots()
    for corner, col in zip(["ss", "tt", "ff"], PAL):
        dly = []
        for v in vdd:
            dly.append(char.fo4_ps(vdd=v, corner=corner))
        ax.plot(vdd, dly, marker="o", color=col, label=corner.upper())
    ax.set_xlabel("VDD (V)")
    ax.set_ylabel("FO4 inverter delay (ps)")
    ax.set_title("FO4 delay vs supply at 25 °C")
    ax.legend(frameon=False)
    _save(fig, fig_dir / "03_fo4_vs_vdd.png")

    temps = np.linspace(-40, 125, 14)
    fig, ax = plt.subplots()
    for corner, col in zip(["ss", "tt", "ff"], PAL):
        dly = [char.fo4_ps(temp_c=t, corner=corner) for t in temps]
        ax.plot(temps, dly, marker="o", color=col, label=corner.upper())
    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("FO4 inverter delay (ps)")
    ax.set_title("FO4 delay vs temperature at 1.8 V")
    ax.legend(frameon=False)
    _save(fig, fig_dir / "04_fo4_vs_temp.png")

    fig, ax = plt.subplots()
    wn = C.WMIN_UM * 2
    wp = wn * 2
    for corner, col in zip(["ss", "tt", "ff"], PAL):
        leak = []
        for t in temps:
            r = char.characterize(
                CELLS["INV"], wn, wp, C.LMIN_UM, C.VDD_NOM, t, 8.0, 30.0, corner
            )
            leak.append(float(np.mean(r.p_leak_nw)))
        ax.semilogy(temps, leak, marker="o", color=col, label=corner.upper())
    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("INV leakage (nW)")
    ax.set_title("Leakage vs temperature (process corners)")
    ax.legend(frameon=False)
    _save(fig, fig_dir / "05_leakage_vs_temp.png")


def plot_cell_bars(fig_dir: Path, char: CellCharacterizer):
    names = list(C.COMBINATIONAL)
    delays, leaks, areas = [], [], []
    for n in names:
        cell = CELLS[n]
        wn = C.WMIN_UM * cell.n_series_n
        wp = C.WMIN_UM * 2 * cell.n_series_p
        r = char.characterize(cell, wn, wp, C.LMIN_UM, C.VDD_NOM, 25, 8.0, 30, "tt")
        delays.append(float(np.mean(r.delay_ps)))
        leaks.append(float(np.mean(r.p_leak_nw)))
        areas.append(float(np.mean(r.area_um2)))
    fig, ax = plt.subplots()
    ax.bar(names, delays, color=PAL[0])
    ax.set_ylabel("Delay (ps)  [tt, 1.8 V, 8 fF]")
    ax.set_title("Balanced-min sizing: cell delay")
    plt.xticks(rotation=20)
    _save(fig, fig_dir / "06_cell_delay_bar.png")

    fig, ax = plt.subplots()
    ax.bar(names, areas, color=PAL[2])
    ax.set_ylabel("Area (µm²)")
    ax.set_title("Row-based cell area")
    plt.xticks(rotation=20)
    _save(fig, fig_dir / "07_cell_area_bar.png")


def plot_dataset(fig_dir: Path, df: pd.DataFrame):
    fig, ax = plt.subplots()
    sample = df.sample(min(len(df), 2500), random_state=0)
    sns.scatterplot(
        data=sample, x="delay_ps", y="p_leak_nw", hue="corner",
        alpha=0.45, ax=ax, s=18, edgecolor=None,
    )
    ax.set_yscale("log")
    ax.set_xlabel("Delay (ps)")
    ax.set_ylabel("Leakage (nW)")
    ax.set_title("Characterization cloud (PVT × sizing × cell)")
    ax.legend(title="corner", frameon=False)
    _save(fig, fig_dir / "08_dataset_delay_leak.png")

    fig, ax = plt.subplots(figsize=(9, 6))
    cols = ["wn_um", "wp_um", "l_um", "vdd", "temp_c", "cload_ff", "slew_ps",
            "delay_ps", "e_dyn_fj", "p_leak_nw", "area_um2"]
    corr = df[cols].corr()
    sns.heatmap(corr, ax=ax, cmap="vlag", center=0, annot=False)
    ax.set_title("Feature / target correlation")
    _save(fig, fig_dir / "09_correlation.png")

    fig, ax = plt.subplots()
    sns.boxplot(data=df, x="cell", y="delay_ps", hue="corner", ax=ax, fliersize=1)
    ax.set_ylim(0, np.quantile(df["delay_ps"], 0.95))
    ax.set_title("Delay distribution by cell and corner")
    ax.legend(frameon=False, ncol=3)
    plt.xticks(rotation=20)
    _save(fig, fig_dir / "10_delay_box.png")


def plot_ml(fig_dir: Path, test: pd.DataFrame, yhat: np.ndarray, yhat_ridge: np.ndarray,
            importance: dict, ml_report: dict):
    y = test["delay_ps"].values
    fig, ax = plt.subplots()
    ax.scatter(y, yhat, s=12, alpha=0.35, color=PAL[0], label="HGB")
    lim = [0, max(y.max(), yhat.max()) * 1.02]
    ax.plot(lim, lim, "k--", lw=1)
    ax.set_xlabel("Physics delay (ps)")
    ax.set_ylabel("Predicted delay (ps)")
    r2 = ml_report["targets"]["delay_ps"]["hgb"]["test"]["r2"]
    ax.set_title(f"Delay surrogate parity  (HGB R² = {r2:.3f})")
    ax.legend(frameon=False)
    _save(fig, fig_dir / "11_ml_parity_delay.png")

    fig, ax = plt.subplots()
    ax.scatter(test["p_leak_nw"], yhat_ridge, s=12, alpha=0.35, color=PAL[3])
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Physics leakage (nW)")
    ax.set_ylabel("Predicted leakage (nW)")
    r2l = ml_report["targets"]["p_leak_nw"]["hgb"]["test"]["r2"]
    ax.set_title(f"Leakage surrogate parity  (HGB R² = {r2l:.3f})")
    _save(fig, fig_dir / "12_ml_parity_leak.png")

    keys = list(importance.keys())
    vals = [importance[k] for k in keys]
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    order = np.argsort(vals)
    ax.barh(np.array(keys)[order], np.array(vals)[order], color=PAL[1])
    ax.set_xlabel("Permutation ΔR²")
    ax.set_title("Delay model — permutation importance")
    _save(fig, fig_dir / "13_feature_importance.png")

    # model family comparison
    fig, ax = plt.subplots()
    fams = ["ridge", "rf", "hgb"]
    labels = ["Ridge", "Random Forest", "HistGB"]
    r2s = [ml_report["targets"]["delay_ps"][f]["test"]["r2"] for f in fams]
    ax.bar(labels, r2s, color=[PAL[3], PAL[4], PAL[0]])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Test R²  (delay)")
    ax.set_title("Baseline vs ensemble surrogates")
    _save(fig, fig_dir / "14_model_compare.png")


def plot_pareto(fig_dir: Path, libopt: dict):
    fig, ax = plt.subplots()
    for i, name in enumerate(["INV", "NAND2", "NOR2", "XOR2"]):
        F = np.asarray(libopt["cells"][name]["pareto_F"])
        ax.scatter(F[:, 0], F[:, 1], s=28, color=PAL[i], label=name, alpha=0.8)
        k = libopt["cells"][name]["knee"]
        # highlight knee via nearest
        d = (F[:, 0] - F[:, 0].min()) ** 2 + (F[:, 1] - F[:, 1].min()) ** 2
        ax.scatter(F[np.argmin(d), 0], F[np.argmin(d), 1], s=90, marker="*", color=PAL[i], edgecolor="k")
    ax.set_xlabel("Worst-corner delay (ps)  [surrogate]")
    ax.set_ylabel("Typical energy (fJ)")
    ax.set_title("NSGA-II Pareto fronts (★ = knee)")
    ax.legend(frameon=False)
    _save(fig, fig_dir / "15_pareto.png")

    so = libopt["signoff"]
    fig, ax = plt.subplots()
    cells = list(C.CELL_NAMES)
    x = np.arange(len(cells))
    w = 0.25
    for j, tag in enumerate(("min", "balanced", "ml_opt")):
        sub = so[so["sizing"] == tag].set_index("cell").loc[list(cells)]
        ax.bar(x + (j - 1) * w, sub["delay_wc_ps"], width=w, label=tag, color=PAL[j])
    ax.set_xticks(x)
    ax.set_xticklabels(cells, rotation=20)
    ax.set_ylabel("ss / 125 °C / 1.62 V delay (ps)")
    ax.set_title("Physics sign-off: delay by sizing policy")
    ax.legend(frameon=False)
    _save(fig, fig_dir / "16_signoff_delay.png")

    fig, ax = plt.subplots()
    for j, tag in enumerate(("min", "balanced", "ml_opt")):
        sub = so[so["sizing"] == tag].set_index("cell").loc[list(cells)]
        ax.bar(x + (j - 1) * w, 100 * sub["yield"], width=w, label=tag, color=PAL[j])
    ax.set_xticks(x)
    ax.set_xticklabels(cells, rotation=20)
    ax.set_ylabel("Monte-Carlo yield (%)")
    ax.set_title("Cell yield at delay + leakage spec (ss / 85 °C)")
    ax.legend(frameon=False)
    ax.set_ylim(0, 105)
    _save(fig, fig_dir / "17_signoff_yield.png")

    fig, ax = plt.subplots()
    sub = so[so["sizing"] == "ml_opt"]
    ax.scatter(sub["delay_wc_ps"], sub["energy_tt_fj"], s=70, c=range(len(sub)), cmap="viridis")
    for _, r in sub.iterrows():
        ax.annotate(r["cell"], (r["delay_wc_ps"], r["energy_tt_fj"]), fontsize=8,
                    textcoords="offset points", xytext=(4, 4))
    ax.set_xlabel("WC delay (ps)")
    ax.set_ylabel("tt energy (fJ)")
    ax.set_title("Optimized library — energy–delay")
    _save(fig, fig_dir / "18_opt_ed.png")


def plot_sta(fig_dir: Path, sta_table: pd.DataFrame, mc: dict):
    fig, ax = plt.subplots()
    ax.bar(sta_table["corner_label"], sta_table["fmax_mhz"], color=PAL[: len(sta_table)])
    f_tgt = 1000.0 / C.ADDER_PERIOD_NS
    ax.axhline(f_tgt, ls="--", color="k", label=f"{f_tgt:.0f} MHz target")
    ax.set_ylabel("Fmax (MHz)")
    ax.set_title("Registered 8-bit RCA — Fmax vs PVT")
    ax.legend(frameon=False)
    plt.xticks(rotation=15)
    _save(fig, fig_dir / "19_sta_fmax.png")

    fig, ax = plt.subplots()
    ax.hist(mc["fmax_mhz"], bins=24, color=PAL[0], edgecolor="white")
    ax.axvline(mc["fmax_p5"], color="k", ls="--", label=f"P5 = {mc['fmax_p5']:.0f} MHz")
    ax.set_xlabel("Fmax (MHz)")
    ax.set_ylabel("MC samples")
    ax.set_title(
        f"Block-level Fmax Monte Carlo  "
        f"(yield@{1000.0/C.ADDER_PERIOD_NS:.0f} MHz = {100*mc['yield']:.1f} %)"
    )
    ax.legend(frameon=False)
    _save(fig, fig_dir / "20_sta_mc.png")

    fig, ax = plt.subplots(figsize=(9, 3.8))
    path = mc["base"]["critical_path"]
    ax.set_xlim(0, max(len(path), 1))
    ax.set_ylim(0, 1)
    for i, n in enumerate(path):
        ax.add_patch(Rectangle((i + 0.05, 0.3), 0.9, 0.4, color=PAL[i % 6], alpha=0.85))
        ax.text(i + 0.5, 0.5, n, ha="center", va="center", fontsize=8, color="white")
        if i < len(path) - 1:
            ax.annotate("", xy=(i + 1.05, 0.5), xytext=(i + 0.95, 0.5),
                        arrowprops=dict(arrowstyle="->", color="k"))
    ax.axis("off")
    ax.set_title("Critical path (net names, launch → capture)")
    _save(fig, fig_dir / "21_critical_path.png")


def plot_schematics(fig_dir: Path):
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    titles = ["INV", "NAND2", "NOR2"]
    for ax, t in zip(axes, titles):
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(t, fontsize=12)
        ax.plot([1, 9], [9, 9], color="#c44", lw=2)
        ax.plot([1, 9], [1, 1], color="#444", lw=2)
        ax.text(9.2, 9, "VDD", fontsize=8, color="#c44")
        ax.text(9.2, 1, "GND", fontsize=8)
        if t == "INV":
            ax.add_patch(Rectangle((4, 5.6), 2, 2.6, fill=False, lw=1.5, color="#c44"))
            ax.add_patch(Rectangle((4, 1.8), 2, 2.6, fill=False, lw=1.5, color="#246"))
            ax.text(4.4, 6.6, "PMOS", fontsize=8, color="#c44")
            ax.text(4.4, 2.8, "NMOS", fontsize=8, color="#246")
            ax.plot([5, 5], [8.2, 9], color="#c44", lw=1.4)
            ax.plot([5, 5], [1, 1.8], color="#444", lw=1.4)
            ax.plot([5, 5], [4.4, 5.6], color="#222", lw=1.4)
            ax.plot([2, 4], [5, 5], color="#222", lw=1.4)
            ax.text(1.2, 5.2, "A", fontsize=9)
            ax.plot([6, 8.5], [5, 5], color="#222", lw=1.4)
            ax.text(8.5, 5.2, "Y", fontsize=9)
        elif t == "NAND2":
            ax.add_patch(Rectangle((2.2, 6.2), 2.2, 2.0, fill=False, lw=1.4, color="#c44"))
            ax.add_patch(Rectangle((5.6, 6.2), 2.2, 2.0, fill=False, lw=1.4, color="#c44"))
            ax.add_patch(Rectangle((4.0, 3.4), 2.2, 1.8, fill=False, lw=1.4, color="#246"))
            ax.add_patch(Rectangle((4.0, 1.5), 2.2, 1.6, fill=False, lw=1.4, color="#246"))
            ax.text(2.4, 7.0, "P_A", fontsize=8, color="#c44")
            ax.text(5.8, 7.0, "P_B", fontsize=8, color="#c44")
            ax.text(4.4, 4.0, "N_A", fontsize=8, color="#246")
            ax.text(4.4, 2.0, "N_B", fontsize=8, color="#246")
            ax.plot([3.3, 3.3], [8.2, 9], color="#c44", lw=1.2)
            ax.plot([6.7, 6.7], [8.2, 9], color="#c44", lw=1.2)
            ax.plot([5.1, 5.1], [1, 1.5], color="#444", lw=1.2)
        else:
            ax.add_patch(Rectangle((4.0, 6.4), 2.2, 1.6, fill=False, lw=1.4, color="#c44"))
            ax.add_patch(Rectangle((4.0, 4.6), 2.2, 1.6, fill=False, lw=1.4, color="#c44"))
            ax.add_patch(Rectangle((2.2, 1.6), 2.2, 2.0, fill=False, lw=1.4, color="#246"))
            ax.add_patch(Rectangle((5.6, 1.6), 2.2, 2.0, fill=False, lw=1.4, color="#246"))
            ax.text(4.3, 7.0, "P_A", fontsize=8, color="#c44")
            ax.text(4.3, 5.1, "P_B", fontsize=8, color="#c44")
            ax.text(2.4, 2.4, "N_A", fontsize=8, color="#246")
            ax.text(5.8, 2.4, "N_B", fontsize=8, color="#246")
    _save(fig, fig_dir / "22_schematics.png")

    # flow diagram
    fig, ax = plt.subplots(figsize=(10.5, 3.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis("off")
    boxes = [
        (0.2, "Cells +\ncompact PVT"),
        (2.2, "DOE data\n(LHS × corners)"),
        (4.2, "ML surrogate\nHGB / RF"),
        (6.2, "NSGA-II\nyield sizing"),
        (8.2, "Liberty +\n8-bit STA"),
    ]
    for x, t in boxes:
        ax.add_patch(FancyBboxPatch((x, 0.7), 1.7, 1.7, boxstyle="round,pad=0.08",
                                    facecolor="#eef4ff", edgecolor="#245", lw=1.4))
        ax.text(x + 0.85, 1.55, t, ha="center", va="center", fontsize=9)
    for x in (1.9, 3.9, 5.9, 7.9):
        ax.annotate("", xy=(x + 0.3, 1.55), xytext=(x, 1.55),
                    arrowprops=dict(arrowstyle="->", color="#245", lw=1.4))
    ax.set_title("Project flow", fontsize=13)
    _save(fig, fig_dir / "00_flow.png")


def make_all_plots(fig_dir: Path, df: pd.DataFrame, ml_report: dict, libopt: dict,
                   test: pd.DataFrame, yhat_delay, yhat_leak, sta_table, mc) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    char = CellCharacterizer()
    plot_schematics(fig_dir)
    plot_iv(fig_dir)
    plot_pvt_surfaces(fig_dir, char)
    plot_cell_bars(fig_dir, char)
    plot_dataset(fig_dir, df)
    plot_ml(fig_dir, test, yhat_delay, yhat_leak, ml_report.get("delay_importance", {}), ml_report)
    plot_pareto(fig_dir, libopt)
    plot_sta(fig_dir, sta_table, mc)
