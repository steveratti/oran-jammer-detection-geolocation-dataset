#!/usr/bin/env bash
# gNB 5 scenario: jammer between gNB 5 (400, 326.8) and gNB 2 (500, 500), 15 UEs.
# Waits for the gNB 3 campaign (run_all.sh) to finish, then runs all seeds x {OFF, 40, 50, 60 dBm},
# then analysis + summary table (separate files: summary_g5.csv, table_g5.csv).
BIN=$HOME/ns-O-RAN-flexric/mmwave-LENA-oran/build/scratch/ns3.42-jammer_gnb3-default
OUT=$HOME/jammer_runs
DETECT=$HOME/jammer_fix_gnb3/jammer_detect.py
FIRST=${FIRST:-1}; LAST=${LAST:-30}; PAR=${PAR:-10}
JX=${JX:-450}; JY=${JY:-413}; NUE=${NUE:-15}

echo ">>> gNB5 script start: $(date). Waiting for the gNB 3 campaign (run_all.sh) to finish..."
echo ">>> gNB 3 campaign finished, starting gNB 5: $(date)"

for D in $OUT/g5_p*_r*; do
  [ -d "$D" ] && grep -q "at time 59.9" "$D/ns3.log" 2>/dev/null && [ -s "$D/MmWaveJammerRx.txt" ] && touch "$D/done"
done

run_one() {
  ON=$1; P=$2; R=$3
  D=$OUT/g5_p${P}_on${ON}_r${R}
  [ -f "$D/done" ] && return
  rm -rf "$D"; mkdir -p "$D" && cd "$D" || return
  "$BIN" --RngRun=$R --jammerOn=$ON --jammerPowerDbm=$P --jammerX=$JX --jammerY=$JY --N_Ues=$NUE \
         --simTime=60 --enableTraces=false --enableE2FileLogging=true > ns3.log 2>&1 && touch done
  echo "$(date +%H:%M) run done: g5_p${P}_on${ON}_r${R}"
}
export -f run_one; export BIN OUT JX JY NUE

echo ">>> gNB5 CAMPAIGN START: $(date)  seeds $FIRST-$LAST, $PAR parallel, jammer ($JX, $JY), $NUE UEs"
for R in $(seq $FIRST $LAST); do
  for CFG in "0 60" "1 40" "1 50" "1 60"; do echo "$CFG $R"; done
done | xargs -P $PAR -L 1 bash -c 'run_one $0 $1 $2'
echo ">>> gNB5 SIMULATIONS DONE: $(date)"

echo ">>> gNB5 ANALYSIS START"
rm -f $OUT/summary_g5.csv
for D in $OUT/g5_p*_r*; do
  [ -f "$D/done" ] || { echo "skip (incomplete): $D"; continue; }
  python3 $DETECT analyze --run-dir "$D" --methods sdbscan htdbscan centroid minsinr jtrilat \
      --summary-csv $OUT/summary_g5.csv > "$D/analysis.txt" 2>&1
done
python3 $DETECT summarize --summary-csv $OUT/summary_g5.csv --out $OUT/table_g5.csv
echo ">>> gNB5 ALL DONE: $(date)   Table: $OUT/table_g5.csv"
