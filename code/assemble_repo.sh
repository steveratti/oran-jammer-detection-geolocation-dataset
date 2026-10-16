#!/usr/bin/env bash
# Copies the files you created/modified into this repo's folder structure.
# Run from inside the new, empty repo folder. Adjust NS / OFF / FIGS if your paths differ.
set -e
NS=~/ns-O-RAN-flexric/mmwave-LENA-oran
OFF=~/jammer_fix_gnb3
FIGS=~/paper_figs

mkdir -p scenario library-patch gui offline-analysis

# --- ns-3 scenarios ---
cp "$NS/scratch/scenario-zero-with-jammer-v3.cc" scenario/ 2>/dev/null || echo "skip: scenario-zero-with-jammer-v3.cc"
cp "$NS/scratch/jammer_gnb3.cc"                   scenario/ 2>/dev/null || echo "skip: jammer_gnb3.cc"

# --- library patch (the PHY file that holds AddJammer/DlSinrWithJammers) ---
cp "$NS/src/mmwave/model/mmwave-enb-phy.cc"       library-patch/ 2>/dev/null || echo "skip: mmwave-enb-phy.cc"

# --- GUI (dashboard) ---
cp "$NS/GUI/src/templates/jammer.html"            gui/ 2>/dev/null || echo "skip: jammer.html"
cp "$NS/GUI/src/http/data_controller.py"          gui/ 2>/dev/null || echo "skip: data_controller.py"
cp "$NS/GUI/process_manager.py"                   gui/ 2>/dev/null || echo "skip: process_manager.py"

# --- offline analysis ---
cp "$OFF/jammer_detect.py"                        offline-analysis/ 2>/dev/null || echo "skip: jammer_detect.py"
cp "$OFF/latency_bench.py"                        offline-analysis/ 2>/dev/null || echo "skip: latency_bench.py"
cp "$FIGS/paper_figures.py"                       offline-analysis/ 2>/dev/null || echo "skip: paper_figures.py"

echo "Done. Review the files, then: git add . && git commit && git push"
