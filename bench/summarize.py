#!/usr/bin/env python3
"""Summarises the runs saved by bench/run.sh.

    python3 bench/summarize.py <label>

Prints three tables:

1. The original report: per scenario, the lowest, median and highest of the
   per-run "average latency" figures.
2. Tick-to-trade, pooled over all runs: for every order sent while handling a
   market data message, the Send stamp minus that message's arrival stamp.
3. Median handler times, pooled over all runs, split the same way as the
   report in app/evaluation/analysis.h.

Tables 2 and 3 are computed from each run's raw files (capture.csv and
latency_log.csv), so they work for any batch, including ones recorded before
the new report existed. Percentiles are nearest-rank, as in the report.
"""
import csv
import math
import pathlib
import re
import statistics
import sys

# Which group an order belongs to, by the kind of delivery that sent it.
ORDER_GROUP = {"md": "tick_to_trade", "report": "after_report", "timer": "after_timer"}


def read_report(path):
    text = path.read_text()
    messages = int(re.search(r"messages: (\d+)", text).group(1))
    average = float(re.search(r"average latency: ([0-9.eE+-]+) ns", text).group(1))
    return messages, average


def read_run(run_dir):
    """Samples (ns) for one run, grouped as in app/evaluation/analysis.h."""
    deliveries = []  # (index, kind, latency-log key, arrival stamp)
    sends = []  # (index of the delivery being handled, Send stamp)
    with open(run_dir / "capture.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["record"] == "delivery":
                kind = row["kind"]
                key = int(row["sim_time_ns"]) if kind == "timer" else int(row["seq"])
                deliveries.append((int(row["delivery"]), kind, key, int(row["wall_ns"])))
            else:
                sends.append((int(row["delivery"]), int(row["wall_ns"])))
    with open(run_dir / "latency_log.csv", newline="") as f:
        completed = {(r["kind"], int(r["key"])): int(r["completed_ns"]) for r in csv.DictReader(f)}

    groups = {name: [] for name in ("tick_to_trade", "after_report", "after_timer", "all",
                                    "handler_sent", "handler_md", "handler_report",
                                    "handler_timer")}
    arrival = {index: (kind, stamp) for index, kind, _, stamp in deliveries}
    sent = set()
    for index, stamp in sends:
        if index in arrival:
            kind, arrived = arrival[index]
            groups[ORDER_GROUP[kind]].append(stamp - arrived)
            sent.add(index)
    for index, kind, key, arrived in deliveries:
        done = completed.get((kind, key))
        if done is None:
            continue
        groups["all"].append(done - arrived)
        groups["handler_sent" if index in sent else "handler_" + kind].append(done - arrived)
    return groups


def percentile(sorted_ns, p):
    rank = math.ceil(p * len(sorted_ns))
    return sorted_ns[max(rank, 1) - 1]


def median_or_dash(ns):
    return f"{statistics.median(ns):.0f}" if ns else "-"


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 bench/summarize.py <label>")
    root = pathlib.Path("build/bench") / sys.argv[1]
    if not root.is_dir():
        sys.exit(f"error: {root} not found")

    info = root / "info.txt"
    if info.exists():
        print(info.read_text())

    scenarios = sorted(p for p in root.iterdir() if p.is_dir())
    pooled = {}
    checked = mismatched = 0

    print("1. Original report: per-run 'average latency' (ns)")
    print(f"{'scenario':<12}{'runs':>6}{'messages':>10}{'min':>10}{'median':>10}{'max':>10}{'max/min':>9}")
    for scenario in scenarios:
        runs = sorted(p for p in scenario.iterdir() if p.is_dir())
        averages, messages = [], set()
        groups = {}
        for run in runs:
            m, average = read_report(run / "report.txt")
            averages.append(average)
            messages.add(m)
            run_groups = read_run(run)
            for name, ns in run_groups.items():
                groups.setdefault(name, []).extend(ns)
            # The raw files must reproduce the printed average.
            raw = run_groups["all"]
            checked += 1
            if abs(sum(raw) / len(raw) - average) > 0.5:
                mismatched += 1
        pooled[scenario.name] = groups
        print(f"{scenario.name:<12}{len(averages):>6}{','.join(map(str, sorted(messages))):>10}"
              f"{min(averages):>10.0f}{statistics.median(averages):>10.0f}{max(averages):>10.0f}"
              f"{max(averages) / min(averages):>9.2f}")

    everything = {}
    for groups in pooled.values():
        for name, ns in groups.items():
            everything.setdefault(name, []).extend(ns)
    rows = list(pooled.items()) + [("all", everything)]

    print("\n2. Tick-to-trade, pooled over all runs (ns)")
    print(f"{'scenario':<12}{'orders':>8}{'p50':>8}{'p90':>8}{'p99':>8}{'max':>9}{'mean':>8}")
    for name, groups in rows:
        ns = sorted(groups["tick_to_trade"])
        print(f"{name:<12}{len(ns):>8}{percentile(ns, 0.5):>8}{percentile(ns, 0.9):>8}"
              f"{percentile(ns, 0.99):>8}{ns[-1]:>9}{statistics.mean(ns):>8.0f}")

    print("\n3. Median handler time, pooled over all runs (ns)")
    print(f"{'scenario':<12}{'order after':>12}{'sent an':>9}{'no order:':>11}{'no order:':>11}{'no order:':>11}")
    print(f"{'':<12}{'exec report':>12}{'order':>9}{'md':>11}{'report':>11}{'timer':>11}")
    for name, groups in rows:
        print(f"{name:<12}{median_or_dash(groups['after_report']):>12}"
              f"{median_or_dash(groups['handler_sent']):>9}{median_or_dash(groups['handler_md']):>11}"
              f"{median_or_dash(groups['handler_report']):>11}{median_or_dash(groups['handler_timer']):>11}")

    print(f"\nCheck: raw files reproduce the printed average in {checked - mismatched}/{checked} runs")


if __name__ == "__main__":
    main()
