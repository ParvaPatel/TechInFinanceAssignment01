#!/bin/bash
# Runs every scenario in sim/fixtures several times and keeps each run's output.
#
#   bash bench/run.sh <label> [runs]      (runs defaults to 30)
#
# Results go to build/bench/<label>/ (build/ is ignored by git):
#   info.txt                       commit, date, machine and power source
#   <scenario>/<run>/report.txt    what market_maker printed
#   <scenario>/<run>/...           capture.csv, latency_log.csv, orders.txt, decisions.log
#
# Every run's orders are compared with the scenario's .expected file, so a
# variant that changes the trading behaviour stops the benchmark immediately.
set -euo pipefail

label=${1:?usage: bash bench/run.sh <label> [runs]}
runs=${2:-30}
bin=build/market_maker
out_root=build/bench/$label

if [ ! -x "$bin" ]; then
    echo "error: $bin not found; run make first" >&2
    exit 1
fi
if [ -e "$out_root" ]; then
    echo "error: $out_root already exists; choose another label or delete it" >&2
    exit 1
fi
mkdir -p "$out_root"

{
    echo "label:   $label"
    echo "commit:  $(git rev-parse --short HEAD) on $(git branch --show-current)"
    echo "changes: $(git status --porcelain -- app sim Makefile | wc -l | tr -d ' ') uncommitted file(s) in app/, sim/, Makefile"
    echo "date:    $(date)"
    echo "machine: $(sysctl -n machdep.cpu.brand_string)"
    echo "power:   $(pmset -g batt | head -1)"
    echo "runs:    $runs per scenario"
} > "$out_root/info.txt"
cat "$out_root/info.txt"

# Runs go round-robin through the scenarios (run 1 of each, then run 2 of each,
# ...) so that a burst of background activity doesn't hit just one scenario.
for i in $(seq 1 "$runs"); do
    for scn in sim/fixtures/*.scn; do
        name=$(basename "$scn" .scn)
        dir=$out_root/$name/$i
        mkdir -p "$dir"
        "$bin" "$scn" --out "$dir" > "$dir/report.txt"
        if ! diff -q "sim/fixtures/$name.expected" "$dir/orders.txt" > /dev/null; then
            echo "error: $name run $i sent different orders (see $dir/orders.txt)" >&2
            exit 1
        fi
    done
    echo "run $i/$runs done"
done
echo "results in $out_root"
