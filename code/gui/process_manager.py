#!/usr/bin/env python3
"""
process_manager.py — companion helper for the FlexRIC jammer dashboard.

Listens on port 38867 and exposes a tiny REST API the dashboard uses to:
  • start / stop the FlexRIC core (nearRT-RIC)
  • start / stop the KPM monitoring xApp (xapp_kpm_moni)
  • start / stop the offline localizer Python xApp
  • tail the log of any of the above + the ns-3 simulation log

Run alongside main.py (the GUI) and gui_trigger.py (the ns-3 launcher):

    python3 process_manager.py

Stdlib only — no extra pip installs needed.
Edit the PROCESSES dict below if your paths differ.
"""

import http.server
import socketserver
import json
import subprocess
import os
import signal
import time
import urllib.parse
from pathlib import Path

PORT    = 38867
HOME    = Path(os.environ.get("FLEXRIC_HOME", "/home/k3"))
LOG_DIR = Path("/tmp/flexric-dashboard")
LOG_DIR.mkdir(exist_ok=True)
SCRATCH_DIR = HOME / "ns-O-RAN-flexric/mmwave-LENA-oran/scratch"

# ─── EDIT PATHS HERE IF YOURS DIFFER ────────────────────────────────────────
PROCESSES = {
    "ric": {
        "label": "FlexRIC (nearRT-RIC)",
        "cmd":   [str(HOME / "flexric/build/examples/ric/nearRT-RIC")],
        "cwd":   str(HOME / "flexric/build/examples/ric"),
        "log":   LOG_DIR / "ric.log",
    },
    "xapp": {
        "label": "KPM monitoring xApp",
        "cmd":   [str(HOME / "flexric/build/examples/xApp/c/monitor/xapp_kpm_moni")],
        "cwd":   str(HOME / "flexric/build/examples/xApp/c/monitor"),
        "log":   LOG_DIR / "xapp.log",
    },
    "localizer": {
        "label": "Jammer localizer (Python xApp)",
        "cmd":   None,  # built dynamically per-request in start_localizer()
        "cwd":   str(HOME / "flexric/build/examples/xApp/c/monitor"),
        "log":   LOG_DIR / "localizer.log",
    },
    "ns3": {
        # ns-3 itself is started via gui_trigger.py (the existing path used by
        # the GUI's "Start new" button); we ONLY tail its log here.
        "label": "ns-3 simulation",
        "cmd":   None,
        "cwd":   None,
        "log":   HOME / "ns-O-RAN-flexric/mmwave-LENA-oran/ns3_run.log",
    },
}
# ────────────────────────────────────────────────────────────────────────────

# binary names for pkill -9 fallback
PKILL_NAMES = {
    "ric":       ["nearRT-RIC"],
    "xapp":      ["xapp_kpm_moni"],
    "localizer": ["jammer_xapp_localizer_v2.py"],
    "ns3":       ["scenario-zero-with-jammer", "ns3"],
}

# runtime state stored separately from config
STATE = {name: {"proc": None, "started_at": None} for name in PROCESSES}


def is_running(name):
    p = STATE[name]["proc"]
    return p is not None and p.poll() is None


def start(name):
    if name not in PROCESSES:
        return {"ok": False, "error": f"unknown process '{name}'"}
    cfg = PROCESSES[name]
    if cfg["cmd"] is None:
        return {"ok": False, "error": f"{name} cannot be started here — use the dashboard's Start new button"}
    if is_running(name):
        return {"ok": True, "running": True, "pid": STATE[name]["proc"].pid, "note": "already running"}
    # binary check
    bin_path = cfg["cmd"][-1] if cfg["cmd"][0] == "python3" else cfg["cmd"][0]
    if not os.path.exists(bin_path):
        return {"ok": False, "error": f"binary not found: {bin_path}"}
    try:
        logf = open(cfg["log"], "ab")
        logf.write(f"\n=== START {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
        logf.flush()
        p = subprocess.Popen(
            cfg["cmd"],
            cwd=cfg["cwd"],
            stdout=logf,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        STATE[name]["proc"] = p
        STATE[name]["started_at"] = time.time()
        return {"ok": True, "running": True, "pid": p.pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def start_localizer(payload):
    name = "localizer"
    cfg = PROCESSES[name]
    if is_running(name):
        return {"ok": True, "running": True, "pid": STATE[name]["proc"].pid, "note": "already running"}
    jam_start = payload.get("jam_start", "5")
    jam_stop = payload.get("jam_stop", "35")
    sim_time = payload.get("sim_time", "40")
    n_jammers = payload.get("n_jammers", "1")
    kpi_csv = str(HOME / "flexric/build/examples/xApp/c/monitor/kpi_dashboard.csv")
    gnb_csv = str(HOME / "ns-O-RAN-flexric/mmwave-LENA-oran/gnb_positions.csv")
    gt_csv = str(HOME / "ns-O-RAN-flexric/mmwave-LENA-oran/jammer_ground_truth.csv")
    ue_pos = str(HOME / "ns-O-RAN-flexric/mmwave-LENA-oran/ue_position.txt")
    out_dir = str(HOME / "xapp_output_v2")
    script = str(HOME / "flexric/build/examples/xApp/c/monitor/jammer_xapp_localizer_v2.py")
    if not os.path.exists(script):
        return {"ok": False, "error": f"binary not found: {script}"}
    cmd = [
        "python3", script,
        "--kpi-csv", kpi_csv,
        "--gnb-csv", gnb_csv,
        "--gt-csv", gt_csv,
        "--ue-pos", ue_pos,
        "--out-dir", out_dir,
        "--jam-start", str(jam_start),
        "--jam-stop", str(jam_stop),
        "--sim-time", str(sim_time),
        "--n-jammers", str(n_jammers),
    ]
    try:
        logf = open(cfg["log"], "ab")
        logf.write(f"\n=== LOCALIZER START {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
        logf.write(f"CMD: {' '.join(cmd)}\n".encode())
        logf.flush()
        p = subprocess.Popen(
            cmd,
            cwd=cfg["cwd"],
            stdout=logf,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        STATE[name]["proc"] = p
        STATE[name]["started_at"] = time.time()
        return {"ok": True, "running": True, "pid": p.pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def stop(name):
    if name not in PROCESSES:
        return {"ok": False, "error": f"unknown process '{name}'"}
    killed = []
    # 1) Try graceful kill via process group if we have a handle
    p = STATE[name]["proc"]
    if p is not None and p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            for _ in range(20):
                if p.poll() is not None:
                    break
                time.sleep(0.1)
            if p.poll() is None:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            killed.append(f"pid {p.pid}")
        except ProcessLookupError:
            pass
    # 2) Always pkill -9 by binary name as safety net
    for pname in PKILL_NAMES.get(name, []):
        try:
            result = subprocess.run(["pkill", "-9", "-f", pname],
                                    capture_output=True, timeout=5)
            if result.returncode == 0:
                killed.append(f"pkill {pname}")
        except Exception:
            pass
    # 3) Log the stop event
    cfg = PROCESSES[name]
    try:
        with open(cfg["log"], "ab") as lf:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            msg = '\n=== STOPPED ' + ts + ' (killed: ' + str(killed) + ') ===\n'
            lf.write(msg.encode())
    except Exception:
        pass
    STATE[name]["proc"] = None
    STATE[name]["started_at"] = None
    return {"ok": True, "running": False, "killed": killed}


def status(name):
    if name not in PROCESSES:
        return {"name": name, "exists": False}
    cfg = PROCESSES[name]
    st  = STATE[name]
    running = is_running(name)
    return {
        "name":       name,
        "label":      cfg["label"],
        "manageable": cfg["cmd"] is not None,
        "running":    running,
        "pid":        st["proc"].pid if running else None,
        "uptime_s":   (time.time() - st["started_at"]) if (running and st["started_at"]) else 0,
        "log_exists": cfg["log"].exists(),
        "log_size":   cfg["log"].stat().st_size if cfg["log"].exists() else 0,
        "log_path":   str(cfg["log"]),
    }


def tail_log(name, lines=300):
    if name not in PROCESSES:
        return ""
    cfg = PROCESSES[name]
    if not cfg["log"].exists():
        return f"[log file not yet created — {cfg['log']}]"
    try:
        with open(cfg["log"], "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 131072))   # last 128 KB
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-lines:])
    except Exception as e:
        return f"[error reading log: {e}]"


def list_scenarios():
    """Live scan of the ns-3 scratch/ folder so new scenario files show up
    in the dashboard dropdowns without any server restart."""
    result = {}
    if not SCRATCH_DIR.is_dir():
        return result
    idx = 0
    for f in sorted(SCRATCH_DIR.glob("*.cc")):
        name = f.name
        if ":" in name:                     # skip Windows Zone.Identifier ADS artifacts
            continue
        if name == "scratch-simulator.cc":  # skip the ns-3 template stub
            continue
        result[str(idx)] = f"scratch/{name}"
        idx += 1
    return result


class Handler(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        url   = urllib.parse.urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        qs    = urllib.parse.parse_qs(url.query)
        if parts == ["status"]:
            return self._send_json({n: status(n) for n in PROCESSES})
        if len(parts) == 2 and parts[0] == "status":
            return self._send_json(status(parts[1]))
        if len(parts) == 2 and parts[0] == "logs":
            n_lines = int(qs.get("lines", ["300"])[0])
            return self._send_json({"name": parts[1], "log": tail_log(parts[1], n_lines)})
        if parts == ["scenarios"]:
            return self._send_json(list_scenarios())
        return self._send_json({"error": "unknown route", "path": self.path}, 404)

    def do_POST(self):
        url   = urllib.parse.urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        qs    = urllib.parse.parse_qs(url.query)
        if parts == ["start_localizer"]:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                payload = {}
            return self._send_json(start_localizer(payload))
        if len(parts) == 2 and parts[0] == "start":
            return self._send_json(start(parts[1]))
        if len(parts) == 2 and parts[0] == "stop":
            return self._send_json(stop(parts[1]))
        if len(parts) == 2 and parts[0] == "logs" and qs.get("clear", ["0"])[0] == "1":
            name = parts[1]
            if name not in PROCESSES:
                return self._send_json({"error": "unknown process " + name}, 404)
            try:
                open(PROCESSES[name]["log"], "w").close()
                return self._send_json({"ok": True, "cleared": name})
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 500)
        return self._send_json({"error": "unknown route", "path": self.path}, 404)

    def log_message(self, fmt, *args):
        return   # silence default access log


if __name__ == "__main__":
    print(f"[process_manager] log dir : {LOG_DIR}")
    print(f"[process_manager] listening on :{PORT}")
    print(f"[process_manager] processes:")
    for n, cfg in PROCESSES.items():
        m = "managed" if cfg["cmd"] else "log-only"
        print(f"   • {n:<10} [{m}]  log → {cfg['log']}")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n[process_manager] shutting down…")
            for n in PROCESSES:
                if is_running(n):
                    print(f"   stopping {n}")
                    stop(n)
