#!/usr/bin/env python3
"""Paper figures for the jammer-detection results (uses the functions of jammer_detect.py).

  map   one run: gNBs, UE trajectories, victim / legitimate UEs, actual and estimated jammer,
        zoom around the jammer and the errors of every method (all estimates kept inside the plot)
  maps  several runs side by side, panels (a), (b), ... (e.g. the median runs at 40 and 60 dBm)
  bars  one run: per-UE minimum / average / std of the best-cell L3 SINR (victims highlighted)
  mc    whole campaign (summary CSV): error CDFs, median error vs power, detection rate
  report one or more runs: map + SINR bars + table of victim/legitimate UEs (CSV and LaTeX)
        + text summary, each run in its own sub-folder of --out-dir

Examples
  python3 paper_figures.py map  --run-dir ~/jammer_runs/p60_on1_r7
  python3 paper_figures.py maps --run-dirs ~/jammer_runs/p40_on1_r17 ~/jammer_runs/p60_on1_r25 --out maps_40_60
  python3 paper_figures.py bars --run-dir ~/jammer_runs/p60_on1_r7
  python3 paper_figures.py report --run-dirs ~/jammer_runs/p40_on1_r17 ~/jammer_runs/p50_on1_r24 \
                                   ~/jammer_runs/p60_on1_r25 --out-dir ~/jammer_figs_gnb3
  python3 paper_figures.py mc   --summary-csv ~/jammer_runs/all_g3_n0.csv --seeds 6-30 --out ~/paper_figs/g3
Icons are read from --icons (default: icons/ next to this script).
"""
import argparse
import importlib.util
import os
import types
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.legend_handler import HandlerBase
from matplotlib.image import BboxImage
from matplotlib.transforms import Bbox, TransformedBbox
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
plt.rcParams.update({"font.size": 12, "axes.titlesize": 14, "axes.titleweight": "bold",
                     "axes.labelsize": 13, "legend.fontsize": 10, "savefig.dpi": 300})

METHODS = {  # name -> (label, colour, marker)
    "jtrilat": ("Interference trilateration (proposed)", "#d62728", "*"),
    "sdbscan": ("S-DBSCAN", "#1f77b4", "s"),
    "htdbscan": ("HT-HDBSCAN", "#9467bd", "^"),
    "centroid": ("Centroid (CL)", "#7f7f7f", "o"),
    "minsinr": ("Minimum-SINR", "#8c564b", "v"),
    "t26": ("Path-loss trilateration [26]", "#ff7f0e", "D"),
    "t26kp": ("Path-loss trilat. [26], known EIRP", "#ffbb78", "d"),
}


def load_jd(path):
    spec = importlib.util.spec_from_file_location("jd", os.path.expanduser(path))
    jd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jd)
    return jd


def default_args(**kw):
    a = types.SimpleNamespace(g_detect=-5.0, g_severe=-12.0, alpha=5.0, beta=1.0, delta=15.0, eps=400.0, min_pts=6,
                              trim_pct=75.0, g_th=-20.0, min_cluster_size=3, min_samples=2, min_victim_ues=2,
                              dedup_ms=0, rsrp_err_db=2.0, sinr_err_db=1.0, noise_seed=-1, inr_th=6.0,
                              jt_window_ms=1000, jt_fscale_db=6.0, area_m=1000.0, tolerance_ms=100, true_pos=None,
                              jammer_on=None, sinr_mode="best", est_pos=None, pos_noise_m=0.0, pos_noise_tau_s=10.0,
                              t26_alpha=2.923, t26_ptx_dbm=50.0, t26_fc_ghz=3.5)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


# ---------------------------------------------------------------- icons
def crop_alpha(img):
    if img is None or img.ndim != 3 or img.shape[2] < 4:
        return img
    a = img[:, :, 3] > 0.03
    if not a.any():
        return img
    r = np.where(a.any(axis=1))[0]; c = np.where(a.any(axis=0))[0]
    return img[r[0]:r[-1] + 1, c[0]:c[-1] + 1]


def load_icons(d):
    ic = {}
    for k in ["jammer_actual", "jammer_detected", "ue", "ue_victim", "gnb"]:
        p = os.path.join(d, k + ".png")
        ic[k] = crop_alpha(plt.imread(p)) if os.path.exists(p) else None
    if ic["gnb"] is None:          # fallback: drawn tower
        ic["gnb"] = tower_icon()
    return ic


def tower_icon(color="#1e88e5"):
    fig = plt.figure(figsize=(1.6, 2.0), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-1.2, 1.2); ax.set_ylim(-0.05, 2.6); ax.axis("off")
    lw = 3
    ax.plot([-0.55, 0, 0.55], [0, 1.75, 0], color=color, lw=lw, solid_capstyle="round")
    for y0, y1 in [(0.15, 0.6), (0.6, 1.05), (1.05, 1.45)]:
        xa = 0.55 * (1 - y0 / 1.75); xb = 0.55 * (1 - y1 / 1.75)
        ax.plot([-xa, xb], [y0, y1], color=color, lw=lw * 0.6)
        ax.plot([xa, -xb], [y0, y1], color=color, lw=lw * 0.6)
    ax.plot(0, 1.85, "o", color="#43a047", ms=9)
    for r in [0.35, 0.6, 0.85]:
        th = np.linspace(-0.9, 0.9, 30)
        ax.plot(0.05 + r * np.cos(th), 1.85 + r * np.sin(th), color=color, lw=lw * 0.8)
        ax.plot(-0.05 - r * np.cos(th), 1.85 + r * np.sin(th), color=color, lw=lw * 0.8)
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba()).copy()
    plt.close(fig)
    return img


def place(ax, img, x, y, h_px, z=5, align=(0.5, 0.5)):
    # icon of h_px pixels anchored at (x, y); not drawn when (x, y) is outside the axes
    if img is None:
        return
    im = OffsetImage(img, zoom=h_px / img.shape[0])
    ab = AnnotationBbox(im, (x, y), frameon=False, zorder=z, box_alignment=align, annotation_clip=True)
    ab.set_in_layout(False)   # icons outside a zoomed axes must not enlarge the saved figure
    ax.add_artist(ab)


class HandlerImage(HandlerBase):
    def __init__(self, img):
        self.img = img
        super().__init__()

    def create_artists(self, legend, orig, xd, yd, width, height, fontsize, trans):
        h = height * 2.3
        w = min(width, h * self.img.shape[1] / self.img.shape[0])
        bb = Bbox.from_bounds(-xd + (width - w) / 2, -yd - (h - height) / 2, w, h)
        im = BboxImage(TransformedBbox(bb, trans))
        im.set_data(self.img)
        return [im]


# ---------------------------------------------------------------- one run
def run_data(jd, run_dir, a):
    pos = jd.load_positions(os.path.join(run_dir, "ue_position.txt"))
    sinr = jd.load_sinr_trace(os.path.join(run_dir, "MmWaveSinrTime.txt"))
    df, _ = jd.build_serving_samples(pos, sinr, a.tolerance_ms, "best")
    gt = jd.load_ground_truth(run_dir, a)
    a.noise_seed_eff = int(gt["rng_run"] or 0)
    victims = jd.stateful_victims(df, a.g_detect, a.g_severe, a.alpha, a.beta, a.delta)
    return pos, df, gt, victims


def estimates(jd, run_dir, df, pos, gt, a, methods):
    out = {}
    rx = None
    rxp = os.path.join(run_dir, "MmWaveJammerRx.txt")
    if os.path.exists(rxp):
        rx = jd.load_jammer_rx(rxp)
    for m in methods:
        try:
            if m == "jtrilat":
                if rx is None:
                    continue
                est, _ = jd.localise_jtrilat(rx, pos, a)
            elif m in ("t26", "t26kp"):
                if rx is None or not hasattr(jd, "localise_t26"):
                    continue
                est, _ = jd.localise_t26(rx, pos, a, gt, m)
            else:
                est, _ = jd.run_method(m, df, a)
        except Exception as e:  # keep the figure even if one method fails
            print("  (" + m + " skipped: " + str(e) + ")")
            continue
        if est is not None:
            out[m] = est
    return out


SHORT = {"jtrilat": "Proposed", "sdbscan": "S-DBSCAN", "htdbscan": "HT-HDBSCAN", "centroid": "CL",
         "minsinr": "Min-SINR", "t26": "[26]", "t26kp": "[26], known EIRP"}


def map_limits(gt, est, area=1000.0, margin=45.0):
    # deployment area, enlarged only on the side where an estimate falls outside it
    xs = [e[0] for e in est.values()]; ys = [e[1] for e in est.values()]
    xlo = 0.0 if min(xs + [0.0]) >= 0 else min(xs) - margin
    xhi = area if max(xs + [area]) <= area else max(xs) + margin
    ylo = 0.0 if min(ys + [0.0]) >= 0 else min(ys) - margin
    yhi = area if max(ys + [area]) <= area else max(ys) + margin
    return xlo, xhi, ylo, yhi


def draw_scene(ax, jd, pos, victims, vset, gt, est, icons, FS, scale=1.0, labels=True, area=1000.0,
               est_icon=False, gnb_scale=1.0):
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((0, 0), area, area, fill=False, ec="#9e9e9e", lw=1.0, ls="-", zorder=0))
    for u, g in pos.groupby("ue_id"):
        g = g.sort_values("t_ms")
        vic = u in vset
        ax.plot(g["x"], g["y"], color="#e53935" if vic else "#9e9e9e", lw=1.3, alpha=0.45, zorder=1)
        x, y = g["x"].iloc[-1], g["y"].iloc[-1]
        place(ax, icons["ue_victim"] if vic else icons["ue"], x, y, 26 * scale, z=6)
        if labels:
            ax.annotate("UE " + str(u), (x, y), xytext=(0, 15 * scale), textcoords="offset points",
                        ha="center", va="bottom", fontsize=FS - 3, fontweight="bold",
                        color="#c62828" if vic else "#1b5e20", zorder=14, annotation_clip=True,
                        bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.75)).set_in_layout(False)
    if len(victims):
        ax.scatter(victims["x"], victims["y"], s=7, color="#ef5350", alpha=0.25, zorder=2, lw=0)
    for gid, (gx, gy) in jd.GNB_POSITIONS.items():
        place(ax, icons["gnb"], gx, gy, 62 * scale * gnb_scale, z=4, align=(0.5, 0.12))   # tower base at the gNB
        if labels:
            ax.annotate("gNB " + str(gid), (gx, gy), xytext=(0, -6), textcoords="offset points", ha="center",
                        va="top", fontsize=FS - 2, fontweight="bold", zorder=13, annotation_clip=True,
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85)).set_in_layout(False)
    if gt["x"] is not None and gt["jammer_on"] == 1:
        place(ax, icons["jammer_actual"], gt["x"], gt["y"], 44 * scale, z=9)
    for m, (ex, ey) in est.items():
        lab, col, mk = METHODS.get(m, (m, "k", "x"))
        if gt["jammer_on"] == 1:
            ax.plot([gt["x"], ex], [gt["y"], ey], ls="--", color=col, lw=1.8, zorder=8)
        if m == "jtrilat":
            if est_icon and icons.get("jammer_detected") is not None:   # red jammer at the estimate
                place(ax, icons["jammer_detected"], ex, ey, 44 * scale, z=11)
                ax.scatter(ex, ey, marker="*", s=260 * scale, color=col, edgecolor="black", lw=1.0, zorder=12)
            else:
                ax.scatter(ex, ey, marker="*", s=560 * scale, color=col, edgecolor="black", lw=1.2, zorder=12)
        else:
            ax.scatter(ex, ey, marker=mk, s=210 * scale, color=col, edgecolor="black", lw=1.2, zorder=10)


def legend_items(est, icons, est_icon=True):
    handles, labels, hmap = [], [], {}
    for key, lab in [("gnb", "gNB"), ("ue", "Legitimate UE"), ("ue_victim", "Victim UE"),
                     ("jammer_actual", "Actual jammer")]:
        if icons.get(key) is None:
            continue
        h = Line2D([], [], lw=0)
        handles.append(h); labels.append(lab); hmap[h] = HandlerImage(icons[key])
    for m in ["sdbscan", "htdbscan", "centroid", "minsinr", "t26", "t26kp"]:
        if m in est:
            lab, col, mk = METHODS[m]
            handles.append(Line2D([], [], marker=mk, ls="--", color=col, mfc=col, mec="black", ms=12, lw=1.6))
            labels.append(lab)
    if "jtrilat" in est:
        handles.append(Line2D([], [], marker="*", ls="--", color=METHODS["jtrilat"][1], mec="black", ms=20, lw=1.6))
        labels.append("Interference trilateration (proposed)")
        if est_icon and icons.get("jammer_detected") is not None:
            h = Line2D([], [], lw=0)
            handles.append(h); labels.append("Estimated jammer (zoom)"); hmap[h] = HandlerImage(icons["jammer_detected"])
    handles.append(Line2D([], [], color="#ef5350", marker="o", ls="", ms=6, alpha=0.6)); labels.append("Victim reports")
    return handles, labels, hmap


def error_lines(gt, est, methods=None):
    lines = []
    if gt["jammer_on"] == 1:
        lines.append("Actual jammer: (%.0f, %.0f) m, %.0f dBm" % (gt["x"], gt["y"], gt["power_dbm"]))
    order = ["jtrilat", "sdbscan", "htdbscan", "centroid", "minsinr", "t26", "t26kp"]
    for m in [m for m in order if m in est]:
        ex, ey = est[m]
        err = np.hypot(ex - gt["x"], ey - gt["y"]) if gt["x"] is not None else np.nan
        lines.append("%-13s (%4.0f, %4.0f) m   error %6.1f m" % (SHORT.get(m, m) + ":", ex, ey, err))
    for m in [m for m in order if methods and m in methods and m not in est]:
        lines.append("%-13s no alarm (attack not detected)" % (SHORT.get(m, m) + ":"))
    if gt["jammer_on"] != 1:
        lines.append("Jammer OFF: " + ("no alarm" if not est else "FALSE ALARM"))
    return lines


def fig_map(jd, a, run_dir, out, methods, icons, scenario_title=None):
    # One realization, sized for the full text width: map (left), zoom around the jammer (top right),
    # estimates and errors (bottom right), legend (bottom). Every estimate is kept inside the axes.
    pos, df, gt, victims = run_data(jd, run_dir, a)
    est = estimates(jd, run_dir, df, pos, gt, a, methods)
    vset = set(victims["ue_id"].unique().tolist())
    FS = 16
    fig = plt.figure(figsize=(14.0, 9.6))
    ax = fig.add_axes([0.055, 0.215, 0.56, 0.75])
    axz = fig.add_axes([0.665, 0.50, 0.31, 0.435])
    axd = fig.add_axes([0.665, 0.215, 0.31, 0.24]); axd.axis("off")
    xlo, xhi, ylo, yhi = map_limits(gt, est, a.area_m)
    ax.set_xlim(xlo, xhi); ax.set_ylim(ylo, yhi); ax.set_aspect("equal")
    ax.grid(True, ls=":", alpha=0.5)
    ax.set_xlabel("x (m)", fontsize=FS); ax.set_ylabel("y (m)", fontsize=FS)
    ax.tick_params(labelsize=FS - 2)
    if scenario_title:
        ax.set_title(scenario_title, fontsize=FS + 1)
    draw_scene(ax, jd, pos, victims, vset, gt, est, icons, FS, scale=1000.0 / max(xhi - xlo, yhi - ylo))
    if gt["x"] is not None and gt["jammer_on"] == 1:
        from matplotlib.patches import Rectangle
        half = 60.0
        if "jtrilat" in est:
            ex, ey = est["jtrilat"]
            half = max(half, 1.4 * max(abs(ex - gt["x"]), abs(ey - gt["y"])) + 15)
        draw_scene(axz, jd, pos, victims, vset, gt, est, icons, FS, scale=1.6, labels=False, est_icon=True,
                   gnb_scale=0.55)
        axz.set_xlim(gt["x"] - half, gt["x"] + half); axz.set_ylim(gt["y"] - half, gt["y"] + half)
        axz.set_aspect("equal"); axz.grid(True, ls=":", alpha=0.5)
        axz.tick_params(labelsize=FS - 4)
        axz.set_title("Zoom around the jammer (%.0f m x %.0f m)" % (2 * half, 2 * half), fontsize=FS - 2)
        if "jtrilat" in est:
            ex, ey = est["jtrilat"]
            err = np.hypot(ex - gt["x"], ey - gt["y"])
            axz.annotate("proposed: %.1f m" % err, (ex, ey), xytext=(14, -30), textcoords="offset points",
                         fontsize=FS - 3, fontweight="bold", color=METHODS["jtrilat"][1], zorder=20,
                         bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=METHODS["jtrilat"][1], alpha=0.9))
        ax.add_patch(Rectangle((gt["x"] - half, gt["y"] - half), 2 * half, 2 * half, fill=False,
                               ec="black", lw=1.5, zorder=15))
    else:
        axz.axis("off")
    axd.text(0.0, 1.0, "Localization results\n" + "\n".join(error_lines(gt, est, methods)), transform=axd.transAxes,
             va="top", ha="left", fontsize=FS - 4, family="monospace", linespacing=1.45,
             bbox=dict(boxstyle="round", fc="white", ec="black", alpha=0.95))
    h, l, hm = legend_items(est, icons)
    fig.legend(h, l, handler_map=hm, loc="lower center", bbox_to_anchor=(0.5, 0.005), fontsize=FS - 3,
               frameon=True, framealpha=0.95, borderpad=0.6, labelspacing=1.0, handlelength=2.6,
               columnspacing=1.4, ncol=5)
    for ext in ("png", "pdf"):
        fig.savefig(out + "." + ext, bbox_inches="tight", dpi=400)
    plt.close(fig)
    print("-> " + out + ".png/.pdf")


def fig_maps(jd, a, run_dirs, out, methods, icons, titles=None):
    # Several realizations side by side, panels (a), (b), ...: same axis limits for every panel,
    # results box under each panel, shared legend at the bottom (nothing overlaps).
    from matplotlib.gridspec import GridSpec
    n = len(run_dirs)
    FS = 16
    data = []
    for rd in run_dirs:
        rd = os.path.expanduser(rd)
        pos, df, gt, victims = run_data(jd, rd, a)
        est = estimates(jd, rd, df, pos, gt, a, methods)
        data.append((rd, pos, gt, victims, est))
    lims = [map_limits(gt, est, a.area_m) for _, _, gt, _, est in data]
    xlo = min(l[0] for l in lims); xhi = max(l[1] for l in lims)
    ylo = min(l[2] for l in lims); yhi = max(l[3] for l in lims)
    fig = plt.figure(figsize=(8.6 * n, 13.2))
    gs = GridSpec(2, n, figure=fig, height_ratios=[1.0, 0.24], hspace=0.12, wspace=0.12,
                  left=0.05, right=0.99, top=0.96, bottom=0.13)
    allest = {}
    for k, (rd, pos, gt, victims, est) in enumerate(data):
        ax = fig.add_subplot(gs[0, k]); axt = fig.add_subplot(gs[1, k]); axt.axis("off")
        allest.update(est)
        vset = set(victims["ue_id"].unique().tolist())
        ax.set_xlim(xlo, xhi); ax.set_ylim(ylo, yhi); ax.set_aspect("equal")
        ax.grid(True, ls=":", alpha=0.5)
        ax.set_xlabel("x (m)", fontsize=FS); ax.tick_params(labelsize=FS - 3)
        if k == 0:
            ax.set_ylabel("y (m)", fontsize=FS)
        draw_scene(ax, jd, pos, victims, vset, gt, est, icons, FS, scale=0.9 * 1000.0 / max(xhi - xlo, yhi - ylo))
        t = titles[k] if titles and k < len(titles) else ("%.0f dBm jammer, seed %s, %d victim UE%s"
                                                          % (gt["power_dbm"], gt["rng_run"], len(vset),
                                                             "" if len(vset) == 1 else "s"))
        ax.set_title("(%s) %s" % ("abcdefgh"[k], t), fontsize=FS)
        axt.text(0.5, 1.0, "\n".join(error_lines(gt, est, methods)), transform=axt.transAxes, va="top", ha="center",
                 multialignment="left", fontsize=FS - 3, family="monospace", linespacing=1.45,
                 bbox=dict(boxstyle="round", fc="white", ec="black", alpha=0.95))
    h, l, hm = legend_items(allest, icons, est_icon=False)
    fig.legend(h, l, handler_map=hm, loc="lower center", bbox_to_anchor=(0.5, 0.0), fontsize=FS - 1,
               frameon=True, framealpha=0.95, borderpad=0.6, labelspacing=1.0, handlelength=2.6,
               columnspacing=1.6, ncol=5)
    for ext in ("png", "pdf"):
        fig.savefig(out + "." + ext, bbox_inches="tight", dpi=400)
    plt.close(fig)
    print("-> " + out + ".png/.pdf")


def fig_bars(jd, a, run_dir, out):
    pos, df, gt, victims = run_data(jd, run_dir, a)
    vset = set(victims["ue_id"].unique().tolist())
    st = df.groupby("ue_id")["sinr_db"].agg(["min", "mean", "std"]).sort_index()
    ues = st.index.tolist()
    names = ["UE %d (%s)" % (u, "V" if u in vset else "L") for u in ues]
    col = ["#e53935" if u in vset else "#1e88e5" for u in ues]
    hat = ["//" if u in vset else "" for u in ues]
    fig, axs = plt.subplots(1, 3, figsize=(17, 6.0))
    for ax, key, title in zip(axs, ["min", "mean", "std"], ["Minimum SINR (dB)", "Average SINR (dB)", "Std. dev. of SINR (dB)"]):
        vals = st[key].to_numpy()
        bars = ax.bar(range(len(ues)), vals, color=col, edgecolor="black", hatch=hat, lw=0.8, alpha=0.9)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + (0.6 if v >= 0 else -0.6), "%.1f" % v, ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=11, fontweight="bold")
        ax.set_xticks(range(len(ues)))
        ax.set_xticklabels(names, rotation=45, ha="right", fontsize=12)
        ax.tick_params(axis="y", labelsize=12)
        ax.set_title(title)
        ax.grid(axis="y", ls="--", alpha=0.5)
        ax.axhline(0, color="black", lw=0.8)
        lo, hi = min(0, vals.min()), max(0, vals.max())
        pad = 0.12 * (hi - lo + 1)
        ax.set_ylim(lo - pad if lo < 0 else 0, hi + pad)
        if key == "min":
            ax.axhline(a.g_detect, color="#fb8c00", ls="--", lw=1.4)
            ax.axhline(a.g_severe, color="#c62828", ls="--", lw=1.4)
    axs[0].set_ylabel("SINR (dB)", fontsize=14)
    leg = [Patch(fc="#e53935", ec="black", hatch="//", label="Victim UE (V)"),
           Patch(fc="#1e88e5", ec="black", label="Legitimate UE (L)"),
           Line2D([], [], color="#fb8c00", ls="--", label=r"$\gamma_{\mathrm{detect}}$ = %.0f dB" % a.g_detect),
           Line2D([], [], color="#c62828", ls="--", label=r"$\gamma_{\mathrm{severe}}$ = %.0f dB" % a.g_severe)]
    fig.legend(handles=leg, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.03), fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for ext in ("png", "pdf"):
        fig.savefig(out + "." + ext, bbox_inches="tight", dpi=400)
    plt.close(fig)
    print("-> " + out + ".png/.pdf")


def ue_table(jd, a, run_dir, out):
    """Per-UE table (same statistics as the bar chart): CSV, LaTeX rows and a printout."""
    pos, df, gt, victims = run_data(jd, run_dir, a)
    vset = set(victims["ue_id"].unique().tolist())
    st = df.groupby("ue_id")["sinr_db"].agg(["min", "mean", "std", "count"]).sort_index()
    below = df.assign(b=df["sinr_db"] < a.g_detect).groupby("ue_id")["b"].mean() * 100
    rows = []
    for u, r in st.iterrows():
        rows.append({"ue_id": int(u), "class": "Victim" if u in vset else "Legitimate",
                     "min_sinr_db": round(r["min"], 1), "avg_sinr_db": round(r["mean"], 1),
                     "std_sinr_db": round(r["std"], 1), "pct_below_gdetect": round(below.get(u, 0.0), 1),
                     "n_reports": int(r["count"])})
    T = pd.DataFrame(rows).sort_values(["class", "ue_id"], ascending=[False, True])
    T.to_csv(out + ".csv", index=False)
    with open(out + ".tex", "w") as f:
        f.write("%% UE classification, %s (%.0f dBm, seed %s)\n" % (os.path.basename(run_dir), gt["power_dbm"] or 0, gt["rng_run"]))
        for cls, head in [("Victim", "Jamming Victims"), ("Legitimate", "Legitimate UEs")]:
            sub = T[T["class"] == cls]
            if len(sub) == 0:
                continue
            f.write("\\multicolumn{4}{|c|}{\\textbf{%s}} \\\\ \\hline\n" % head)
            for _, r in sub.iterrows():
                f.write("%-3d & %-10s & $%.1f$ & $%.1f$ \\\\ \\hline\n" % (r["ue_id"], cls, r["min_sinr_db"], r["avg_sinr_db"]))
    print("\nUE table  %s  (%d victims, %d legitimate)" % (os.path.basename(run_dir), len(vset), len(T) - len(vset)))
    print(T.to_string(index=False))
    print("-> " + out + ".csv / .tex")
    return T


def report(jd, a, run_dirs, out_dir, methods, icons):
    out_dir = os.path.expanduser(out_dir)
    for rd in run_dirs:
        rd = os.path.expanduser(rd.rstrip("/"))
        name = os.path.basename(rd)
        pos, df, gt, victims = run_data(jd, rd, a)
        tag = ("%.0fdBm_" % gt["power_dbm"] if gt["power_dbm"] is not None and gt["jammer_on"] == 1 else "off_") + name
        d = os.path.join(out_dir, tag)
        os.makedirs(d, exist_ok=True)
        print("\n================ %s  ->  %s" % (name, d))
        fig_map(jd, a, rd, os.path.join(d, "jammer_map"), methods, icons)
        fig_bars(jd, a, rd, os.path.join(d, "sinr_bars"))
        ue_table(jd, a, rd, os.path.join(d, "ue_table"))
        est = estimates(jd, rd, df, pos, gt, a, methods)
        lines = error_lines(gt, est, methods)
        if "jtrilat" in est:
            ex, ey = est["jtrilat"]
            lines.append("Distances from the proposed estimate to the gNBs:")
            for gid, (gx, gy) in jd.GNB_POSITIONS.items():
                lines.append("  gNB %s (%.1f, %.1f): %.1f m" % (gid, gx, gy, np.hypot(ex - gx, ey - gy)))
        with open(os.path.join(d, "summary.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        print("\n".join(lines))
        print("-> " + os.path.join(d, "summary.txt"))


# ---------------------------------------------------------------- Monte Carlo
def parse_seeds(txt):
    out = set()
    for p in txt.split(","):
        p = p.strip()
        if "-" in p:
            lo, hi = p.split("-"); out.update(range(int(lo), int(hi) + 1))
        elif p:
            out.add(int(p))
    return out


def fig_mc(csvs, seeds, outdir, methods, pos_noise=0.0):
    s = pd.concat([pd.read_csv(c) for c in csvs], ignore_index=True)
    if seeds:
        s = s[s["rng_run"].isin(parse_seeds(seeds))]
    if "pos_noise_m" in s.columns:
        s = s[s["pos_noise_m"].fillna(0) == pos_noise]
    s = s.drop_duplicates(subset=["run_dir", "method"], keep="last")
    on = s[s["jammer_on"] == 1]
    powers = sorted(on["power_dbm"].dropna().unique())
    methods = [m for m in methods if m in set(on["method"])]
    os.makedirs(outdir, exist_ok=True)
    # 1) error CDF per power
    fig, axs = plt.subplots(1, len(powers), figsize=(5.4 * len(powers), 4.6), sharey=True)
    axs = np.atleast_1d(axs)
    for ax, p in zip(axs, powers):
        for m in methods:
            e = np.sort(on[(on["power_dbm"] == p) & (on["method"] == m) & (on["detected"] == 1)]["error_m"].dropna())
            if len(e) == 0:
                continue
            lab, col, mk = METHODS.get(m, (m, "k", "x"))
            ax.step(np.r_[0, e], np.r_[0, np.arange(1, len(e) + 1) / len(e)], where="post", color=col,
                    lw=3 if m == "jtrilat" else 1.8, label=lab)
        ax.set_xscale("log"); ax.set_xlim(1, 1500)
        ax.set_title("Jammer EIRP %.0f dBm" % p); ax.set_xlabel("Localization error (m)")
        ax.grid(True, which="both", ls=":", alpha=0.6)
    axs[0].set_ylabel("Empirical CDF")
    h, l = axs[0].get_legend_handles_labels()
    for ax in axs[1:]:
        for hh, ll in zip(*ax.get_legend_handles_labels()):
            if ll not in l:
                h.append(hh); l.append(ll)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    fig.legend(h, l, loc="lower center", ncol=min(len(l), 6), frameon=False, fontsize=10, bbox_to_anchor=(0.5, 0.0))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(outdir, "mc_error_cdf." + ext), bbox_inches="tight")
    plt.close(fig)
    # 2) median error vs power (bootstrap 95% CI) and 3) detection rate
    rng = np.random.default_rng(0)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 4.8))
    w = 0.8 / max(len(methods), 1)
    for k, m in enumerate(methods):
        lab, col, mk = METHODS.get(m, (m, "k", "x"))
        med, lo, hi, det = [], [], [], []
        for p in powers:
            g = on[(on["power_dbm"] == p) & (on["method"] == m)]
            e = g[g["detected"] == 1]["error_m"].dropna().to_numpy()
            det.append(100 * g["detected"].mean() if len(g) else np.nan)
            if len(e) >= 2:
                bs = np.median(rng.choice(e, (2000, len(e))), axis=1)
                med.append(np.median(e)); lo.append(np.median(e) - np.percentile(bs, 2.5)); hi.append(np.percentile(bs, 97.5) - np.median(e))
            elif len(e) == 1:
                med.append(e[0]); lo.append(0); hi.append(0)
            else:
                med.append(np.nan); lo.append(0); hi.append(0)
        x = np.arange(len(powers)) + (k - (len(methods) - 1) / 2) * w
        a1.bar(x, med, w, yerr=[lo, hi], capsize=3, color=col, edgecolor="black", lw=0.6, label=lab,
               hatch="//" if m == "jtrilat" else "")
        a2.bar(x, det, w, color=col, edgecolor="black", lw=0.6, label=lab, hatch="//" if m == "jtrilat" else "")
    for ax in (a1, a2):
        ax.set_xticks(range(len(powers))); ax.set_xticklabels(["%.0f dBm" % p for p in powers])
        ax.set_xlabel("Jammer EIRP"); ax.grid(axis="y", ls="--", alpha=0.5)
    a1.set_yscale("log"); a1.set_ylabel("Median localization error (m)"); a1.set_title("Localization error (95% CI)")
    a2.set_ylabel("Detection rate (%)"); a2.set_ylim(0, 110); a2.set_title("Detection rate")
    h, l = a2.get_legend_handles_labels()
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.legend(h, l, loc="lower center", ncol=min(len(l), 3), frameon=False, fontsize=10, bbox_to_anchor=(0.5, 0.0))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(outdir, "mc_error_detection." + ext), bbox_inches="tight")
    plt.close(fig)
    print("-> " + outdir + "/mc_error_cdf.png/.pdf, mc_error_detection.png/.pdf")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["map", "maps", "bars", "mc", "table", "report"])
    ap.add_argument("--detect", default="~/jammer_fix_gnb3/jammer_detect.py")
    ap.add_argument("--icons", default=os.path.join(HERE, "icons"))
    ap.add_argument("--run-dir")
    ap.add_argument("--run-dirs", nargs="+", help="for maps: several runs side by side")
    ap.add_argument("--out", default=None)
    ap.add_argument("--out-dir", default="jammer_figs", help="for report")
    ap.add_argument("--title", default=None)
    ap.add_argument("--methods", nargs="+", default=["sdbscan", "centroid", "t26", "jtrilat"])
    ap.add_argument("--summary-csv", nargs="+")
    ap.add_argument("--seeds", default=None)
    ap.add_argument("--pos-noise", type=float, default=0.0)
    ap.add_argument("--t26-alpha", type=float, default=2.923)
    a0 = ap.parse_args()
    if a0.what == "mc":
        meths = ["sdbscan", "htdbscan", "centroid", "minsinr", "t26", "jtrilat"]
        fig_mc(a0.summary_csv, a0.seeds, os.path.expanduser(a0.out or "paper_figs"), meths, a0.pos_noise)
        return
    jd = load_jd(a0.detect)
    a = default_args(t26_alpha=a0.t26_alpha)
    if a0.what == "report":
        report(jd, a, a0.run_dirs or [a0.run_dir], a0.out_dir, a0.methods, load_icons(a0.icons))
        return
    if a0.what == "maps":
        out = os.path.expanduser(a0.out or "fig_jammer_maps")
        fig_maps(jd, a, a0.run_dirs, out, a0.methods, load_icons(a0.icons))
        return
    run_dir = os.path.expanduser(a0.run_dir)
    if a0.what == "map":
        out = a0.out or os.path.join(run_dir, "fig_jammer_map")
        fig_map(jd, a, run_dir, os.path.expanduser(out), a0.methods, load_icons(a0.icons), a0.title)
    elif a0.what == "table":
        ue_table(jd, a, run_dir, os.path.expanduser(a0.out or os.path.join(run_dir, "ue_table")))
    else:
        out = a0.out or os.path.join(run_dir, "fig_sinr_bars")
        fig_bars(jd, a, run_dir, os.path.expanduser(out))


if __name__ == "__main__":
    main()
