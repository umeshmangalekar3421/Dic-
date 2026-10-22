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


def train_wirelength_model(data_dir: str, save_path: str = "models/wirelength_model.pkl") -> dict:
    print("[1/2] Loading net properties for Wirelength Prediction...")
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
    joblib.dump({"model": model, "features": features}, save_path)

    metrics = {"task": "wirelength", "samples": len(df), "R2": round(r2, 4), "RMSE": round(rmse, 2), "MAE": round(mae, 2)}
    print(f"      Wirelength Model: R² = {metrics['R2']:.4f}, RMSE = {metrics['RMSE']}, MAE = {metrics['MAE']}")
    return metrics, (y_test.values[:1000], y_pred[:1000])


def train_slack_model(data_dir: str, save_path: str = "models/slack_model.pkl") -> dict:
    print("[2/2] Loading pin properties for Timing Slack Prediction...")
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
    # Target in picoseconds for numerical precision
    y = df["pin_slack"] * 1e12

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = HistGradientBoostingRegressor(max_iter=150, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = float(r2_score(y_test, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae = float(mean_absolute_error(y_test, y_pred))

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    joblib.dump({"model": model, "features": features, "target_unit": "ps"}, save_path)

    metrics = {"task": "timing_slack", "samples": len(df), "R2": round(r2, 4), "RMSE_ps": round(rmse, 2), "MAE_ps": round(mae, 2)}
    print(f"      Slack Model     : R² = {metrics['R2']:.4f}, RMSE = {metrics['RMSE_ps']} ps, MAE = {metrics['MAE_ps']} ps")
    return metrics, (y_test.values[:1000], y_pred[:1000])


def main():
    data_dir = "Dataset/CircuitOps-main/IRs/sky130hd"
    if not os.path.exists(data_dir):
        raise FileNotFoundError(f"Dataset directory not found: {data_dir}")

    wl_metrics, (wl_true, wl_pred) = train_wirelength_model(data_dir)
    slack_metrics, (slack_true, slack_pred) = train_slack_model(data_dir)

    results = {"wirelength": wl_metrics, "timing_slack": slack_metrics}
    with open("reports/ml_metrics.json", "w") as f:
        json.dump(results, f, indent=2)

    # Plot Accuracy Scatter Plots
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    # Wirelength Plot
    axes[0].scatter(wl_true, wl_pred, alpha=0.3, s=10, color="#1f77b4")
    axes[0].plot([wl_true.min(), wl_true.max()], [wl_true.min(), wl_true.max()], "r--", lw=1.5)
    axes[0].set_title(f"Wirelength Prediction ($R^2 = {wl_metrics['R2']:.4f}$)")
    axes[0].set_xlabel("Ground-Truth Wirelength (nm)")
    axes[0].set_ylabel("Predicted Wirelength (nm)")
    axes[0].grid(True, linestyle="--", alpha=0.6)

    # Slack Plot
    axes[1].scatter(slack_true, slack_pred, alpha=0.3, s=10, color="#2ca02c")
    axes[1].plot([slack_true.min(), slack_true.max()],
                 [slack_true.min(), slack_true.max()], "r--", lw=1.5)
    axes[1].set_title(f"Timing Slack Prediction ($R^2 = {slack_metrics['R2']:.4f}$)")
    axes[1].set_xlabel("Ground-Truth Slack (ps)")
    axes[1].set_ylabel("Predicted Slack (ps)")
    axes[1].grid(True, linestyle="--", alpha=0.6)

    plt.tight_layout()
    os.makedirs("reports", exist_ok=True)
    plot_path = "reports/ml_accuracy.png"
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"\n[OK] Trained models saved in models/")
    print(f"[OK] Correlation plot saved to {plot_path}")
    print(f"[OK] Summary metrics saved to reports/ml_metrics.json")


if __name__ == "__main__":
    main()
