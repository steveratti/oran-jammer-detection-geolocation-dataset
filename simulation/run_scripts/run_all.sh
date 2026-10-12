#!/usr/bin/env bash
# Saare seeds x {OFF, 40, 50, 60 dBm} ek saath + aakhir mein analysis aur summary table
BIN=$HOME/ns-O-RAN-flexric/mmwave-LENA-oran/build/scratch/ns3.42-jammer_gnb3-default
OUT=$HOME/jammer_runs
DETECT=$HOME/jammer_fix_gnb3/jammer_detect.py
FIRST=${FIRST:-1}; LAST=${LAST:-30}; PAR=${PAR:-12}

# pehle se poore runs (jaise seed 1) dobara na chalein
for D in $OUT/p*_r*; do
  [ -d "$D" ] && grep -q "at time 59.9" "$D/ns3.log" 2>/dev/null && [ -s "$D/MmWaveJammerRx.txt" ] && touch "$D/done"
done

run_one() {
  ON=$1; P=$2; R=$3
  D=$OUT/p${P}_on${ON}_r${R}
  [ -f "$D/done" ] && return
  rm -rf "$D"; mkdir -p "$D" && cd "$D" || return
  "$BIN" --RngRun=$R --jammerOn=$ON --jammerPowerDbm=$P --simTime=60 \
         --enableTraces=false --enableE2FileLogging=true > ns3.log 2>&1 && touch done
  echo "$(date +%H:%M) run poora: p${P}_on${ON}_r${R}"
}
export -f run_one; export BIN OUT

echo ">>> CAMPAIGN SHURU: $(date)  seeds $FIRST-$LAST, $PAR ek saath"
for R in $(seq $FIRST $LAST); do
  for CFG in "0 60" "1 40" "1 50" "1 60"; do echo "$CFG $R"; done
done | xargs -P $PAR -L 1 bash -c 'run_one $0 $1 $2'
echo ">>> SIMULATIONS KHATAM: $(date)"

echo ">>> ANALYSIS SHURU"
rm -f $OUT/summary.csv
for D in $OUT/p*_r*; do
  [ -f "$D/done" ] || { echo "skip (adhoora): $D"; continue; }
  python3 $DETECT analyze --run-dir "$D" --methods sdbscan htdbscan centroid minsinr jtrilat \
      --summary-csv $OUT/summary.csv > "$D/analysis.txt" 2>&1
done
python3 $DETECT summarize --summary-csv $OUT/summary.csv --out $OUT/table.csv
echo ">>> SAB KHATAM: $(date)   Table: $OUT/table.csv"
