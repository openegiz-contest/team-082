#!/usr/bin/env python3
"""Train the ML models of the Bozshakol twin on the open datasets in data/.

    python3 bozshakol/ml/train.py        # needs numpy, pandas, scikit-learn

Writes bozshakol/ml/models/*.json (plain JSON: gradient-boosted trees, linear
coefficients and a pre-computed 3D block-model grid) and metrics.json. The
twin runtime evaluates them in pure Python (sim/ml.py) — the stand needs no
ML libraries. Every model is validated out of sample; the metrics are copied
into the twins, where they are shown next to the model outputs.

Models
  flotation_silica   GBM soft sensor: % SiO2 in concentrate *now* from 21
                     process variables, their hourly change and the last lab
                     assay that has come back (3 h old) — Kaggle flotation
                     plant, CC0; time-ordered split, compared with that assay.
  geomet_grid        GBM spatial interpolation of Cu, Au, Fe, S, Al, K from 2000
                     drill-hole samples (GeoMet, CC BY 4.0); grouped CV by
                     drill hole, compared with inverse-distance weighting.
  geomet_hardness    Ridge: comminution breakage index t (th3) from assays.
  geomet_recovery    Ridge: locked-cycle Cu recovery (LCT) from assays.
  seismic_hazard     GBM classifier: hazardous next shift (seismic-bumps,
                     UCI, CC BY 4.0); stratified CV, ROC AUC.
  mwd_rocktype       GBM multiclass: rock type of a blasting round from its
                     MWD statistics (15 Norwegian tunnels, NGI, Zenodo
                     10358374, CC BY 4.0); per-tunnel split along the
                     chainage (last 25 % = test), compared with the majority
                     class and with the previous round's mapped rock.
  energy_load        GBM: plant active power 2 h ahead from the last half
                     hours, the same time yesterday, time of day and weekday
                     (mining and processing plant, Zenodo 20647907, CC BY-SA
                     4.0); per-month time split, compared with "same as now"
                     and "same time yesterday".
  fragmentation_ref  Rosin-Rammler and Swebrec fits of drone-measured muckpile
                     size distributions (El Aljibe quarry, Zenodo 10666378,
                     CC BY 4.0) — reference for the Kuz-Ram model of blasts.
"""

import json
import math
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score, roc_auc_score
from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "ml", "models")
SEED = 7


def export_gbm(model, features, kind, exact=False):
    trees = []
    for est in model.estimators_[:, 0]:
        t = est.tree_
        trees.append({
            "l": t.children_left.tolist(), "r": t.children_right.tolist(), "f": t.feature.tolist(),
            "t": [float(x) if exact else round(float(x), 6) for x in t.threshold], "v": [round(float(x), 6) for x in t.value[:, 0, 0]],
        })
    base = float(model._raw_predict_init(np.zeros((1, len(features))))[0, 0])
    return {"type": "gbm", "kind": kind, "features": features, "base": base, "lr": float(model.learning_rate), "trees": trees}


def export_gbm_multi(model, features):
    """Multiclass GBM: one tree list per class, softmax at inference."""
    per_class = []
    for k in range(model.estimators_.shape[1]):
        trees = []
        for est in model.estimators_[:, k]:
            t = est.tree_
            trees.append({
                "l": t.children_left.tolist(), "r": t.children_right.tolist(), "f": t.feature.tolist(),
                "t": [float(x) for x in t.threshold], "v": [round(float(x), 6) for x in t.value[:, 0, 0]],
            })
        per_class.append(trees)
    base = [float(v) for v in model._raw_predict_init(np.zeros((1, len(features))))[0]]
    return {"type": "gbm", "kind": "multiclass", "features": features, "classes": [str(c) for c in model.classes_],
            "base": base, "lr": float(model.learning_rate), "trees": per_class}


def check_parity(model, skl, X, feats, proba=False):
    """The pure-Python evaluator (sim/ml.py) must reproduce scikit-learn."""
    sys.path.insert(0, ROOT)
    from sim import ml as rt
    ref = skl.predict_proba(X)[:, 1] if proba else skl.predict(X)
    got = np.array([rt.gbm(model, dict(zip(feats, row))) for row in X])
    err = float(np.max(np.abs(ref - got)))
    assert err < 1e-4, f"parity error {err}"
    print(f"parity ok ({len(X)} rows, max |diff| {err:.2e})")


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{name}.json"), "w") as fh:
        json.dump(obj, fh, separators=(",", ":"))


# ---------------------------------------------------------------------------
LAB_DELAY_H = 3   # the laboratory assay reaches the control room ~3 h after sampling


def flotation_features(df):
    """Features available *now*: process variables of this hour, their change
    over the last hour, and the last assays that have already come back from
    the laboratory (LAB_DELAY_H hours old). Same code path as the runtime."""
    d = df.copy()
    proc = [c for c in df.columns if c not in ("hour", "iron_conc", "silica_conc")]
    for c in proc:
        d[c + "_d"] = d[c] - d[c].shift(1)
    d["silica_lab"] = d["silica_conc"].shift(LAB_DELAY_H)
    d["iron_lab"] = d["iron_conc"].shift(LAB_DELAY_H)
    d["silica_lab_m3"] = d["silica_conc"].shift(LAB_DELAY_H).rolling(3).mean()
    feats = proc + [c + "_d" for c in proc] + ["silica_lab", "iron_lab", "silica_lab_m3"]
    return d, feats


def flotation():
    df = pd.read_csv(os.path.join(DATA, "flotation-plant", "flotation_hourly.csv"))
    d, feats = flotation_features(df)
    d = d.dropna().reset_index(drop=True)
    X, y = d[feats].values, d["silica_conc"].values
    cut = int(len(d) * 0.8)
    m = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8, random_state=SEED, loss="huber")
    m.fit(X[:cut], y[:cut])
    p = m.predict(X[cut:])
    naive = d["silica_lab"].values[cut:]
    met = {
        "rows": len(d), "train": cut, "test": len(d) - cut, "lab_delay_h": LAB_DELAY_H,
        "split": "по времени: первые 80 % часов — обучение, последние 20 % — тест",
        "mae": round(mean_absolute_error(y[cut:], p), 3), "r2": round(r2_score(y[cut:], p), 3),
        "mae_naive": round(mean_absolute_error(y[cut:], naive), 3), "r2_naive": round(r2_score(y[cut:], naive), 3),
        "naive": f"последний пришедший анализ (возраст {LAB_DELAY_H} ч)",
        "test_from": d["hour"].iloc[cut], "test_to": d["hour"].iloc[-1],
    }
    imp = sorted(zip(feats, m.feature_importances_), key=lambda x: -x[1])[:6]
    met["top_features"] = [[f, round(float(v), 3)] for f, v in imp]
    model = export_gbm(m, feats, "regression")
    check_parity(model, m, X[cut:cut + 200], feats)
    model["metrics"] = met
    model["lab_delay_h"] = LAB_DELAY_H
    save("flotation_silica", model)
    return met


# ---------------------------------------------------------------------------
GEO_VARS = ["Cu ppm", "Au ppm", "Fe ppm", "S ppm", "Al ppm", "K ppm"]   # interpolated in space
ASSAYS = ["Cu ppm", "Fe ppm", "S ppm", "Al ppm", "K ppm", "Ca ppm", "Mg ppm"]  # inputs of the ridge models


def geo_to_model_z(z_geo):
    return (z_geo - 380.0) / 2.0


def model_to_geo(x, y, z):
    """Twin coordinates (pit centre at 0,0; z metres below the rim) -> GeoMet."""
    return x, y, 380.0 + 2.0 * z


def idw(train_xyz, train_v, q, power=2, k=12):
    d = np.sqrt(((q[:, None, :] - train_xyz[None, :, :]) ** 2).sum(-1)) + 1e-6
    idx = np.argsort(d, axis=1)[:, :k]
    dd = np.take_along_axis(d, idx, 1)
    w = 1 / dd ** power
    return (w * train_v[idx]).sum(1) / w.sum(1)


def geomet_grid():
    dh = pd.read_csv(os.path.join(DATA, "geomet", "drillholes.csv"))
    dh = dh[dh["Cu ppm"] > 0].reset_index(drop=True)
    xyz = dh[["X", "Y", "Z"]].values
    feats = np.c_[xyz, xyz[:, 0] + xyz[:, 1], xyz[:, 0] - xyz[:, 1]]
    groups = dh["HOLEID"].values
    gkf = GroupKFold(n_splits=5)
    metrics, models = {}, {}
    for var in GEO_VARS:
        y = np.log(dh[var].clip(lower=0.001).values)
        m = GradientBoostingRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, random_state=SEED)
        p = cross_val_predict(m, feats, y, cv=gkf, groups=groups)
        p_idw = np.zeros_like(y)
        for tr, te in gkf.split(feats, y, groups):
            p_idw[te] = idw(xyz[tr], y[tr], xyz[te])
        metrics[var] = {"r2_log": round(r2_score(y, p), 3), "r2_log_idw": round(r2_score(y, p_idw), 3)}
        m.fit(feats, y)
        models[var] = m
    # Pre-computed grid over the pit (twin coordinates).
    xs = np.arange(-1150, 1151, 50.0)
    ys = np.arange(-900, 801, 50.0)
    zs = np.arange(0, -226, -15.0)
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    X, Y, Z = model_to_geo(gx.ravel(), gy.ravel(), gz.ravel())
    q = np.c_[X, Y, Z, X + Y, X - Y]
    grid = {}
    for var, m in models.items():
        grid[var] = np.exp(m.predict(q)).round(1).tolist()
    obj = {"type": "grid", "x": xs.tolist(), "y": ys.tolist(), "z": zs.tolist(), "order": "x,y,z (z fastest)",
           "vars": GEO_VARS, "values": grid,
           "mapping": "GeoMet X,Y = twin x,y (m); GeoMet Z = 380 + 2 * twin z (twin z <= 0 below the pit rim)",
           "means": {v: round(float(np.mean(grid[v])), 1) for v in GEO_VARS}, "metrics": metrics,
           "samples": int(len(dh)), "holes": int(dh["HOLEID"].nunique())}
    save("geomet_grid", obj)
    return {"samples": obj["samples"], "holes": obj["holes"], **metrics}


def ridge_on_assays(csv, target):
    df = pd.read_csv(os.path.join(DATA, "geomet", csv)).dropna(subset=[target])
    X = np.log(df[ASSAYS].clip(lower=1).values)
    y = df[target].values
    groups = df["HOLEID"].values
    m = RidgeCV(alphas=np.logspace(-2, 3, 30))
    p = cross_val_predict(m, X, y, cv=GroupKFold(n_splits=5), groups=groups)
    m.fit(X, y)
    met = {"rows": int(len(df)), "r2_cv": round(r2_score(y, p), 3), "mae_cv": round(mean_absolute_error(y, p), 4),
           "mean": round(float(y.mean()), 4), "std": round(float(y.std()), 4), "alpha": round(float(m.alpha_), 3)}
    obj = {"type": "linear", "features": [f"log({v})" for v in ASSAYS], "coef": m.coef_.round(6).tolist(),
           "intercept": round(float(m.intercept_), 6), "target": target, "metrics": met}
    return obj, met


# ---------------------------------------------------------------------------
def seismic():
    rows, cols = [], []
    with open(os.path.join(DATA, "seismic-bumps", "seismic-bumps.arff")) as fh:
        data = False
        for line in fh:
            line = line.strip()
            if line.lower().startswith("@attribute"):
                cols.append(line.split()[1])
            elif line.lower().startswith("@data"):
                data = True
            elif data and line and not line.startswith("%"):
                rows.append(line.split(","))
    df = pd.DataFrame(rows, columns=cols)
    cat = {"a": 0, "b": 1, "c": 2, "d": 3}
    for c in ("seismic", "seismoacoustic", "ghazard"):
        df[c] = df[c].map(cat)
    df["shift"] = (df["shift"] == "N").astype(int)
    for c in df.columns:
        df[c] = pd.to_numeric(df[c])
    feats = [c for c in df.columns if c != "class"]
    X, y = df[feats].values, df["class"].values
    m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=SEED)
    p = cross_val_predict(m, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=SEED), method="predict_proba")[:, 1]
    auc = roc_auc_score(y, p)
    base_auc = roc_auc_score(y, df["ghazard"].values + 0.01 * df["genergy"].rank(pct=True).values)
    thr = float(np.quantile(p, 0.85))
    pred = p >= thr
    met = {"rows": int(len(df)), "positive_share": round(float(y.mean()), 3), "roc_auc_cv": round(auc, 3),
           "roc_auc_expert_ghazard": round(base_auc, 3), "threshold": round(thr, 3),
           "recall_at_threshold": round(float((pred & (y == 1)).sum() / max(1, (y == 1).sum())), 3),
           "precision_at_threshold": round(float((pred & (y == 1)).sum() / max(1, pred.sum())), 3)}
    # The runtime replays the last 20 % of the shifts: the deployed model never
    # sees them (records are in time order).
    cut = int(len(df) * 0.8)
    m.fit(X[:cut], y[:cut])
    ph = m.predict_proba(X[cut:])[:, 1]
    met["holdout_from_row"] = cut
    met["roc_auc_holdout"] = round(roc_auc_score(y[cut:], ph), 3) if y[cut:].sum() else None
    expert = df["ghazard"].values + 0.01 * df["genergy"].rank(pct=True).values
    met["roc_auc_expert_holdout"] = round(roc_auc_score(y[cut:], expert[cut:]), 3)
    model = export_gbm(m, feats, "binary")
    check_parity(model, m, X[cut:cut + 200], feats, proba=True)
    model["metrics"] = met
    save("seismic_hazard", model)
    return met


ENERGY_H = 4                     # forecast horizon: 4 half hours = 2 h
ENERGY_LAGS = [0, 1, 2, 3, 4, 8, 48]
ENERGY_FEATS = [f"lag{lag}" for lag in ENERGY_LAGS] + ["day_ago", "tod", "dow"]


def energy_frame(df):
    """Features for every half hour i: P at i-lag, P 24 h before the target, target time of day, weekday."""
    out = []
    for _, g in df.groupby("month"):
        g = g.sort_values(["day", "minute"]).copy()
        for lag in ENERGY_LAGS:
            g[f"lag{lag}"] = g["P_MW"].shift(lag)
        g["day_ago"] = g["P_MW"].shift(48 - ENERGY_H)
        g["y"] = g["P_MW"].shift(-ENERGY_H)
        g["tod"] = ((g["minute"] + 30 * ENERGY_H) % 1440) / 60
        g["dow"] = pd.to_datetime(g["date"]).dt.dayofweek
        out.append(g.dropna(subset=ENERGY_FEATS + ["y"]))
    return pd.concat(out)


def energy_load():
    df = pd.read_csv(os.path.join(DATA, "energy-gok", "energy_30min.csv"))
    d = energy_frame(df)
    pos = d.groupby("month").cumcount() / d.groupby("month")["P_MW"].transform("count")
    tr, te = d[pos < 0.75], d[pos >= 0.75]
    m = GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=SEED)
    m.fit(tr[ENERGY_FEATS].values, tr["y"].values)
    p = m.predict(te[ENERGY_FEATS].values)
    cosphi = df["P_MW"] / np.sqrt(df["P_MW"] ** 2 + df["Q_Mvar"] ** 2)
    daily = df.groupby(["month", "day"])["P_MW"]
    met = {"half_hours": int(len(df)), "train": int(len(tr)), "test": int(len(te)), "horizon_h": ENERGY_H / 2,
           "split": "в каждом месяце: первые 75 % получасов — обучение, последние 25 % — тест",
           "mae_mw": round(mean_absolute_error(te["y"], p), 2),
           "mae_now_mw": round(mean_absolute_error(te["y"], te["lag0"]), 2),
           "mae_day_ago_mw": round(mean_absolute_error(te["y"], te["day_ago"]), 2),
           "mean_mw": round(float(df["P_MW"].mean()), 1), "mean_mw_jan": round(float(df[df.month == 1]["P_MW"].mean()), 1),
           "mean_mw_jun": round(float(df[df.month == 6]["P_MW"].mean()), 1),
           "cos_phi": round(float(cosphi.mean()), 3), "load_factor": round(float((daily.mean() / daily.max()).mean()), 3),
           "hour_profile": [round(float(x), 3) for x in (df.groupby(df["minute"] // 60)["P_MW"].mean() / df["P_MW"].mean())]}
    model = export_gbm(m, ENERGY_FEATS, "regression", exact=True)
    model["f32"] = True
    check_parity(model, m, te[ENERGY_FEATS].values[:200], ENERGY_FEATS)
    model["metrics"] = met
    model["horizon"] = ENERGY_H
    model["lags"] = ENERGY_LAGS
    save("energy_load", model)
    return met


MWD_BASE = ["PenetrNorm", "PenetrRMS", "RotaPressNorm", "RotaPressRMS", "FeedPressNorm", "HammerPressNorm",
            "WaterFlowNorm", "WaterFlowRMS"]
MWD_FEATS = [f"{b}{s}" for b in MWD_BASE for s in ("Mean", "Median", "StandardDeviation", "Skewness")]


def mwd_rocktype():
    df = pd.read_csv(os.path.join(DATA, "mwd-rocktype", "mwd_rocktype_blastholes_model_ready_full.csv"), index_col=0)
    df = df.sort_values(["Tunnel", "PegStart"]).reset_index(drop=True)
    pos = df.groupby("Tunnel").cumcount() / df.groupby("Tunnel")["PegStart"].transform("count")
    test = (pos >= 0.75).values
    tr, te = df[~test], df[test]
    m = GradientBoostingClassifier(n_estimators=120, max_depth=3, learning_rate=0.08, subsample=0.8, random_state=SEED)
    m.fit(tr[MWD_FEATS].values, tr["Rock"].values)
    proba = m.predict_proba(te[MWD_FEATS].values)
    pred = m.classes_[proba.argmax(1)]
    prev = df.groupby("Tunnel")["Rock"].shift(1)[te.index]
    change = (prev != te["Rock"]).values
    # change alarm: the model's rock differs from the last mapped one with confidence >= thr
    conf = proba.max(1)
    best = None
    for thr in np.arange(0.4, 0.95, 0.05):
        alarm = (pred != prev.values) & (conf >= thr)
        tp = int((alarm & change).sum())
        prec = tp / max(1, alarm.sum())
        rec = tp / max(1, change.sum())
        f = 2 * prec * rec / max(1e-9, prec + rec)
        if best is None or f > best[0]:
            best = (f, float(thr), prec, rec, int(alarm.sum()))
    met = {"rounds": int(len(df)), "tunnels": int(df["Tunnel"].nunique()), "classes": int(df["Rock"].nunique()),
           "train": int(len(tr)), "test": int(len(te)),
           "split": "в каждом тоннеле: первые 75 % циклов по пикетажу — обучение, последние 25 % — тест",
           "accuracy": round(accuracy_score(te["Rock"], pred), 3), "f1_macro": round(f1_score(te["Rock"], pred, average="macro"), 3),
           "accuracy_majority": round(float((te["Rock"] == tr["Rock"].mode()[0]).mean()), 3),
           "accuracy_previous_round": round(float((prev == te["Rock"]).mean()), 3),
           "rock_changes_test": int(change.sum()),
           "accuracy_on_changes": round(float((pred[change] == te["Rock"].values[change]).mean()), 3),
           "change_alarm_threshold": round(best[1], 2), "change_alarm_precision": round(best[2], 3),
           "change_alarm_recall": round(best[3], 3), "change_alarm_count": best[4]}
    model = export_gbm_multi(m, MWD_FEATS)
    sys.path.insert(0, ROOT)
    from sim import ml as rt
    got = np.array([rt.gbm_proba(model, dict(zip(MWD_FEATS, row))) for row in te[MWD_FEATS].values[:150]])
    print("parity max diff", np.abs(got - proba[:150]).max())
    assert np.abs(got - proba[:150]).max() < 1e-3, "pure-Python multiclass GBM differs from scikit-learn"
    model["metrics"] = met
    model["test_from"] = {t: float(g["PegStart"].iloc[int(len(g) * 0.75)]) for t, g in df.groupby("Tunnel")}
    save("mwd_rocktype", model)
    return met


def _swebrec(x, x50, xmax, b):
    return 1.0 / (1.0 + (np.log(xmax / x) / np.log(xmax / x50)) ** b)


def fragmentation_ref():
    from scipy.optimize import curve_fit
    out = {}
    folder = os.path.join(DATA, "fragmentation")
    for name in sorted(os.listdir(folder)):
        if not name.startswith("MSA_") or not name.endswith(".txt"):
            continue
        arr = np.loadtxt(os.path.join(folder, name), delimiter=",")
        x, P = arr[:, 0], arr[:, 1]
        rr = lambda x, x50, n: 1 - np.exp(-np.log(2) * (x / x50) ** n)
        (x50, n), _ = curve_fit(rr, x, P, p0=[np.interp(0.5, P, x), 1.2])
        rmse_rr = float(np.sqrt(np.mean((rr(x, x50, n) - P) ** 2)))
        xmax = float(x.max()) * 1.02
        (sx50, sb), _ = curve_fit(lambda x, a, b: _swebrec(x, a, xmax, b), x, P, p0=[x50, 2.0], bounds=([x.min(), 0.3], [xmax * 0.99, 10]))
        rmse_sw = float(np.sqrt(np.mean((_swebrec(x, sx50, xmax, sb) - P) ** 2)))
        out[name[:-4]] = {
            "x50_mm_measured": round(float(np.interp(0.5, P, x)), 1), "x80_mm_measured": round(float(np.interp(0.8, P, x)), 1),
            "xmax_mm": round(float(x.max()), 1),
            "rr_x50_mm": round(float(x50), 1), "rr_n": round(float(n), 3), "rr_rmse": round(rmse_rr, 4),
            "swebrec_x50_mm": round(float(sx50), 1), "swebrec_b": round(float(sb), 3), "swebrec_rmse": round(rmse_sw, 4),
            "curve": [[round(float(a), 1), round(float(b), 4)] for a, b in zip(x[::3], P[::3])],
        }
    save("fragmentation_ref", {"type": "reference", "blasts": out})
    return {k: {kk: vv for kk, vv in v.items() if kk != "curve"} for k, v in out.items()}


def main():
    report = {"flotation_silica": flotation(), "geomet_grid": geomet_grid()}
    hard, report["geomet_hardness"] = ridge_on_assays("comminution.csv", "th3")
    save("geomet_hardness", hard)
    rec, report["geomet_recovery"] = ridge_on_assays("flotation.csv", "LCT")
    save("geomet_recovery", rec)
    report["seismic_hazard"] = seismic()
    report["mwd_rocktype"] = mwd_rocktype()
    report["energy_load"] = energy_load()
    report["fragmentation_ref"] = fragmentation_ref()
    with open(os.path.join(OUT, "metrics.json"), "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
