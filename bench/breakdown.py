#!/usr/bin/env python3
"""Two breakdowns of a batch saved by bench/run.sh.

    python3 bench/breakdown.py <label>

A. Cold start: tick-to-trade of the 1st and 2nd market-data order of each run
   (each run is a fresh process) against every later order.
B. Cost of a throw: handler time of feed messages that sent no order, inside
   vs outside the windows in which every requote throws. The windows come
   from the scenario walkthroughs in notes/05 and notes/06:
     gap         after the sequence-gap halt at 8,005,000
     empty_side  no market asks from 5,005,100 to 12,000,000 (book invalid)
     position    bid blocked by the position limit, 14,010,000 to 20,005,000
   Sequence numbers 1 and 2 are skipped everywhere: start-up messages that
   also throw (book invalid) but are cold for other reasons too.
"""
import csv
import pathlib
import statistics
import sys

THROW_WINDOWS = {  # [start, end) in simulated ns
    "gap": (8_005_000, 10**12),
    "empty_side": (5_005_100, 12_000_000),
    "position": (14_010_000, 20_005_001),
}


def load(run):
    deliveries, sends = {}, []
    with open(run / "capture.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["record"] == "delivery":
                key = int(r["sim_time_ns"]) if r["kind"] == "timer" else int(r["seq"])
                deliveries[int(r["delivery"])] = (r["kind"], key, int(r["sim_time_ns"]), int(r["wall_ns"]))
            else:
                sends.append((int(r["delivery"]), int(r["wall_ns"])))
    with open(run / "latency_log.csv", newline="") as f:
        completed = {(r["kind"], int(r["key"])): int(r["completed_ns"]) for r in csv.DictReader(f)}
    return deliveries, sends, completed


def median(ns):
    return f"{statistics.median(ns):>6.0f} ns (n={len(ns)})" if ns else "     - "


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 bench/breakdown.py <label>")
    root = pathlib.Path("build/bench") / sys.argv[1]
    if not root.is_dir():
        sys.exit(f"error: {root} not found")

    print("A. Tick-to-trade by order number within the run (all scenarios)")
    first, second, later = [], [], []
    for run in sorted(root.glob("*/*/")):
        deliveries, sends, _ = load(run)
        t2t = [stamp - deliveries[i][3] for i, stamp in sends if deliveries[i][0] == "md"]
        first += t2t[:1]
        second += t2t[1:2]
        later += t2t[2:]
    print(f"   1st order of each run   median {median(first)}")
    print(f"   2nd order of each run   median {median(second)}")
    print(f"   every later order       median {median(later)}")

    print("\nB. Feed messages that sent no order: handler time when the requote throws vs not")
    for name, (start, end) in THROW_WINDOWS.items():
        throwing, not_throwing = [], []
        for run in sorted((root / name).glob("*/")):
            deliveries, sends, completed = load(run)
            sent = {i for i, _ in sends}
            for i, (kind, key, sim, arrived) in deliveries.items():
                if kind != "md" or i in sent or key <= 2:
                    continue
                ns = completed[(kind, key)] - arrived
                (throwing if start <= sim < end else not_throwing).append(ns)
        print(f"   {name:<11} throwing {median(throwing)}   not throwing {median(not_throwing)}")


if __name__ == "__main__":
    main()
