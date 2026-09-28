"""Surrogate models that replace SPICE inside the optimizer.

Three families are trained for every target:
  * Ridge  — linear baseline (after one-hot + scaling)
  * Random forest
  * HistGradientBoosting (primary surrogate)

The industrial analogue is a Liberate / FineSim campaign feeding an
XGBoost delay model used by a sizing engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from dic_mlopt import config as C

FEATURES_NUM = [
    "wn_um", "wp_um", "wp_wn", "l_um", "vdd", "temp_c", "cload_ff", "slew_ps",
    "n_series_n", "n_series_p", "n_nmos", "n_pmos", "logical_effort", "is_seq",
]
FEATURES_CAT = ["cell", "corner"]
FEATURES = FEATURES_NUM + FEATURES_CAT
TARGETS = ["delay_ps", "e_dyn_fj", "p_leak_nw", "area_um2", "delay_rise_ps", "delay_fall_ps"]
LOG_TARGETS = {"p_leak_nw"}


def _log10(z):
    return np.log10(np.asarray(z, dtype=float))


def _exp10(z):
    return np.power(10.0, np.asarray(z, dtype=float))


def _maybe_log(est, target: str):
    if target not in LOG_TARGETS:
        return est
    return TransformedTargetRegressor(
        regressor=est,
        func=_log10,
        inverse_func=_exp10,
        check_inverse=False,
    )


def _split(df: pd.DataFrame, seed: int):
    trainval, test = train_test_split(df, test_size=C.TEST_SIZE, random_state=seed, stratify=df["cell"])
    train, val = train_test_split(
        trainval, test_size=C.VAL_SIZE / (1.0 - C.TEST_SIZE), random_state=seed, stratify=trainval["cell"]
    )
    return train, val, test


def _metrics(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = r2_score(y_true, y_pred)
    mape = float(np.mean(np.abs((y_true - y_pred) / np.maximum(np.abs(y_true), 1e-9)))) * 100.0
    return {"mae": float(mae), "rmse": rmse, "r2": float(r2), "mape_pct": mape}


def _make_ridge():
    pre = ColumnTransformer(
        [
            ("num", StandardScaler(), FEATURES_NUM),
            ("cat", OneHotEncoder(handle_unknown="ignore"), FEATURES_CAT),
        ]
    )
    return Pipeline([("pre", pre), ("model", Ridge(alpha=0.6))])


def _make_hgb():
    # HGB natively handles categoricals if we ordinal-code them; we one-hot via pandas later.
    return HistGradientBoostingRegressor(
        max_depth=6,
        learning_rate=0.08,
        max_iter=220,
        l2_regularization=0.05,
        min_samples_leaf=12,
        random_state=C.RNG_SEED,
    )


def _make_rf():
    return RandomForestRegressor(
        n_estimators=40,
        max_depth=12,
        min_samples_leaf=4,
        n_jobs=1,
        random_state=C.RNG_SEED,
    )


def _encode(df: pd.DataFrame) -> pd.DataFrame:
    out = df[FEATURES_NUM].copy()
    for col in FEATURES_CAT:
        dummies = pd.get_dummies(df[col], prefix=col)
        out = pd.concat([out.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)
    return out


def train_models(df: pd.DataFrame, out_dir: Path, seed: int = C.RNG_SEED) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    train, val, test = _split(df, seed)
    train.to_csv(out_dir / "train.csv", index=False)
    val.to_csv(out_dir / "val.csv", index=False)
    test.to_csv(out_dir / "test.csv", index=False)

    # Align dummy columns across splits
    x_train = _encode(train)
    x_val = _encode(val).reindex(columns=x_train.columns, fill_value=0)
    x_test = _encode(test).reindex(columns=x_train.columns, fill_value=0)

    report: dict = {"n_train": len(train), "n_val": len(val), "n_test": len(test), "targets": {}}
    bundles: Dict[str, dict] = {}

    for tgt in TARGETS:
        y_tr, y_va, y_te = train[tgt].values, val[tgt].values, test[tgt].values
        family = {}

        ridge = _maybe_log(_make_ridge(), tgt)
        ridge.fit(train[FEATURES], y_tr)
        family["ridge"] = {
            "val": _metrics(y_va, ridge.predict(val[FEATURES])),
            "test": _metrics(y_te, ridge.predict(test[FEATURES])),
        }

        hgb = _maybe_log(_make_hgb(), tgt)
        hgb.fit(x_train, y_tr)
        family["hgb"] = {
            "val": _metrics(y_va, hgb.predict(x_val)),
            "test": _metrics(y_te, hgb.predict(x_test)),
        }

        rf = _maybe_log(_make_rf(), tgt)
        rf.fit(x_train, y_tr)
        family["rf"] = {
            "val": _metrics(y_va, rf.predict(x_val)),
            "test": _metrics(y_te, rf.predict(x_test)),
        }

        report["targets"][tgt] = family
        bundles[tgt] = {
            "ridge": ridge,
            "hgb": hgb,
            "rf": rf,
            "columns": list(x_train.columns),
        }

    slim = {
        t: {"ridge": b["ridge"], "hgb": b["hgb"], "columns": b["columns"]}
        for t, b in bundles.items()
    }
    joblib.dump({"bundles": slim, "features_num": FEATURES_NUM, "features_cat": FEATURES_CAT},
                out_dir / "surrogates.joblib")
    # permutation importance on delay HGB (test set, subsample)
    report["delay_importance"] = _perm_importance(
        bundles["delay_ps"]["hgb"], x_test, test["delay_ps"].values, list(x_train.columns)
    )
    return report


def _perm_importance(model, x: pd.DataFrame, y: np.ndarray, cols: List[str], n_repeat: int = 4) -> dict:
    rng = np.random.default_rng(C.RNG_SEED)
    base = r2_score(y, model.predict(x))
    n = min(len(x), 900)
    idx = rng.choice(len(x), size=n, replace=False)
    xs = x.iloc[idx].copy()
    ys = y[idx]
    # group dummy columns back to original feature names
    groups = {}
    for c in cols:
        key = c.split("_")[0] if c.startswith("cell_") or c.startswith("corner_") else c
        if c.startswith("cell_"):
            key = "cell"
        elif c.startswith("corner_"):
            key = "corner"
        groups.setdefault(key, []).append(c)
    out = {}
    for key, members in groups.items():
        drops = []
        for _ in range(n_repeat):
            xp = xs.copy()
            for m in members:
                xp[m] = rng.permutation(xp[m].values)
            drops.append(base - r2_score(ys, model.predict(xp)))
        out[key] = float(np.mean(drops))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def load_models(path: Path):
    return joblib.load(path)


def predict_df(bundle_file, df: pd.DataFrame, target: str, model: str = "hgb") -> np.ndarray:
    pack = bundle_file if isinstance(bundle_file, dict) else joblib.load(bundle_file)
    b = pack["bundles"][target]
    if model == "ridge":
        return b["ridge"].predict(df[FEATURES])
    x = _encode(df).reindex(columns=b["columns"], fill_value=0)
    return b[model].predict(x)
