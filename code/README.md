# O-RAN Jammer Detection and Geolocation – Dataset and Simulation Code

Dataset and simulation code for the manuscript

> S. A. Ratti, A. Piccioni, F. Graziosi, D. Cassioli, A. Marotta,
> **"An O-RAN-Native xApp Framework for Jammer Detection and Geolocation"**,
> MDPI *Sensors* (manuscript sensors-4613690, under review).

The data were generated with **ns-O-RAN** (ns-3 mmWave module with O-RAN E2 support) extended with a
downlink jamming model. They contain the E2 KPM reports, the per-UE L3 SINR, the UE trajectories and the
ground-truth jammer position of every simulation run, so that jammer detection, jammer localization and
UE localization methods can be evaluated offline.

---

## Contents

| Location | Content |
|---|---|
| [Release v2.0](https://github.com/steveratti/oran-jammer-detection-geolocation-dataset/releases/tag/v2.0) | **Dataset of the revised manuscript**: 8 archives, 30 Monte Carlo runs per configuration, both scenarios (≈ 5.7 GB) |
| `simulation/` | ns-3 scenario, modified ns-3 source files and run scripts used to generate the dataset |
| `v1_original_submission/` | Data of the original submission (single realization per scenario), kept for reference |

The archives are distributed as release assets because they exceed the GitHub file-size limit.

---

## Dataset (Release v2.0)

### Configurations

Each configuration was simulated with 30 independent random seeds (`--RngRun=1 … 30`), which differ in
UE mobility, shadowing, LOS/NLOS state and fading.

**Seeds 1–5 were used only for calibration and parameter tuning; seeds 6–30 were used only for testing.**

| Archive | Scenario | Jammer | EIRP | UEs | Runs |
|---|---|---|---|---|---|
| `gnb3_p60_on0_seeds1-30.tar.gz` | 1 | OFF (jammer-free control) | – | 10 | 30 |
| `gnb3_p40_on1_seeds1-30.tar.gz` | 1 | ON | 40 dBm | 10 | 30 |
| `gnb3_p50_on1_seeds1-30.tar.gz` | 1 | ON | 50 dBm | 10 | 30 |
| `gnb3_p60_on1_seeds1-30.tar.gz` | 1 | ON | 60 dBm | 10 | 30 |
| `gnb5_p60_on0_seeds1-30.tar.gz` | 2 | OFF (jammer-free control) | – | 15 | 30 |
| `gnb5_p40_on1_seeds1-30.tar.gz` | 2 | ON | 40 dBm | 15 | 30 |
| `gnb5_p50_on1_seeds1-30.tar.gz` | 2 | ON | 50 dBm | 15 | 30 |
| `gnb5_p60_on1_seeds1-30.tar.gz` | 2 | ON | 60 dBm | 15 | 30 |

- **Scenario 1:** jammer at (710, 510, 1.5) m, about 14 m from gNB 3.
- **Scenario 2:** jammer at (450, 413, 1.5) m, between gNB 5 and gNB 2 (about 100 m from both).
- The jammer-free runs (`p60_on0`) are the false-alarm control and are also used for UE localization.
  In these runs the jammer is not created; `60` is only the default value of the power parameter.

### Download and verification

```bash
# download the archives and SHA256SUMS.txt from the release page, then
sha256sum -c SHA256SUMS.txt
tar -xzf gnb3_p40_on1_seeds1-30.tar.gz
```

### Archive layout

Each archive contains one folder per run:

```
Scenario 1:  p<EIRP>_on<0|1>_r<seed>/       e.g.  p40_on1_r17/
Scenario 2:  g5_p<EIRP>_on<0|1>_r<seed>/    e.g.  g5_p40_on1_r17/
```

### Files in each run folder

| File | Description |
|---|---|
| `jammer.txt` | Ground truth of the run: `x,y,z,power_dbm,jammer_on,rng_run` |
| `MmWaveSinrTime.txt` | L3 SINR of every UE towards every cell over time (input of the jammer-detection and UE-localization methods) |
| `MmWaveJammerRx.txt` | Jammer power received by each UE, as computed by the simulator. **Ground truth only**: it is not used by the estimators in the paper |
| `ue_position.txt` | True UE positions over time (used for scoring and to emulate network-reported positions) |
| `ues.txt` | Initial UE positions |
| `gnbs.txt`, `enbs.txt` | gNB and LTE eNB information over time (positions, cell IDs) |
| `cu-cp-cell-*.txt`, `cu-up-cell-*.txt`, `du-cell-*.txt` | E2SM-KPM reports logged per cell (E2 file logging); cell 1 is the LTE anchor eNB, cells 2–5 are the gNBs |
| `DlMacStats.txt`, `DlTxPhyStats.txt`, `RlcAmBufferSize.txt`, `X2Stats.txt`, `*E2*Stats*.txt`, `LteUlSinrStats.txt`, `CellIdStats.txt`, `MmWaveSwitchStats.txt` | Standard ns-3 mmWave / LTE traces |
| `ns3.log` | Simulator log |
| `done` | Empty marker file written when the run completed |

### Simulation parameters

| Parameter | Value |
|---|---|
| Simulation time | 60 s |
| Area | 1000 m × 1000 m |
| gNBs (cell IDs 2, 3, 4, 5) | (500, 500), (700, 500), (400, 673.2), (400, 326.8) m |
| Carrier / bandwidth | 3.5 GHz (FR1) / 20 MHz |
| gNB transmit power | 44 dBm |
| Channel model | 3GPP UMi Street Canyon (TR 38.901) |
| UE speed | 3–7 m/s |
| UE noise figure | 9 dB |
| E2 KPM reporting period | 50 ms |
| Jammer | isotropic, continuous, wideband, 1.5 m height, EIRP 40/50/60 dBm |

**Jammer model.** The jammer power received by UE *u* is J<sub>u</sub> = P<sub>J</sub> − PL<sub>UMi</sub>(d<sub>J,u</sub>),
with its own LOS/NLOS state and shadowing, and the L3 SINR reported over E2 becomes
S<sub>u</sub> / (N<sub>u</sub> + J<sub>u</sub>). The jammer therefore affects the measured SINR, the KPM reports and
the handover decisions, but it is not modelled at the transport-block decoding level.

---

## Simulation code (`simulation/`)

```
simulation/
├── scenario/
│   └── jammer_scenario.cc        ns-3 scenario (gNB deployment, UEs, jammer, E2 logging)
├── ns3_modified_files/
│   ├── mmwave-enb-phy.h          modified ns-3 mmWave gNB PHY (jammer power added to the reported SINR)
│   ├── mmwave-enb-phy.cc
│   └── jammer_sinr.patch         the same changes as a patch against the original files
└── run_scripts/
    ├── run_all.sh                Scenario 1 campaign (30 seeds × {OFF, 40, 50, 60 dBm})
    └── run_all_gnb5.sh           Scenario 2 campaign (30 seeds × {OFF, 40, 50, 60 dBm})
```

### Base software

- ns-O-RAN with the `mmwave-LENA-oran` module:
  <https://github.com/MinaYonan123/mmwave-LENA-oran>, commit `0ae720c` (ns-3.42).

### Reproducing the dataset

```bash
cd ~/ns-O-RAN-flexric/mmwave-LENA-oran          # ns-O-RAN installation

# 1) add the jammer to the gNB PHY (either apply the patch ...)
git apply --check /path/to/simulation/ns3_modified_files/jammer_sinr.patch
git apply         /path/to/simulation/ns3_modified_files/jammer_sinr.patch
#    (... or copy mmwave-enb-phy.h/.cc into src/mmwave/model/)

# 2) add the scenario (the run scripts expect the name jammer_gnb3)
cp /path/to/simulation/scenario/jammer_scenario.cc scratch/jammer_gnb3.cc

# 3) build
./ns3 build
```

One run of each scenario:

```bash
BIN=build/scratch/ns3.42-jammer_gnb3-default

# Scenario 1 (default jammer position (710, 510) m, 10 UEs), 50 dBm jammer, seed 7
mkdir -p run_s1 && cd run_s1
../$BIN --RngRun=7 --jammerOn=1 --jammerPowerDbm=50 --simTime=60 \
        --enableTraces=false --enableE2FileLogging=true > ns3.log 2>&1
cd ..

# Scenario 2 (jammer at (450, 413) m, 15 UEs), jammer-free control, seed 7
mkdir -p run_s2 && cd run_s2
../$BIN --RngRun=7 --jammerOn=0 --jammerX=450 --jammerY=413 --N_Ues=15 --simTime=60 \
        --enableTraces=false --enableE2FileLogging=true > ns3.log 2>&1
```

Main command-line options of the scenario:

| Option | Meaning |
|---|---|
| `--RngRun` | Random seed (Monte Carlo realization) |
| `--jammerOn` | 1 = jammer active, 0 = jammer-free control run |
| `--jammerPowerDbm` | Jammer EIRP in dBm |
| `--jammerX`, `--jammerY`, `--jammerZ` | Jammer position in m |
| `--N_Ues` | Number of UEs |
| `--simTime` | Simulated time in s |
| `--enableE2FileLogging` | Write the E2 KPM reports to files instead of sending them to a RIC |

**Full campaigns.** `run_all.sh` and `run_all_gnb5.sh` run all seeds and configurations in parallel
(`PAR` runs at a time) and write one folder per run to `$HOME/jammer_runs`. Edit `BIN`, `OUT` and `PAR`
at the top of each script if needed. Each run takes several hours of CPU time; a full campaign of
120 runs takes 2–3 days with 20 parallel runs. The last step of the scripts calls the jammer-detection
analysis, which is not part of this repository; the simulation part does not depend on it.

---

## Version history

- **v2.0** (October 2026, revised manuscript): 30 Monte Carlo runs per configuration, jammer-free
  control runs, three jammer powers, Scenario 2 jammer at (450, 413) m, simulation code.
- **v1** (original submission): single realization per scenario, in `v1_original_submission/`.

## License

The dataset is released under CC0 1.0 (see `LICENSE`). The files in `simulation/` that are derived from
ns-3 (`ns3_modified_files/`, `scenario/`) are distributed under the GNU GPL v2, like ns-3.

## Contact

Steve Azarsh Ratti – DISIM Department, University of L'Aquila, Italy –
steveazarsh.ratti@graduate.univaq.it
