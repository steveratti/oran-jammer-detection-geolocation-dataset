import os
import subprocess
from dataclasses import asdict

import requests
import json

import paramiko
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from src.simulation_objects.simulation import Simulation
from src.simulation_objects.simulation_manager import SimulationManager

influx_data_router = APIRouter()
import os
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"))
templates.env.auto_reload = True


def get_simulation() -> Simulation:
    return SimulationManager.get_simulation()


@influx_data_router.get("/")
async def root(request: Request, simulation: Simulation = Depends(get_simulation)):
    host_ns3 = os.getenv('NS3_HOST')
    return templates.TemplateResponse(
        "chart.html",
        {
            "request": request,
            "ues": simulation.ues,
            "cells": simulation.cells,
            "sim_id": simulation.sim_id,
            "chart_dimensions": (simulation.max_x, simulation.max_y),
            "host_ns3": host_ns3,
        },
    )

@influx_data_router.get("/jammer")
async def jammer_page(request: Request, simulation: Simulation = Depends(get_simulation)):
    host_ns3 = os.getenv('NS3_HOST')
    return templates.TemplateResponse(
        "jammer.html",
        {
            "request": request,
            "ues": simulation.ues,
            "cells": simulation.cells,
            "sim_id": simulation.sim_id,
            "chart_dimensions": (simulation.max_x, simulation.max_y),
            "host_ns3": host_ns3,
        },
    )

@influx_data_router.get("/scenarios")
async def scenarios(request: Request):
    remote_host = os.getenv('NS3_HOST')
    files = {}
    try:
        response = requests.get(f'http://{remote_host}:38866', timeout=3)
        if response.status_code == 200:
            files = json.loads(response.text)
    except Exception as _e:
        print("gui_trigger scenario fetch failed:", _e)
    if not files:
        try:
            response = requests.get(f'http://{remote_host}:38867/scenarios', timeout=3)
            if response.status_code == 200:
                files = response.json()
        except Exception as _e:
            print("process_manager scenario fetch failed:", _e)
    if not files:
        files = {"0":"scratch/scenario-zero-with_parallel_loging.cc",
            "1":"scratch/scenario-one.cc",
            "2":"scratch/scenario-zero.cc",
            "3":"scratch/scenario-zero-with-jammer-v3.cc"}
    return files

@influx_data_router.get("/refresh-data")
async def refresh_data(request: Request, simulation: Simulation = Depends(get_simulation)):
    SimulationManager.refresh_simulation()
    updated_simulation = SimulationManager.get_simulation()
    if (updated_simulation.number_of_ues == 0 or updated_simulation.number_of_cells == 0) and updated_simulation.simulation_status == 'on':
        updated_simulation.set_ue_cell_number()
    es_state = {}
    sinr = {}
    retx = {}
    prb = {}
    for cell in updated_simulation.cells:
        es_state[cell.cell_id] = cell.es_state
        prb[cell.cell_id] = cell.dlPrbUsage_percentage
    for ue in updated_simulation.ues:
        sinr[ue.ue_id] = ue.L3servingSINR_dB
        retx[ue.ue_id] = ue.ErrTotalNbrDl
    print(updated_simulation.ues)
    return {
        "ues": [asdict(ue) for ue in updated_simulation.ues],
        "cells": [asdict(cell) for cell in updated_simulation.cells],
        "max_x_max_y": (updated_simulation.max_x, updated_simulation.max_y),
        "sim_id": updated_simulation.sim_id if updated_simulation.sim_id else 'off',
        "es_state": es_state,
        "sinr": sinr,
        "retx": retx,
        "prb": prb,
        "starting_power": updated_simulation.starting_power,
        "current_power": updated_simulation.current_power,
        "maxec": updated_simulation.maxec,
        "totalcurrec": updated_simulation.totalcurrec,
        "simulation_status": updated_simulation.simulation_status,
        "scenario": SimulationManager.get_scenario(),
    }


@influx_data_router.post("/start_simulation")
async def start_simulation(request: Request):
    form_data = await request.json()
    SimulationManager.reset_simulation()
    import glob as _glob
    for _pat in ("scenario-zero-with-jammer","scenario-zero-with_parallel_loging"):
        try:
            subprocess.run(["pkill","-9","-f",_pat],capture_output=True,timeout=5)
        except Exception as _e:
            print("pre-start pkill failed:",_e)
    for _lg in _glob.glob(os.path.expanduser("~/ns-O-RAN-flexric/mmwave-LENA-oran/ns3_run.log")):
        try:
            open(_lg,"w").close()
        except Exception as _e:
            print("log truncate failed:",_e)
    remote_host = os.getenv('NS3_HOST')
    if not remote_host:
        print("NS3_HOST environment variable is not set.")
        return
    fields = [
        "e2TermIp",
        "hoSinrDifference",
        "indicationPeriodicity",
        "simTime",
        "KPM_E2functionID",
        "RC_E2functionID",
        "N_MmWaveEnbNodes",
        #"N_LteEnbNodes",
        "N_Ues",
        "CenterFrequency",
        "Bandwidth",
        "N_AntennasMcUe",
        "N_AntennasMmWave",
        "IntersideDistanceUEs",
        "IntersideDistanceCells",
        "MapSize",
        "PathLossModel",
        "ChannelConditionModel",
        "ShadowingEnabled"
    ]
    mobility_fields = ["speedMin", "speedMax", "mobilityModel"]
    scenario = form_data.get('scenario')
    if not scenario:
        return
    flags = False
    if form_data.get('flags') == 'true':
        flags = True
    if form_data.get('flexric') == 'true':
        arguments = ' '
    else:
        arguments = '--enableE2FileLogging=1 '
    mobility_scenarios = ["scenario-zero", "orange-rf-channel-reconfiguration", "early_scenario-zero-with_parallel_loging"]
    if any(s in scenario for s in mobility_scenarios):
        fields += mobility_fields
    jammer_fields = ["JammerEnabled", "N_Jammers"]
    for _ji in range(4):
        jammer_fields += [
            f"Jammer{_ji}Type", f"Jammer{_ji}X", f"Jammer{_ji}Y",
            f"Jammer{_ji}PowerDbm", f"Jammer{_ji}Start", f"Jammer{_ji}Stop",
            f"Jammer{_ji}PartialRatio", f"Jammer{_ji}DutyCycle"
        ]
    if "jammer" in scenario.lower():
        fields += jammer_fields
    for field in fields:
        value = form_data.get(field)
        if value is not None:
            arguments += f"--{field}={value} "
        elif value is None and field == 'simTime':
            arguments += f"--simTime=100 "
    # gNBTxPower: translate to ns-3 Config::SetDefault CLI form.
    # --ns3::MmWaveEnbPhy::TxPower=<dBm> is picked up by ns-3's
    # CommandLine::Parse() for ANY scenario — no .cc edits needed.
    _gnb_pwr = form_data.get("gNBTxPower")
    if _gnb_pwr is not None:
        arguments += f"--ns3::MmWaveEnbPhy::TxPower={_gnb_pwr} "
    command = f'./ns3 run "{scenario} {arguments}"'
    command = f'curl -X POST -d \'{command}\' http://{remote_host}:38866'
    try:
        print(f'Sending start command: {command}')
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        print("Response from server:")
        print(result.stdout)
        scenario = os.path.split(scenario)[1].split(".")[0]
        SimulationManager.start_simulation(scenario)
    except Exception as e:
        print(f"An error occurred: {e}")
    number_of_ues = int(form_data.get('N_Ues', 2))
    number_of_cells = int(form_data.get('N_LteEnbNodes', 1)) + int(form_data.get('N_MmWaveEnbNodes', 4))
    SimulationManager._simulation = Simulation(number_of_ues, number_of_cells)



@influx_data_router.post("/reset_simulation")
async def reset_simulation():
    SimulationManager.reset_simulation()
    return {"message": "Simulation reset"}


@influx_data_router.post("/stop_simulation")
async def stop_simulation():
    remote_host = os.getenv('NS3_HOST')
    scenario = SimulationManager.get_scenario()
    if not scenario:
        return    
    if not remote_host:
        print("NS3_HOST environment variable is not set.")
        return

    command = f"curl -X POST -d '{scenario}' http://{remote_host}:38867"

    try:
        print(f'Sending stop command: {command}')
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        print("Response from server:")
        print(result.stdout)
        try:
            subprocess.run(["pkill","-9","-f","scenario-zero-with-jammer"],capture_output=True,timeout=5)
            subprocess.run(["pkill","-9","-f","scenario-zero-with-jammer-v3"],capture_output=True,timeout=5)
            subprocess.run(["pkill","-9","-f","scenario-zero-with_parallel_loging"],capture_output=True,timeout=5)
        except Exception as _e:
            print("pkill fallback failed:",_e)
        try:
            requests.post(f"http://{remote_host}:38867/stop/ns3", timeout=5)
        except Exception as _e:
            print("process_manager stop failed:",_e)
        SimulationManager.stop_simulation()
    except Exception as e:
        print(f"An error occurred: {e}")


# ════════════════════════════════════════════════════════════════════════════
# PROCESS MANAGEMENT — start / stop / log-tail for RIC, KPM xApp, localizer
# ════════════════════════════════════════════════════════════════════════════
# Lets the jammer dashboard control the FlexRIC core + xApps from the browser
# instead of needing separate shells. Uses subprocess.Popen with the process
# group flag so we can SIGTERM the whole tree on stop. Logs are tee'd into
# /tmp/flexric-dashboard/ and tailed on demand.

import asyncio
import signal as _pm_signal
import time as _pm_time
from pathlib import Path as _PMPath
from fastapi import Query as _PMQuery

_PM_HOME = _PMPath(os.environ.get("FLEXRIC_HOME", "/home/k3"))
_PM_LOG_DIR = _PMPath("/tmp/flexric-dashboard")
_PM_LOG_DIR.mkdir(exist_ok=True)

# Edit these paths if your build tree lives elsewhere.
_PM_PROCS = {
    "ric": {
        "label": "FlexRIC core (nearRT-RIC)",
        "cmd":   [str(_PM_HOME / "flexric/build/examples/ric/nearRT-RIC")],
        "cwd":   str(_PM_HOME / "flexric/build/examples/ric"),
        "log":   _PM_LOG_DIR / "ric.log",
    },
    "xapp": {
        "label": "KPM monitoring xApp",
        "cmd":   [str(_PM_HOME / "flexric/build/examples/xApp/c/monitor/xapp_kpm_moni")],
        "cwd":   str(_PM_HOME / "flexric/build/examples/xApp/c/monitor"),
        "log":   _PM_LOG_DIR / "xapp.log",
    },
    "localizer": {
        "label": "Jammer localizer (Python xApp)",
        "cmd":   None,  # built dynamically via /process/start_localizer
        "cwd":   str(_PM_HOME / "flexric/build/examples/xApp/c/monitor"),
        "log":   _PM_LOG_DIR / "localizer.log",
    },
    "ns3": {
        # ns-3 itself is launched by gui_trigger.py via the Scenario form;
        # here we only tail its log.
        "label": "ns-3 simulation",
        "cmd":   None,
        "cwd":   None,
        "log":   _PM_HOME / "ns-O-RAN-flexric/mmwave-LENA-oran/ns3_run.log",
    },
}

# runtime handles (Popen instances) keyed by name
_PM_STATE = {n: {"proc": None, "started_at": None} for n in _PM_PROCS}


def _pm_running(name):
    p = _PM_STATE[name]["proc"]
    return p is not None and p.poll() is None


def _pm_status_one(name):
    cfg = _PM_PROCS[name]
    st  = _PM_STATE[name]
    running = _pm_running(name)
    return {
        "name":       name,
        "label":      cfg["label"],
        "manageable": cfg["cmd"] is not None,
        "running":    running,
        "pid":        st["proc"].pid if running else None,
        "uptime_s":   (_pm_time.time() - st["started_at"]) if (running and st["started_at"]) else 0,
        "log_exists": cfg["log"].exists(),
        "log_size":   cfg["log"].stat().st_size if cfg["log"].exists() else 0,
        "log_path":   str(cfg["log"]),
    }


@influx_data_router.get("/process/status")
async def pm_status_all():
    return {n: _pm_status_one(n) for n in _PM_PROCS}


@influx_data_router.get("/process/status/{name}")
async def pm_status(name: str):
    if name not in _PM_PROCS:
        return JSONResponse({"error": f"unknown process '{name}'"}, status_code=404)
    return _pm_status_one(name)


@influx_data_router.post("/process/start/{name}")
async def pm_start(name: str):
    if name not in _PM_PROCS:
        return JSONResponse({"ok": False, "error": f"unknown process '{name}'"}, status_code=404)
    cfg = _PM_PROCS[name]
    if cfg["cmd"] is None:
        return {"ok": False, "error": f"{name} is not startable from here"}
    if _pm_running(name):
        return {"ok": True, "running": True, "pid": _PM_STATE[name]["proc"].pid, "note": "already running"}
    bin_path = cfg["cmd"][-1] if cfg["cmd"][0] == "python3" else cfg["cmd"][0]
    if not os.path.exists(bin_path):
        return {"ok": False, "error": f"binary not found: {bin_path}"}
    try:
        logf = open(cfg["log"], "ab")
        logf.write(f"\n=== START {_pm_time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
        logf.flush()
        proc = subprocess.Popen(
            cfg["cmd"],
            cwd=cfg["cwd"],
            stdout=logf,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        _PM_STATE[name]["proc"] = proc
        _PM_STATE[name]["started_at"] = _pm_time.time()
        return {"ok": True, "running": True, "pid": proc.pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}



@influx_data_router.post("/process/start_localizer")
async def pm_start_localizer(request: Request):
    form = await request.json()
    jam_start  = form.get('jam_start',  '5')
    jam_stop   = form.get('jam_stop',   '35')
    sim_time   = form.get('sim_time',   '40')
    n_jammers  = form.get('n_jammers',  '1')
    kpi_csv    = str(_PM_HOME / 'flexric/build/examples/xApp/c/monitor/kpi_dashboard.csv')
    gnb_csv    = str(_PM_HOME / 'ns-O-RAN-flexric/mmwave-LENA-oran/gnb_positions.csv')
    gt_csv     = str(_PM_HOME / 'ns-O-RAN-flexric/mmwave-LENA-oran/jammer_ground_truth.csv')
    ue_pos     = str(_PM_HOME / 'ns-O-RAN-flexric/mmwave-LENA-oran/ue_position.txt')
    out_dir    = str(_PM_HOME / 'xapp_output_v2')
    cmd = [
        'python3',
        str(_PM_HOME / 'flexric/build/examples/xApp/c/monitor/jammer_xapp_localizer_v2.py'),
        '--kpi-csv',   kpi_csv,
        '--gnb-csv',   gnb_csv,
        '--gt-csv',    gt_csv,
        '--ue-pos',    ue_pos,
        '--out-dir',   out_dir,
        '--jam-start', str(jam_start),
        '--jam-stop',  str(jam_stop),
        '--sim-time',  str(sim_time),
        '--n-jammers', str(n_jammers),
    ]
    cfg = _PM_PROCS['localizer']
    if _pm_running('localizer'):
        return {'ok': True, 'running': True, 'pid': _PM_STATE['localizer']['proc'].pid, 'note': 'already running'}
    try:
        logf = open(cfg['log'], 'ab')
        logf.write(f"\n=== LOCALIZER START {_pm_time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
        logf.write(f"CMD: {' '.join(cmd)}\n".encode())
        logf.flush()
        proc = subprocess.Popen(cmd, cwd=str(cfg['cwd']), stdout=logf,
                                stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        _PM_STATE['localizer']['proc'] = proc
        _PM_STATE['localizer']['started_at'] = _pm_time.time()
        return {'ok': True, 'running': True, 'pid': proc.pid}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@influx_data_router.post("/process/stop/{name}")
async def pm_stop(name: str):
    if name not in _PM_PROCS:
        return JSONResponse({"ok": False, "error": f"unknown process '{name}'"}, status_code=404)
    if not _pm_running(name):
        return {"ok": True, "running": False, "note": "not running"}
    proc = _PM_STATE[name]["proc"]
    try:
        os.killpg(os.getpgid(proc.pid), _pm_signal.SIGTERM)
        for _ in range(30):
            if proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), _pm_signal.SIGKILL)
    except ProcessLookupError:
        pass
    _PM_STATE[name]["proc"] = None
    _PM_STATE[name]["started_at"] = None
    return {"ok": True, "running": False}


@influx_data_router.get("/process/logs/{name}")
async def pm_logs(name: str, request: Request, lines: int = _PMQuery(300, ge=1, le=5000)):
    if name not in _PM_PROCS:
        return JSONResponse({"error": f"unknown process '{name}'"}, status_code=404)
    if request.query_params.get("clear") == "1":
        open(_PM_PROCS[name]["log"], "w").close()
    cfg = _PM_PROCS[name]
    if not cfg["log"].exists():
        return {"name": name, "log": f"[log not yet created — {cfg['log']}]"}
    try:
        with open(cfg["log"], "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 131072))   # last 128 KB
            data = f.read().decode("utf-8", errors="replace")
        return {"name": name, "log": "\n".join(data.splitlines()[-lines:])}
    except Exception as e:
        return {"name": name, "log": f"[error reading log: {e}]"}
