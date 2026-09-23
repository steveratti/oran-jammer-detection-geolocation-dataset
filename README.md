# O-RAN-Native Jammer Detection and Geolocation — Dataset

Simulation dataset accompanying an O-RAN-native xApp framework for jammer
detection and geolocation. The data were generated using an NS-3 / O-RAN
simulation environment with a 3GPP Urban Micro (UMi) channel model.

Two attack scenarios are provided:
- **Scenario 1 — jammer near gNB 3:** a localized attack.
- **Scenario 2 — jammer near gNB 5:** a dispersed, multi-cell attack.

## Folder structure

### Detection stage
`MDPI_jammer_gnb_id_3/` and `MDPI_jammer_gnb_id_5/`
- `l3_sinr_log.csv` — L3 SINR telemetry per UE / cell over time.
- `gnbs.txt` — gNB identifiers and positions.
- `ue_position.txt` — ground-truth UE positions.

### Localization stage
`MDPI_near_gnb3_Localization/` and `MDPI_near_gnb5_Localization/`
- `MmWaveSinrTime.txt` — time-series SINR measurements.
- `UeKpmMeasurements.csv` — KPM measurements (RSRP, RSRQ, RSSI, SINR).
- `gnbs.txt` — gNB identifiers and positions.
- `ue_position.txt` — ground-truth UE positions.
- `ue_position_estimated.csv` — estimated UE positions from the localization pipeline.
- `table_II_errors*.csv` — per-UE localization error values.

## License
Released under CC0 1.0 (public domain dedication).
