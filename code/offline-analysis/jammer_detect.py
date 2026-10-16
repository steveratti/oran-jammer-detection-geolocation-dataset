#!/usr/bin/env python3
"""
Jammer detection and localisation from L3 SINR + UE positions (offline).

Fixes w.r.t. the original gnb3.py / gnb5.py scripts:
  * no UE-ID remapping hacks (the IMSI bug is fixed in the ns-3 scenario);
  * SINR and positions are aligned on the SAME clock (simulation time);
  * victims follow Algorithm 1 exactly (score >= delta AND SINR < gamma_severe);
  * the jammer estimate is taken from the LARGEST cluster (never from the
    cluster closest to the ground truth);
  * "no jammer" is returned when too few distinct UEs are affected;
  * every run appends one row per method to a summary CSV (Monte Carlo ready).

Sub-commands
  analyze    analyse one run directory (one or several methods)
  summarize  aggregate the summary CSV of a whole campaign

Files expected in a run directory (written by jammer_scenario.cc):
  ue_position.txt     timestamp,id,x,y,type,cell,simid   (every 100 ms)
  MmWaveSinrTime.txt  <time_s> <imsi> <cellId> <sinr_dB> (L3 SINR, every cell)
  jammer.txt          x,y,z,power_dbm,jammer_on,rng_run  (ground truth)

Example
  python3 jammer_detect.py analyze --run-dir runs/p60_on1_r1 --methods sdbscan htdbscan centroid \
          --summary-csv results/summary.csv --plot
  python3 jammer_detect.py summarize --summary-csv results/summary.csv
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import least_squares, minimize
from sklearn.cluster import DBSCAN

try:  # the stand-alone hdbscan package (used in the original scripts)
    import hdbscan as _hdbscan_pkg

    def _hdbscan(min_cluster_size, min_samples):
        return _hdbscan_pkg.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples)
except ImportError:  # fall back to scikit-learn >= 1.3
    from sklearn.cluster import HDBSCAN as _SkHDBSCAN

    def _hdbscan(min_cluster_size, min_samples):
        return _SkHDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples)

GNB_POSITIONS = {2: (500.0, 500.0), 3: (700.0, 500.0), 4: (400.0, 673.205), 5: (400.0, 326.795)}


# ----------------------------------------------------------------------------
# Loading and time alignment
# ----------------------------------------------------------------------------
def load_positions(path):
    """UE positions on the simulation clock (t_ms = timestamp - simid)."""
    pos = pd.read_csv(path)
    pos = pos.rename(columns={"id": "ue_id", "cell": "serving_cell"})
    for c in ["timestamp", "ue_id", "x", "y", "serving_cell", "simid"]:
        pos[c] = pd.to_numeric(pos[c], errors="coerce")
    pos = pos.dropna(subset=["timestamp", "ue_id", "x", "y", "simid"])
    pos["t_ms"] = (pos["timestamp"] - pos["simid"]).astype("int64")
    pos["ue_id"] = pos["ue_id"].astype(int)
    pos["serving_cell"] = pos["serving_cell"].fillna(0).astype(int)
    return pos[["t_ms", "ue_id", "x", "y", "serving_cell"]].sort_values("t_ms")


def load_estimated_positions(path):
    """Optional SI-MAP/EKF trajectory: CSV with columns t_ms,ue_id,x,y."""
    est = pd.read_csv(path)
    missing = {"t_ms", "ue_id", "x", "y"} - set(est.columns)
    if missing:
        sys.exit(f"Estimated-position file needs columns t_ms,ue_id,x,y (missing {missing})")
    est["ue_id"] = est["ue_id"].astype(int)
    return est[["t_ms", "ue_id", "x", "y"]].sort_values("t_ms")


def load_sinr_trace(path):
    """MmWaveSinrTime.txt -> t_ms, ue_id, cell, sinr_db (simulation clock)."""
    s = pd.read_csv(path, sep=r"\s+", header=None, names=["t_s", "ue_id", "cell", "sinr_db"],
                    engine="c", on_bad_lines="skip")
    for c in s.columns:
        s[c] = pd.to_numeric(s[c], errors="coerce")
    s = s.dropna()
    s["t_ms"] = np.round(s["t_s"] * 1000.0).astype("int64")
    s["ue_id"] = s["ue_id"].astype(int)
    s["cell"] = s["cell"].astype(int)
    return s[["t_ms", "ue_id", "cell", "sinr_db"]].sort_values("t_ms")


def build_serving_samples(pos, sinr, tolerance_ms, mode="best"):
    if mode == "best":
        return build_best_cell_samples(pos, sinr, tolerance_ms)
    return build_serving_cell_samples(pos, sinr, tolerance_ms)


def build_best_cell_samples(pos, sinr, tolerance_ms):
    """best-cell L3 SINR: for every position snapshot, the highest of the latest L3 SINR
    values towards all mmWave cells (serving + neighbours). Keeps UEs that fell back to
    LTE (serving cell 0) and is not biased by a UE attached to a distant cell."""
    p = pos.sort_values("t_ms").copy()
    cols = []
    for c in sorted(sinr["cell"].unique()):
        sc = sinr[sinr["cell"] == c][["t_ms", "ue_id", "sinr_db"]].rename(columns={"sinr_db": f"s{c}"})
        p = pd.merge_asof(p.sort_values("t_ms"), sc.sort_values("t_ms"), on="t_ms", by="ue_id",
                          direction="backward", tolerance=tolerance_ms)
        cols.append(f"s{c}")
    p["sinr_db"] = p[cols].max(axis=1)
    n0 = len(p)
    p = p.dropna(subset=["sinr_db"]).drop(columns=cols)
    return p.sort_values(["t_ms", "ue_id"]).reset_index(drop=True), n0 - len(p)


def build_serving_cell_samples(pos, sinr, tolerance_ms):
    """One serving-cell L3 SINR sample per UE and per position snapshot.

    For every position snapshot (t, UE, serving cell) take the most recent
    SINR value of that UE towards its serving cell, at most `tolerance_ms` old.
    """
    p = pos[pos["serving_cell"] > 0].rename(columns={"serving_cell": "cell"})
    merged = pd.merge_asof(p.sort_values("t_ms"), sinr.sort_values("t_ms"), on="t_ms",
                           by=["ue_id", "cell"], direction="backward", tolerance=tolerance_ms)
    n0 = len(merged)
    merged = merged.dropna(subset=["sinr_db"])
    return merged.sort_values(["t_ms", "ue_id"]).reset_index(drop=True), n0 - len(merged)


def load_ground_truth(run_dir, args):
    gt = {"x": None, "y": None, "jammer_on": None, "power_dbm": None, "rng_run": None}
    path = os.path.join(run_dir, "jammer.txt")
    if os.path.exists(path):
        row = pd.read_csv(path).iloc[0]
        gt.update(x=float(row["x"]), y=float(row["y"]), jammer_on=int(row["jammer_on"]),
                  power_dbm=float(row["power_dbm"]), rng_run=int(row["rng_run"]))
    if args.true_pos is not None:
        gt["x"], gt["y"] = args.true_pos
    if args.jammer_on is not None:
        gt["jammer_on"] = args.jammer_on
    return gt


# ----------------------------------------------------------------------------
# Victim identification
# ----------------------------------------------------------------------------
def stateful_victims(df, g_detect, g_severe, alpha, beta, delta):
    """Algorithm 1, stage 1: per-UE suspicion score with hysteresis."""
    score = {}
    is_victim = np.zeros(len(df), dtype=bool)
    for i, (u, g) in enumerate(zip(df["ue_id"].to_numpy(), df["sinr_db"].to_numpy())):
        s = score.get(u, 0.0)
        s = s + alpha if g < g_detect else max(0.0, s - beta)
        score[u] = s
        is_victim[i] = (s >= delta) and (g < g_severe)
    return df[is_victim]


def threshold_victims(df, g_th):
    """HT-HDBSCAN stage 1: stateless hard threshold."""
    return df[df["sinr_db"] < g_th]


def dedup_per_ue(victims, window_ms):
    """Keep at most one victim event per UE per time window (removes dwell-time bias)."""
    if window_ms <= 0 or victims.empty:
        return victims
    v = victims.copy()
    v["win"] = v["t_ms"] // window_ms
    v = v.sort_values("sinr_db").groupby(["ue_id", "win"], as_index=False).first()
    return v.drop(columns="win")


# ----------------------------------------------------------------------------
# Localisation
# ----------------------------------------------------------------------------
def largest_cluster(labels):
    valid = labels[labels >= 0]
    if valid.size == 0:
        return None
    return pd.Series(valid).value_counts().idxmax()


def localise_sdbscan(victims, eps, min_pts, trim_pct):
    pts = victims[["x", "y"]].to_numpy()
    labels = DBSCAN(eps=eps, min_samples=min_pts).fit_predict(pts)
    k = largest_cluster(labels)
    if k is None:
        return None, {"clusters": {}}
    c = victims[labels == k]
    xy, g = c[["x", "y"]].to_numpy(), c["sinr_db"].to_numpy()
    w = (g.max() - g + 1.0) ** 2
    rough = np.average(xy, axis=0, weights=w)
    d = np.hypot(xy[:, 0] - rough[0], xy[:, 1] - rough[1])
    keep = d <= np.percentile(d, trim_pct)
    xy2, g2 = xy[keep], g[keep]
    w2 = (g2.max() - g2 + 1.0) ** 2
    est = np.average(xy2, axis=0, weights=w2)
    sizes = pd.Series(labels).value_counts().to_dict()
    return tuple(est), {"clusters": {int(a): int(b) for a, b in sizes.items()},
                        "cluster_ues": sorted(c["ue_id"].unique().tolist())}


def localise_hdbscan(victims, min_cluster_size, min_samples):
    pts = victims[["x", "y"]].to_numpy()
    if len(pts) < max(min_cluster_size, min_samples):
        return None, {"clusters": {}}
    labels = _hdbscan(min_cluster_size, min_samples).fit_predict(pts)
    k = largest_cluster(labels)
    if k is None:
        return None, {"clusters": {}}
    c = victims[labels == k]
    est = np.median(c[["x", "y"]].to_numpy(), axis=0)
    sizes = pd.Series(labels).value_counts().to_dict()
    return tuple(est), {"clusters": {int(a): int(b) for a, b in sizes.items()},
                        "cluster_ues": sorted(c["ue_id"].unique().tolist())}


def localise_centroid(victims):
    """Baseline: plain centroid of all victim events (no clustering, no weights)."""
    return tuple(victims[["x", "y"]].mean().to_numpy()), {}


def localise_min_sinr(victims):
    """Baseline: position of the single most degraded sample."""
    r = victims.loc[victims["sinr_db"].idxmin()]
    return (float(r["x"]), float(r["y"])), {}


# ----------------------------------------------------------------------------
# Interference-power trilateration (uses RSRP + SINR, file MmWaveJammerRx.txt)
# ----------------------------------------------------------------------------
def load_jammer_rx(path):
    # MmWaveJammerRx.txt: time_s imsi cellId S_dBm J_dBm N_dBm sinr_dB (written by the ns-3 patch)
    rx = pd.read_csv(path, sep=" ")
    rx = rx.apply(pd.to_numeric, errors="coerce").dropna(subset=["time_s", "imsi", "S_dBm", "N_dBm", "sinr_dB"])
    rx["t_ms"] = np.round(rx["time_s"] * 1000.0).astype("int64")
    rx["ue_id"] = rx["imsi"].astype(int)
    return rx.sort_values("t_ms")


def estimate_interference(rx, rsrp_err_db, sinr_err_db, seed):
    # J_est = S/SINR - N from OBSERVABLE quantities only (RSRP-like S, L3 SINR, known noise floor).
    # Gaussian measurement errors (dB) are added to S and SINR to mimic real UE reports.
    # The true J column written by the simulator is never used.
    rng = np.random.default_rng(seed)
    s_obs = rx["S_dBm"].to_numpy() + rng.normal(0.0, rsrp_err_db, len(rx))
    g_obs = rx["sinr_dB"].to_numpy() + rng.normal(0.0, sinr_err_db, len(rx))
    n_lin = 10 ** (rx["N_dBm"].to_numpy() / 10)
    j_lin = 10 ** ((s_obs - g_obs) / 10) - n_lin
    out = rx[["t_ms", "ue_id"]].copy()
    out["j_lin"] = np.maximum(j_lin, 1e-30)
    out["n_lin"] = n_lin
    # one value per UE and report instant: median over the cells (J does not depend on the cell)
    out = out.groupby(["t_ms", "ue_id"], as_index=False).median()
    out["J_dBm"] = 10 * np.log10(out["j_lin"])
    out["INR_dB"] = 10 * np.log10(out["j_lin"] / out["n_lin"])
    return out


def localise_jtrilat(rx, pos, a):
    j = estimate_interference(rx, a.rsrp_err_db, a.sinr_err_db, getattr(a, "noise_seed_eff", a.noise_seed))
    j = pd.merge_asof(j.sort_values("t_ms"), pos[["t_ms", "ue_id", "x", "y"]].sort_values("t_ms"),
                      on="t_ms", by="ue_id", direction="backward", tolerance=a.tolerance_ms).dropna(subset=["x", "y"])
    # one robust value per UE and time window (removes dwell-time weighting)
    j["win"] = j["t_ms"] // max(a.jt_window_ms, 1)
    w = j.groupby(["ue_id", "win"], as_index=False).agg(x=("x", "mean"), y=("y", "mean"),
                                                         J_dBm=("J_dBm", "median"), INR_dB=("INR_dB", "median"))
    hit = w[w["INR_dB"] >= a.inr_th]
    info = {"n_victim_events": int(len(hit)), "n_victim_ues": int(hit["ue_id"].nunique()),
            "victim_ues": sorted(hit["ue_id"].unique().tolist())}
    t0w = int(j["t_ms"].min()) if len(j) else 0
    hit_t = hit.assign(t_ms=(hit["win"] + 1) * a.jt_window_ms)
    info["detect_time_ms"] = first_alarm_ms(hit_t, a.min_victim_ues, 4, t0w)
    info["n_windows"] = int(w["win"].nunique())
    info["alarm_windows"] = int((hit.groupby("win")["ue_id"].nunique() >= a.min_victim_ues).sum()) if len(hit) else 0
    if info["n_victim_ues"] < a.min_victim_ues or len(hit) < 4:
        return None, info
    xy = hit[["x", "y"]].to_numpy()
    jd = hit["J_dBm"].to_numpy()

    def resid(th):
        x0, y0, q, n = th
        d = np.maximum(np.hypot(xy[:, 0] - x0, xy[:, 1] - y0), 1.0)
        return jd - (q - 10.0 * n * np.log10(d))

    # coarse-to-fine multistart: screen the 7x7 grid with a cheap closed-form robust
    # cost, then refine only the few best seeds with least_squares (same basins,
    # ~10x fewer nonlinear fits -> cold start well under 1 s even at 2000 UEs).
    gx, gy = np.meshgrid(np.linspace(50, 950, 7), np.linspace(50, 950, 7))
    seeds = np.column_stack([gx.ravel(), gy.ravel()])
    n0 = 3.0
    scost = np.empty(len(seeds))
    for i, (x0, y0) in enumerate(seeds):
        d0 = np.maximum(np.hypot(xy[:, 0] - x0, xy[:, 1] - y0), 1.0)
        q0 = float(np.median(jd + 10 * n0 * np.log10(d0)))
        z = ((jd - (q0 - 10.0 * n0 * np.log10(d0))) / a.jt_fscale_db) ** 2
        scost[i] = float(np.sum(2.0 * (np.sqrt(1.0 + z) - 1.0)))
    best = None
    for i in np.argsort(scost)[:getattr(a, "jt_n_restarts", 4)]:
        x0, y0 = seeds[int(i)]
        d0 = np.maximum(np.hypot(xy[:, 0] - x0, xy[:, 1] - y0), 1.0)
        q0 = float(np.median(jd + 10 * n0 * np.log10(d0)))
        r = least_squares(resid, [x0, y0, q0, n0], loss="soft_l1", f_scale=a.jt_fscale_db,
                          bounds=([0, 0, -np.inf, 1.5], [a.area_m, a.area_m, np.inf, 5.0]))
        if best is None or r.cost < best.cost:
            best = r
    x0, y0, q, n = best.x
    info.update({"pathloss_exponent": round(float(n), 2), "q_dbm": round(float(q), 1),
                 "fit_rmse_db": round(float(np.sqrt(np.mean(resid(best.x) ** 2))), 2)})
    return (float(x0), float(y0)), info


# ----------------------------------------------------------------------------
# Baseline [26] (Ratti et al., COMSNETS 2025) cross-applied to the jammer
# ----------------------------------------------------------------------------
T26_METHODS = ("t26", "t26kp", "t26oracle")


def localise_t26(rx, pos, a, gt, variant):
    # Path-loss ranging + least-squares trilateration exactly as in [26], but the anchors are the
    # victim UEs (same INR windows as jtrilat) and the transmitter is the jammer:
    #   PL_k = P_jam - J_k ,  d_k = 10^((PL_k - 32.45 - 10 alpha log10(fc)) / (10 alpha))
    #   p = argmin sum_k (|p - u_k| - d_k)^2  (Nelder-Mead from the gNB centroid, as in [26])
    # t26       : fixed alpha (a-priori fit of the [26] model to 3GPP UMi) + ASSUMED jammer power
    # t26kp     : fixed alpha + KNOWN jammer power (oracle power)
    # t26oracle : known power + per-anchor alpha chosen with the TRUE distance, as in the original
    #             [26] script (upper bound only, not realisable)
    j = estimate_interference(rx, a.rsrp_err_db, a.sinr_err_db, getattr(a, "noise_seed_eff", a.noise_seed))
    j = pd.merge_asof(j.sort_values("t_ms"), pos[["t_ms", "ue_id", "x", "y"]].sort_values("t_ms"),
                      on="t_ms", by="ue_id", direction="backward", tolerance=a.tolerance_ms).dropna(subset=["x", "y"])
    j["win"] = j["t_ms"] // max(a.jt_window_ms, 1)
    w = j.groupby(["ue_id", "win"], as_index=False).agg(x=("x", "mean"), y=("y", "mean"),
                                                         J_dBm=("J_dBm", "median"), INR_dB=("INR_dB", "median"))
    hit = w[w["INR_dB"] >= a.inr_th]
    info = {"n_victim_events": int(len(hit)), "n_victim_ues": int(hit["ue_id"].nunique()),
            "victim_ues": sorted(hit["ue_id"].unique().tolist())}
    if info["n_victim_ues"] < a.min_victim_ues or len(hit) < 3:
        return None, info
    xy = hit[["x", "y"]].to_numpy()
    jd = hit["J_dBm"].to_numpy()
    lfc = np.log10(a.t26_fc_ghz)
    known = gt["power_dbm"] if gt["power_dbm"] is not None else a.t26_ptx_dbm
    ptx = a.t26_ptx_dbm if variant == "t26" else known
    pl = ptx - jd
    if variant == "t26oracle" and gt["x"] is not None:
        dtrue = np.maximum(np.hypot(xy[:, 0] - gt["x"], xy[:, 1] - gt["y"]), 1.0)
        alist = np.arange(1.7, 3.8405, 0.001)
        dd = 10 ** ((pl[:, None] - 32.45 - 10 * alist[None, :] * lfc) / (10 * alist[None, :]))
        al = alist[np.argmin(np.abs(dd - dtrue[:, None]), axis=1)]
        anote = "oracle (median " + str(round(float(np.median(al)), 2)) + ")"
    else:
        al = np.full(len(pl), a.t26_alpha)
        anote = str(a.t26_alpha)
    d = np.clip(10 ** ((pl - 32.45 - 10 * al * lfc) / (10 * al)), 1.0, 2.0 * a.area_m)

    def cost(p):
        return float(np.sum((np.hypot(xy[:, 0] - p[0], xy[:, 1] - p[1]) - d) ** 2))

    p0 = np.mean(np.array(list(GNB_POSITIONS.values())), axis=0)
    r = minimize(cost, p0, method="Nelder-Mead", options={"xatol": 0.01, "fatol": 1e-6, "maxiter": 4000})
    info["t26_note"] = ("alpha " + anote + ", jammer power used " + str(round(float(ptx), 1))
                        + " dBm, range rmse " + str(round(float(np.sqrt(cost(r.x) / len(d))), 1)) + " m")
    return (float(r.x[0]), float(r.x[1])), info


# ----------------------------------------------------------------------------
# One run
# ----------------------------------------------------------------------------
def first_alarm_ms(ev, min_ues, min_events, t0):
    # time (from the first report) at which the evidence collected so far first satisfies the alarm rule
    if ev.empty:
        return None
    e = ev.sort_values("t_ms")
    seen = set()
    for k, (t, u) in enumerate(zip(e["t_ms"].to_numpy(), e["ue_id"].to_numpy()), start=1):
        seen.add(int(u))
        if len(seen) >= min_ues and k >= min_events:
            return int(t - t0)
    return None


def window_alarms(ev, all_t_ms, min_ues, win_ms=1000):
    # number of 1 s windows, and number of windows with victims from at least min_ues distinct UEs
    n_win = int(pd.Series(all_t_ms // win_ms).nunique())
    if ev.empty:
        return n_win, 0
    per_w = ev.assign(w=ev["t_ms"] // win_ms).groupby("w")["ue_id"].nunique()
    return n_win, int((per_w >= min_ues).sum())


def run_method(method, df, a):
    if method in ("sdbscan", "centroid", "minsinr"):
        victims = stateful_victims(df, a.g_detect, a.g_severe, a.alpha, a.beta, a.delta)
    elif method == "htdbscan":
        victims = threshold_victims(df, a.g_th)
    else:
        raise ValueError(method)
    victims = dedup_per_ue(victims, a.dedup_ms)
    n_ues = victims["ue_id"].nunique()
    info = {"n_victim_events": int(len(victims)), "n_victim_ues": int(n_ues),
            "victim_ues": sorted(victims["ue_id"].unique().tolist())}
    need = a.min_pts if method == "sdbscan" else (max(a.min_cluster_size, a.min_samples) if method == "htdbscan" else 1)
    info["detect_time_ms"] = first_alarm_ms(victims, a.min_victim_ues, need, int(df["t_ms"].min()))
    info["n_windows"], info["alarm_windows"] = window_alarms(victims, df["t_ms"], a.min_victim_ues)
    if n_ues < a.min_victim_ues or len(victims) == 0:
        return None, info
    if method == "sdbscan":
        if len(victims) < a.min_pts:
            return None, info
        est, extra = localise_sdbscan(victims, a.eps, a.min_pts, a.trim_pct)
    elif method == "htdbscan":
        est, extra = localise_hdbscan(victims, a.min_cluster_size, a.min_samples)
    elif method == "centroid":
        est, extra = localise_centroid(victims)
    else:
        est, extra = localise_min_sinr(victims)
    info.update(extra)
    return est, info


def analyze(a):
    run_dir = a.run_dir
    pos = load_positions(os.path.join(run_dir, "ue_position.txt"))
    gt0 = load_ground_truth(run_dir, a)
    a.noise_seed_eff = int(a.noise_seed if a.noise_seed >= 0 else (gt0["rng_run"] or 0))
    if a.pos_noise_m > 0:  # emulate UE-positioning error (e.g. SI-MAP/EKF, Path B)
        # temporally correlated (first-order Gauss-Markov) error per UE and axis, std pos_noise_m
        rp = np.random.default_rng(10007 + a.noise_seed_eff)
        pos = pos.sort_values(["ue_id", "t_ms"]).reset_index(drop=True)
        ex, ey = np.zeros(len(pos)), np.zeros(len(pos))
        for u, idx in pos.groupby("ue_id").indices.items():
            tt = pos["t_ms"].to_numpy()[idx] / 1000.0
            e = np.zeros((len(idx), 2))
            e[0] = rp.normal(0.0, a.pos_noise_m, 2)
            for k in range(1, len(idx)):
                rho = np.exp(-max(tt[k] - tt[k - 1], 0.0) / a.pos_noise_tau_s)
                e[k] = rho * e[k - 1] + np.sqrt(1.0 - rho * rho) * rp.normal(0.0, a.pos_noise_m, 2)
            ex[idx], ey[idx] = e[:, 0], e[:, 1]
        pos["x"] = pos["x"] + ex
        pos["y"] = pos["y"] + ey
        pos = pos.sort_values("t_ms")
    sinr = load_sinr_trace(os.path.join(run_dir, a.sinr_file))
    df, n_unmatched = build_serving_samples(pos, sinr, a.tolerance_ms, a.sinr_mode)
    if a.est_pos:  # replace ground-truth coordinates with SI-MAP/EKF estimates
        est = load_estimated_positions(a.est_pos)
        df = pd.merge_asof(df.drop(columns=["x", "y"]).sort_values("t_ms"), est, on="t_ms", by="ue_id",
                           direction="backward", tolerance=a.tolerance_ms).dropna(subset=["x", "y"])
    gt = load_ground_truth(run_dir, a)

    print("=" * 78)
    print(f"RUN {run_dir}")
    print(f"  positions : {pos['t_ms'].min()/1000:.1f}-{pos['t_ms'].max()/1000:.1f} s, {pos['ue_id'].nunique()} UEs")
    print(f"  SINR trace: {sinr['t_ms'].min()/1000:.1f}-{sinr['t_ms'].max()/1000:.1f} s, {len(sinr)} rows")
    print(f"  SINR mode: {a.sinr_mode}; merged samples: {len(df)} (unmatched snapshots dropped: {n_unmatched})")
    print(f"  ground truth: jammer_on={gt['jammer_on']} pos=({gt['x']}, {gt['y']}) "
          f"power={gt['power_dbm']} dBm rng_run={gt['rng_run']}")
    if len(df) == 0:
        sys.exit("No samples after alignment - check that both files come from the same run.")

    stats = df.groupby("ue_id")["sinr_db"].agg(["count", "min", "mean", "std"]).round(2)
    print(f"\n  Per-UE {a.sinr_mode} L3 SINR (dB)")
    print(stats.to_string())

    rx = None
    if any(m in a.methods for m in ("jtrilat",) + T26_METHODS):
        rx_path = os.path.join(run_dir, "MmWaveJammerRx.txt")
        if os.path.exists(rx_path):
            rx = load_jammer_rx(rx_path)
        else:
            print("  (no " + rx_path + ": method jtrilat skipped - rebuild ns-3 with the RSRP logging patch)")
    rows = []
    for m in a.methods:
        if m == "jtrilat":
            if rx is None:
                continue
            est, info = localise_jtrilat(rx, pos if not a.est_pos else df[["t_ms", "ue_id", "x", "y"]], a)
        elif m in T26_METHODS:
            if rx is None:
                continue
            est, info = localise_t26(rx, pos if not a.est_pos else df[["t_ms", "ue_id", "x", "y"]], a, gt, m)
        else:
            est, info = run_method(m, df, a)
        detected = est is not None
        err = None
        if detected and gt["x"] is not None:
            err = float(np.hypot(est[0] - gt["x"], est[1] - gt["y"]))
        nearest_gnb = None
        if detected:
            nearest_gnb = min(GNB_POSITIONS, key=lambda g: np.hypot(est[0] - GNB_POSITIONS[g][0],
                                                                     est[1] - GNB_POSITIONS[g][1]))
        row = {"run_dir": run_dir, "rng_run": gt["rng_run"], "jammer_on": gt["jammer_on"],
               "power_dbm": gt["power_dbm"], "true_x": gt["x"], "true_y": gt["y"], "method": m,
               "detected": int(detected), "est_x": None if not detected else round(est[0], 2),
               "est_y": None if not detected else round(est[1], 2),
               "error_m": None if err is None else round(err, 2), "nearest_gnb": nearest_gnb,
               "n_samples": len(df), "n_victim_events": info["n_victim_events"],
               "n_victim_ues": info["n_victim_ues"], "victim_ues": json.dumps(info["victim_ues"]),
               "clusters": json.dumps(info.get("clusters", {})),
               "detect_time_ms": info.get("detect_time_ms"), "n_windows": info.get("n_windows"),
               "alarm_windows": info.get("alarm_windows"), "pos_noise_m": a.pos_noise_m,
               "noise_seed": getattr(a, "noise_seed_eff", a.noise_seed)}
        rows.append(row)
        print(f"\n  [{m}] victims: {info['n_victim_ues']} UEs {info['victim_ues']}, "
              f"{info['n_victim_events']} events; clusters (label:size, -1=noise): {info.get('clusters', {})}")
        if "pathloss_exponent" in info:
            print("  [" + m + "] fit: path-loss exponent " + str(info["pathloss_exponent"])
                  + ", rmse " + str(info["fit_rmse_db"]) + " dB")
        if info.get("detect_time_ms") is not None:
            print("  [" + m + "] first alarm after " + str(info["detect_time_ms"]) + " ms; alarm windows "
                  + str(info.get("alarm_windows")) + "/" + str(info.get("n_windows")))
        if "t26_note" in info:
            print("  [" + m + "] [26] model: " + info["t26_note"])
        if detected:
            e = "" if err is None else f", error {err:.2f} m"
            print(f"  [{m}] jammer estimate ({est[0]:.1f}, {est[1]:.1f}){e}, nearest gNB {nearest_gnb}")
        else:
            print(f"  [{m}] NO JAMMER declared")
        if gt["jammer_on"] == 0 and detected:
            print(f"  [{m}] !!! FALSE ALARM (jammer was OFF)")

    if a.summary_csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.summary_csv)), exist_ok=True)
        out = pd.DataFrame(rows)
        out.to_csv(a.summary_csv, mode="a", index=False, header=not os.path.exists(a.summary_csv))
        print(f"\n  -> appended {len(rows)} row(s) to {a.summary_csv}")
    if a.plot:
        plot_run(df, rows, gt, a, os.path.join(run_dir, "jammer_map.png"))


def plot_run(df, rows, gt, a, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    victims = stateful_victims(df, a.g_detect, a.g_severe, a.alpha, a.beta, a.delta)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(df["x"], df["y"], s=3, c="#9aa5b1", alpha=0.3, label="UE samples")
    ax.scatter(victims["x"], victims["y"], s=8, c="#d97706", label="victim events (Alg. 1)")
    for g, (x, y) in GNB_POSITIONS.items():
        ax.scatter(x, y, marker="^", s=150, c="black")
        ax.annotate(f"gNB {g}", (x, y), textcoords="offset points", xytext=(0, 10), ha="center")
    if gt["x"] is not None and gt["jammer_on"]:
        ax.scatter(gt["x"], gt["y"], marker="*", s=350, c="#7c3aed", label="true jammer")
    markers = {"sdbscan": "X", "htdbscan": "P", "centroid": "o", "minsinr": "D"}
    for r in rows:
        if r["detected"]:
            ax.scatter(r["est_x"], r["est_y"], marker=markers.get(r["method"], "x"), s=160,
                       edgecolor="black", label=f"{r['method']} estimate")
    ax.set_xlim(0, 1000); ax.set_ylim(0, 1000); ax.set_aspect("equal")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)"); ax.grid(ls=":")
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    print(f"  -> map saved to {path}")


# ----------------------------------------------------------------------------
# Campaign summary
# ----------------------------------------------------------------------------
def _parse_seeds(txt):
    out = set()
    for part in txt.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-")
            out.update(range(int(lo), int(hi) + 1))
        elif part:
            out.add(int(part))
    return out


def _boot_ci(x, rng, n=2000):
    x = np.asarray(x, float)
    if len(x) < 2:
        return None, None
    m = np.median(rng.choice(x, (n, len(x)), replace=True), axis=1)
    return round(float(np.percentile(m, 2.5)), 2), round(float(np.percentile(m, 97.5)), 2)


def summarize(a):
    s = pd.read_csv(a.summary_csv)
    if a.seeds:
        keep = _parse_seeds(a.seeds)
        s = s[s["rng_run"].isin(keep)]
        print("seeds used: " + str(sorted(int(x) for x in s["rng_run"].unique())))
    ok_gnbs = [int(g) for g in a.sector_ok.split(",")] if a.sector_ok else None
    keys = ["power_dbm", "method"] + (["pos_noise_m"] if "pos_noise_m" in s.columns else [])
    rng = np.random.default_rng(0)
    out = []
    for key, g in s.groupby(keys, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        on, off = g[g["jammer_on"] == 1], g[g["jammer_on"] == 0]
        det = on[on["detected"] == 1]
        errs = det["error_m"].dropna()
        lo, hi = _boot_ci(errs, rng)
        r = dict(zip(keys, key))
        r.update({"runs_on": len(on), "runs_off": len(off),
                  "detection_rate": round(on["detected"].mean(), 3) if len(on) else None,
                  "false_alarm_rate": round(off["detected"].mean(), 3) if len(off) else None,
                  "err_median_m": round(errs.median(), 2) if len(errs) else None,
                  "err_median_ci95": ("[" + str(lo) + ", " + str(hi) + "]") if lo is not None else None,
                  "err_mean_m": round(errs.mean(), 2) if len(errs) else None,
                  "err_p90_m": round(errs.quantile(0.9), 2) if len(errs) else None})
        if ok_gnbs is not None:
            r["sector_correct"] = round(det["nearest_gnb"].isin(ok_gnbs).mean(), 3) if len(det) else None
        if "n_windows" in g.columns:
            if len(off) and off["n_windows"].fillna(0).sum() > 0:
                r["fa_rate_per_window"] = round(off["alarm_windows"].fillna(0).sum() / off["n_windows"].fillna(0).sum(), 4)
                r["windows_off"] = int(off["n_windows"].fillna(0).sum())
            if len(on) and on["n_windows"].fillna(0).sum() > 0:
                r["det_prob_per_window"] = round(on["alarm_windows"].fillna(0).sum() / on["n_windows"].fillna(0).sum(), 3)
        if "detect_time_ms" in g.columns:
            dt = det["detect_time_ms"].dropna()
            r["detect_time_median_ms"] = round(float(dt.median()), 1) if len(dt) else None
        r["victim_ues_mean_on"] = round(on["n_victim_ues"].mean(), 2) if len(on) else None
        r["victim_ues_mean_off"] = round(off["n_victim_ues"].mean(), 2) if len(off) else None
        out.append(r)
    res = pd.DataFrame(out)
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(res.to_string(index=False))
    if a.out:
        res.to_csv(a.out, index=False)
        print("-> " + a.out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    an = sub.add_parser("analyze", help="analyse one run directory")
    an.add_argument("--run-dir", required=True)
    an.add_argument("--sinr-file", default="MmWaveSinrTime.txt")
    an.add_argument("--est-pos", default=None, help="optional SI-MAP/EKF CSV (t_ms,ue_id,x,y)")
    an.add_argument("--methods", nargs="+", default=["sdbscan", "htdbscan", "centroid"],
                    choices=["sdbscan", "htdbscan", "centroid", "minsinr", "jtrilat", "t26", "t26kp", "t26oracle"])
    an.add_argument("--tolerance-ms", type=int, default=100, help="max age of the SINR sample")
    an.add_argument("--sinr-mode", choices=["best", "serving"], default="best",
                    help="best = best-cell L3 SINR (default); serving = serving-cell L3 SINR only")
    an.add_argument("--true-pos", type=float, nargs=2, default=None, help="override jammer.txt")
    an.add_argument("--jammer-on", type=int, choices=[0, 1], default=None, help="override jammer.txt")
    # Algorithm 1 (S-DBSCAN)
    an.add_argument("--g-detect", type=float, default=-5.0)
    an.add_argument("--g-severe", type=float, default=-12.0)
    an.add_argument("--alpha", type=float, default=5.0)
    an.add_argument("--beta", type=float, default=1.0)
    an.add_argument("--delta", type=float, default=15.0,
                    help="suspicion limit; 15 = three consecutive bad samples (paper used 5)")
    an.add_argument("--eps", type=float, default=400.0)
    an.add_argument("--min-pts", type=int, default=6)
    an.add_argument("--trim-pct", type=float, default=75.0)
    # Algorithm 2 (HT-HDBSCAN)
    an.add_argument("--g-th", type=float, default=-20.0)
    an.add_argument("--min-cluster-size", type=int, default=3)
    an.add_argument("--min-samples", type=int, default=2)
    # common
    an.add_argument("--min-victim-ues", type=int, default=2,
                    help="declare a jammer only if at least this many distinct UEs are victims")
    an.add_argument("--dedup-ms", type=int, default=0,
                    help="keep one victim event per UE per window (0 = off)")
    # interference-power trilateration (jtrilat)
    an.add_argument("--rsrp-err-db", type=float, default=2.0, help="std of RSRP measurement error [dB]")
    an.add_argument("--sinr-err-db", type=float, default=1.0, help="std of SINR measurement error [dB]")
    an.add_argument("--noise-seed", type=int, default=-1,
                    help="seed of the measurement-error generator (-1 = use the run seed)")
    an.add_argument("--pos-noise-m", type=float, default=0.0,
                    help="per-axis std of a correlated error added to the UE positions [m] (e.g. 15 for SI-MAP/EKF)")
    an.add_argument("--pos-noise-tau-s", type=float, default=10.0,
                    help="correlation time of the UE-position error [s]")
    an.add_argument("--inr-th", type=float, default=6.0,
                    help="interference-to-noise ratio [dB] above which a UE sample counts as interfered")
    an.add_argument("--jt-window-ms", type=int, default=1000, help="averaging window per UE [ms]")
    an.add_argument("--jt-fscale-db", type=float, default=6.0, help="robust-loss scale [dB]")
    an.add_argument("--jt-n-restarts", type=int, default=4,
                    help="best grid seeds refined with least_squares (coarse-to-fine cold start)")
    an.add_argument("--area-m", type=float, default=1000.0, help="side of the square scenario area [m]")
    # baseline [26]: path-loss ranging + LS trilateration
    an.add_argument("--t26-alpha", type=float, default=2.65,
                    help="[26] path-loss coefficient; 2.65 = LS fit of the [26] model to 3GPP UMi (10-600 m), no test data")
    an.add_argument("--t26-ptx-dbm", type=float, default=50.0,
                    help="jammer power ASSUMED by method t26 (unknown to the defender)")
    an.add_argument("--t26-fc-ghz", type=float, default=3.5, help="carrier frequency of the scenario [GHz]")
    an.add_argument("--summary-csv", default=None)
    an.add_argument("--plot", action="store_true")

    sm = sub.add_parser("summarize", help="aggregate a campaign summary CSV")
    sm.add_argument("--summary-csv", required=True)
    sm.add_argument("--out", default=None)
    sm.add_argument("--seeds", default=None, help="seeds to report, e.g. 6-30 (test seeds) or 1-5")
    sm.add_argument("--sector-ok", default=None, help="correct nearest gNB(s), e.g. 3 or 5,2")

    a = ap.parse_args()
    analyze(a) if a.cmd == "analyze" else summarize(a)


if __name__ == "__main__":
    main()
