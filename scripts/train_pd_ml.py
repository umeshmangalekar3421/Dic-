"""
Train High-Accuracy Physical Design ML Surrogate Models.
========================================================

Dataset Source: CircuitOps (Open-Source SkyWater 130nm Physical Design Dataset)
Circuits: GCD, RISCV32I, IBEX, AES

Tasks:
  1. Post-Routing Wirelength Prediction (net_route_length)
  2. Post-Routing Timing Slack Prediction (pin_slack)
"""

import os
import json
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.model_selection import train_test_split
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error


def train_synthesis_cap_model(data_dir: str, save_path: str = "models/synthesis_cap_model.pkl") -> tuple:
    print("[1/4] Training Stage 1 ML: Synthesis Net Capacitance Predictor...")
    dfs = []
    for d in ["gcd", "riscv32i", "ibex", "aes"]:
        p = os.path.join(data_dir, d, "net_properties.csv")
        if os.path.exists(p):
            dfs.append(pd.read_csv(p))

    df = pd.concat(dfs, ignore_index=True)
    df = df[df["total_cap"].notnull() & (df["total_cap"] > 0)]
    features = ["fanout"]
    X = df[features].fillna(0)
    y = df["total_cap"] * 1e15  # fF

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = HistGradientBoostingRegressor(max_iter=150, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = float(r2_score(y_test, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae = float(mean_absolute_error(y_test, y_pred))

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    joblib.dump({"model": model, "features": features, "unit": "fF"}, save_path)

    metrics = {"stage": "1_synthesis", "task": "net_capacitance", "samples": len(df), "R2": round(r2, 4), "RMSE_fF": round(rmse, 2), "MAE_fF": round(mae, 2)}
    print(f"      [Stage 1] Net Cap Model   : R² = {metrics['R2']:.4f}, RMSE = {metrics['RMSE_fF']} fF, MAE = {metrics['MAE_fF']} fF")
    return metrics, (y_test.values[:1000], y_pred[:1000])


def train_wirelength_model(data_dir: str, save_path: str = "models/wirelength_model.pkl") -> tuple:
    print("[2/4] Training Stage 2 ML: Placement Wirelength Predictor...")
    dfs = []
    for d in ["gcd", "riscv32i", "ibex", "aes"]:
        p = os.path.join(data_dir, d, "net_properties.csv")
        if os.path.exists(p):
            dfs.append(pd.read_csv(p))

    df = pd.concat(dfs, ignore_index=True)
    features = ["fanout", "total_cap", "net_cap", "net_coupling", "net_res"]
    X = df[features].fillna(0)
    y = df["net_route_length"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = HistGradientBoostingRegressor(max_iter=150, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = float(r2_score(y_test, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae = float(mean_absolute_error(y_test, y_pred))

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    joblib.dump({"model": model, "features": features, "unit": "nm"}, save_path)

    metrics = {"stage": "2_placement", "task": "wirelength", "samples": len(df), "R2": round(r2, 4), "RMSE_nm": round(rmse, 2), "MAE_nm": round(mae, 2)}
    print(f"      [Stage 2] Wirelength Model: R² = {metrics['R2']:.4f}, RMSE = {metrics['RMSE_nm']} nm, MAE = {metrics['MAE_nm']} nm")
    return metrics, (y_test.values[:1000], y_pred[:1000])


def train_slew_model(data_dir: str, save_path: str = "models/slew_model.pkl") -> tuple:
    print("[3/4] Training Stage 3 ML: Routing Slew / Transition Predictor...")
    dfs = []
    for d in ["gcd", "riscv32i", "ibex", "aes"]:
        p_pins = os.path.join(data_dir, d, "pin_properties.csv")
        p_nets = os.path.join(data_dir, d, "net_properties.csv")
        if os.path.exists(p_pins) and os.path.exists(p_nets):
            pins = pd.read_csv(p_pins)
            nets = pd.read_csv(p_nets)
            m = pd.merge(pins, nets, on="net_name", how="inner")
            dfs.append(m)

    df = pd.concat(dfs, ignore_index=True)
    df = df[df["pin_tran"].notnull() & (df["pin_tran"] > 0)]
    features = ["fanout", "total_cap", "net_cap", "net_res", "input_pin_cap", "maxcap", "maxtran", "is_in_clk"]
    X = df[features].fillna(0)
    y = df["pin_tran"] * 1e12  # ps

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = HistGradientBoostingRegressor(max_iter=150, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = float(r2_score(y_test, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae = float(mean_absolute_error(y_test, y_pred))

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    joblib.dump({"model": model, "features": features, "unit": "ps"}, save_path)

    metrics = {"stage": "3_routing", "task": "pin_slew", "samples": len(df), "R2": round(r2, 4), "RMSE_ps": round(rmse, 2), "MAE_ps": round(mae, 2)}
    print(f"      [Stage 3] Slew Model      : R² = {metrics['R2']:.4f}, RMSE = {metrics['RMSE_ps']} ps, MAE = {metrics['MAE_ps']} ps")
    return metrics, (y_test.values[:1000], y_pred[:1000])


def train_slack_model(data_dir: str, save_path: str = "models/slack_model.pkl") -> tuple:
    print("[4/4] Training Stage 4 ML: Timing Slack & Critical Path Predictor...")
    dfs = []
    for d in ["gcd", "riscv32i", "ibex"]:
        p = os.path.join(data_dir, d, "pin_properties.csv")
        if os.path.exists(p):
            dfs.append(pd.read_csv(p))

    df = pd.concat(dfs, ignore_index=True)
    # Filter out unconstrained 1e30 OpenSTA sentinels (< 1 us)
    df = df[df["pin_slack"].notnull() & np.isfinite(df["pin_slack"]) & (df["pin_slack"].abs() < 1e-6)]

    features = [
        "x", "y", "is_in_clk", "is_port", "is_startpoint", "is_endpoint",
        "dir", "maxcap", "maxtran", "num_reachable_endpoint",
        "pin_tran", "pin_rise_arr", "pin_fall_arr", "input_pin_cap"
    ]
    X = df[features].fillna(0)
    y = df["pin_slack"] * 1e12  # ps

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = HistGradientBoostingRegressor(max_iter=150, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = float(r2_score(y_test, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae = float(mean_absolute_error(y_test, y_pred))

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    joblib.dump({"model": model, "features": features, "unit": "ps"}, save_path)

    metrics = {"stage": "4_timing_sta", "task": "timing_slack", "samples": len(df), "R2": round(r2, 4), "RMSE_ps": round(rmse, 2), "MAE_ps": round(mae, 2)}
    print(f"      [Stage 4] Slack Model     : R² = {metrics['R2']:.4f}, RMSE = {metrics['RMSE_ps']} ps, MAE = {metrics['MAE_ps']} ps")
    return metrics, (y_test.values[:1000], y_pred[:1000])


def main():
    data_dir = "Dataset/CircuitOps-main/IRs/sky130hd"
    if not os.path.exists(data_dir):
        raise FileNotFoundError(f"Dataset directory not found: {data_dir}")

    cap_metrics, (cap_true, cap_pred) = train_synthesis_cap_model(data_dir)
    wl_metrics, (wl_true, wl_pred) = train_wirelength_model(data_dir)
    slew_metrics, (slew_true, slew_pred) = train_slew_model(data_dir)
    slack_metrics, (slack_true, slack_pred) = train_slack_model(data_dir)

    results = {
        "stage_1_synthesis": cap_metrics,
        "stage_2_placement": wl_metrics,
        "stage_3_routing": slew_metrics,
        "stage_4_timing": slack_metrics
    }
    os.makedirs("reports", exist_ok=True)
    with open("reports/ml_metrics.json", "w") as f:
        json.dump(results, f, indent=2)

    # Plot 4-Stage Accuracy Figure
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # Stage 1: Synthesis Cap
    axes[0, 0].scatter(cap_true, cap_pred, alpha=0.3, s=10, color="#8c564b")
    axes[0, 0].plot([cap_true.min(), cap_true.max()], [cap_true.min(), cap_true.max()], "r--", lw=1.5)
    axes[0, 0].set_title(f"Stage 1: Synthesis Net Cap ($R^2 = {cap_metrics['R2']:.4f}$)")
    axes[0, 0].set_xlabel("Ground-Truth Net Cap (fF)")
    axes[0, 0].set_ylabel("Predicted Net Cap (fF)")
    axes[0, 0].grid(True, linestyle="--", alpha=0.6)

    # Stage 2: Wirelength
    axes[0, 1].scatter(wl_true, wl_pred, alpha=0.3, s=10, color="#1f77b4")
    axes[0, 1].plot([wl_true.min(), wl_true.max()], [wl_true.min(), wl_true.max()], "r--", lw=1.5)
    axes[0, 1].set_title(f"Stage 2: Placement Wirelength ($R^2 = {wl_metrics['R2']:.4f}$)")
    axes[0, 1].set_xlabel("Ground-Truth Wirelength (nm)")
    axes[0, 1].set_ylabel("Predicted Wirelength (nm)")
    axes[0, 1].grid(True, linestyle="--", alpha=0.6)

    # Stage 3: Slew / Transition
    axes[1, 0].scatter(slew_true, slew_pred, alpha=0.3, s=10, color="#ff7f0e")
    axes[1, 0].plot([slew_true.min(), slew_true.max()], [slew_true.min(), slew_true.max()], "r--", lw=1.5)
    axes[1, 0].set_title(f"Stage 3: Routing Slew Degradation ($R^2 = {slew_metrics['R2']:.4f}$)")
    axes[1, 0].set_xlabel("Ground-Truth Slew (ps)")
    axes[1, 0].set_ylabel("Predicted Slew (ps)")
    axes[1, 0].grid(True, linestyle="--", alpha=0.6)

    # Stage 4: Timing Slack
    axes[1, 1].scatter(slack_true, slack_pred, alpha=0.3, s=10, color="#2ca02c")
    axes[1, 1].plot([slack_true.min(), slack_true.max()], [slack_true.min(), slack_true.max()], "r--", lw=1.5)
    axes[1, 1].set_title(f"Stage 4: Timing Slack ($R^2 = {slack_metrics['R2']:.4f}$)")
    axes[1, 1].set_xlabel("Ground-Truth Slack (ps)")
    axes[1, 1].set_ylabel("Predicted Slack (ps)")
    axes[1, 1].grid(True, linestyle="--", alpha=0.6)

    plt.tight_layout()
    plot_path = "reports/ml_accuracy.png"
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"\n[OK] All 4 flow stage ML models saved to models/")
    print(f"[OK] 4-panel correlation plot saved to {plot_path}")
    print(f"[OK] Summary metrics saved to reports/ml_metrics.json")


if __name__ == "__main__":
    main()
