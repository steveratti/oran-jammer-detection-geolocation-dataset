#!/usr/bin/env python3
"""Processing-time / scalability benchmark of the Jammer xApp algorithms (Reviewer 3, comment 4).

For an increasing number of UEs it builds one sliding window of E2 KPM reports (synthetic, same
format as the ns-3 logs), and measures the wall-clock time that each stage of the Jammer xApp
needs to process that window:
  victim detection (stateful thresholds), S-DBSCAN, HT-HDBSCAN, centroid, jtrilat (cold start,
  7x7 multistart as in the offline analysis) and jtrilat (warm start from the previous estimate,
  i.e. the steady-state xApp loop).

Usage:
  python3 latency_bench.py --detect ~/jammer_fix_gnb3/jammer_detect.py --out ~/latency_bench
"""
import argparse, importlib.util, os, time, types
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--detect", default=os.path.expanduser("~/jammer_fix_gnb3/jammer_detect.py"))
ap.add_argument("--out", default=os.path.expanduser("~/latency_bench"))
ap.add_argument("--ues", type=int, nargs="+", default=[10, 25, 50, 100, 250, 500, 1000, 2000])
ap.add_argument("--window-s", type=float, default=5.0, help="sliding window processed per decision")
ap.add_argument("--report-ms", type=int, default=50, help="KPM reporting period (ns-O-RAN indicationPeriodicity = 50 ms)")
ap.add_argument("--repeat", type=int, default=5)
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--plot-only", action="store_true", help="only redraw the figure from the saved CSV")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

spec = importlib.util.spec_from_file_location("jd", a.detect)
jd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jd)
from scipy.optimize import least_squares

# same deployment as the ns-3 scenario
GNB = np.array(list(jd.GNB_POSITIONS.values()))
CELLS = list(jd.GNB_POSITIONS.keys())
FC, PTX, PJ, NOISE = 3.5, 44.0, 50.0, -174 + 10 * np.log10(20e6) + 9
JAM = np.array([710.0, 510.0])


def pl(d, rng):
    d = np.maximum(d, 10.0)
    return 22.4 + 35.3 * np.log10(d) + 21.3 * np.log10(FC) + rng.normal(0, 7.8, d.shape)


def make_window(n_ue, rng):
    """One window of reports: n_ue UEs, random walk, report every report_ms."""
    steps = int(a.window_s * 1000 / a.report_ms)
    start = rng.uniform(0, 1000, (n_ue, 2))
    walk = np.cumsum(rng.normal(0, 0.15, (steps, n_ue, 2)), axis=0)   # ~1.5 m/s
    pos = np.clip(start[None] + walk, 0, 1000)                        # steps x n_ue x 2
    t_ms = (np.arange(steps) * a.report_ms)[:, None].repeat(n_ue, 1)
    ue = np.arange(1, n_ue + 1)[None].repeat(steps, 0)
    p = pos.reshape(-1, 2); tt = t_ms.ravel(); uu = ue.ravel()
    dj = np.hypot(p[:, 0] - JAM[0], p[:, 1] - JAM[1])
    j_dbm = PJ - pl(dj, rng)
    rx_rows, best = [], []
    s_all = []
    for c, g in zip(CELLS, GNB):
        dg = np.hypot(p[:, 0] - g[0], p[:, 1] - g[1])
        s = PTX - pl(dg, rng)
        sinr = s - 10 * np.log10(10 ** (NOISE / 10) + 10 ** (j_dbm / 10))
        s_all.append(sinr)
        rx_rows.append(pd.DataFrame({"time_s": tt / 1000.0, "imsi": uu, "cellId": c, "S_dBm": s,
                                     "J_dBm": j_dbm, "N_dBm": NOISE, "sinr_dB": sinr}))
    best = np.max(np.vstack(s_all), axis=0)
    df = pd.DataFrame({"t_ms": tt, "ue_id": uu, "x": p[:, 0], "y": p[:, 1], "sinr_db": best})
    rx = pd.concat(rx_rows, ignore_index=True)
    rx["t_ms"] = np.round(rx["time_s"] * 1000).astype("int64")
    rx["ue_id"] = rx["imsi"].astype(int)
    pos_df = df[["t_ms", "ue_id", "x", "y"]]
    return df.sort_values("t_ms"), rx.sort_values("t_ms"), pos_df


args = types.SimpleNamespace(g_detect=-5.0, g_severe=-12.0, alpha=5.0, beta=1.0, delta=15.0,
                             eps=400.0, min_pts=6, trim_pct=75.0, g_th=-20.0, min_cluster_size=3,
                             min_samples=2, min_victim_ues=2, dedup_ms=0, rsrp_err_db=2.0,
                             sinr_err_db=1.0, noise_seed=0, inr_th=6.0, jt_window_ms=1000,
                             jt_fscale_db=6.0, area_m=1000.0, tolerance_ms=100)


def jtrilat_warm(rx, pos, x0):
    """Steady-state xApp loop: one robust fit started from the previous estimate."""
    j = jd.estimate_interference(rx, args.rsrp_err_db, args.sinr_err_db, args.noise_seed)
    j = pd.merge_asof(j.sort_values("t_ms"), pos.sort_values("t_ms"), on="t_ms", by="ue_id",
                      direction="backward", tolerance=args.tolerance_ms).dropna(subset=["x", "y"])
    j["win"] = j["t_ms"] // args.jt_window_ms
    w = j.groupby(["ue_id", "win"], as_index=False).agg(x=("x", "mean"), y=("y", "mean"),
                                                         J_dBm=("J_dBm", "median"), INR_dB=("INR_dB", "median"))
    hit = w[w["INR_dB"] >= args.inr_th]
    xy, jdb = hit[["x", "y"]].to_numpy(), hit["J_dBm"].to_numpy()
    if len(hit) < 4:
        return None
    def resid(th):
        d = np.maximum(np.hypot(xy[:, 0] - th[0], xy[:, 1] - th[1]), 1.0)
        return jdb - (th[2] - 10 * th[3] * np.log10(d))
    d0 = np.maximum(np.hypot(xy[:, 0] - x0[0], xy[:, 1] - x0[1]), 1.0)
    q0 = float(np.median(jdb + 30 * np.log10(d0)))
    r = least_squares(resid, [x0[0], x0[1], q0, 3.0], loss="soft_l1", f_scale=args.jt_fscale_db,
                      bounds=([0, 0, -np.inf, 1.5], [args.area_m, args.area_m, np.inf, 5.0]))
    return r.x[:2]


def timed(fn, rep):
    ts = []
    out = None
    for _ in range(rep):
        t0 = time.perf_counter(); out = fn(); ts.append(time.perf_counter() - t0)
    return 1e3 * float(np.median(ts)), out


rng = np.random.default_rng(a.seed)
rows = []
for n in ([] if a.plot_only else a.ues):
    df, rx, pos = make_window(n, rng)
    t_vd, vict = timed(lambda: jd.stateful_victims(df, args.g_detect, args.g_severe, args.alpha,
                                                   args.beta, args.delta), a.repeat)
    t_th, vth = timed(lambda: jd.threshold_victims(df, args.g_th), a.repeat)
    t_sd, est_sd = timed(lambda: jd.run_method("sdbscan", df, args), a.repeat)
    args_dd = types.SimpleNamespace(**{**vars(args), "dedup_ms": 1000})
    t_sdd, est_sdd = timed(lambda: jd.run_method("sdbscan", df, args_dd), a.repeat)
    t_hd, est_hd = timed(lambda: jd.run_method("htdbscan", df, args), a.repeat)
    t_ce, _ = timed(lambda: jd.run_method("centroid", df, args), a.repeat)
    rep_jt = max(1, min(a.repeat, 3 if n <= 500 else 1))
    t_jc, est_jc = timed(lambda: jd.localise_jtrilat(rx, pos, args), rep_jt)
    x0 = est_jc[0] if est_jc[0] is not None else (500.0, 500.0)
    t_jw, _ = timed(lambda: jtrilat_warm(rx, pos, x0), a.repeat)
    err = lambda e: None if (e is None or e[0] is None) else round(float(np.hypot(e[0][0] - JAM[0], e[0][1] - JAM[1])), 1)
    row = {"n_ue": n, "reports_in_window": len(df), "rx_rows": len(rx),
           "victim_detection_ms": round(t_vd, 3), "sdbscan_total_ms": round(t_sd, 3), "sdbscan_dedup1s_ms": round(t_sdd, 3),
           "htdbscan_total_ms": round(t_hd, 3), "centroid_total_ms": round(t_ce, 3),
           "jtrilat_cold_ms": round(t_jc, 2), "jtrilat_warm_ms": round(t_jw, 3),
           "err_sdbscan_m": err(est_sd), "err_sdbscan_dedup_m": err(est_sdd), "err_jtrilat_m": err(est_jc)}
    rows.append(row)
    print(row, flush=True)

if a.plot_only:
    res = pd.read_csv(os.path.join(a.out, "latency_scalability.csv"))
else:
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(a.out, "latency_scalability.csv"), index=False)
print("\n-> " + os.path.join(a.out, "latency_scalability.csv"))

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    series = [("victim_detection_ms", "Victim detection (stateful)", "o"),
              ("sdbscan_total_ms", "S-DBSCAN (detection + clustering)", "s"),
              ("sdbscan_dedup1s_ms", "S-DBSCAN, 1 event/UE/s", "P"),
              ("htdbscan_total_ms", "HT-HDBSCAN", "^"),
              ("jtrilat_warm_ms", "jtrilat, warm start (steady state)", "D"),
              ("jtrilat_cold_ms", "jtrilat, cold start", "v")]
    for col, lab, m in series:
        ax.plot(res["n_ue"], res[col], marker=m, label=lab)
    ax.axhline(1000, color="red", ls="--", lw=1.5)
    ax.text(res["n_ue"].max(), 1150, "Near-RT RIC control-loop limit (1 s)", color="red", fontsize=9, ha="right")
    ax.axhline(a.report_ms, color="gray", ls=":", lw=1.2)
    ax.text(res["n_ue"].min(), a.report_ms * 1.15, "KPM reporting period (%d ms)" % a.report_ms, color="dimgray", fontsize=9)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_ylim(0.1, 3000)
    ax.set_xlabel("Number of UEs"); ax.set_ylabel("Processing time per decision (ms)")
    ax.set_title("Jammer xApp processing time (window %.0f s)" % a.window_s, fontsize=10)
    ax.grid(True, which="both", alpha=0.3); ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(a.out, "latency_scalability." + ext), dpi=200)
    print("-> " + os.path.join(a.out, "latency_scalability.png/.pdf"))
except Exception as e:
    print("plot skipped:", e)
