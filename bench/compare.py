#!/usr/bin/env python3
"""Compares two batches saved by bench/run.sh.

    python3 bench/compare.py <before> <after>

1. Tick-to-trade p50, p90 and p99 per scenario, pooled over all runs.
2. Median handler time of feed messages that sent no order: all of them, and
   those inside the windows where every requote throws (bench/breakdown.py).
3. The original metric: the median of the per-run averages.

Each cell is "before -> after (change)". To judge whether a change is real,
compare it with the difference between two batches of identical code, such
as baseline vs measurement: anything of that size is run-to-run noise.
"""
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from breakdown import THROW_WINDOWS, load  # noqa: E402
from summarize import percentile, read_report, read_run  # noqa: E402


def collect(label):
    root = pathlib.Path("build/bench") / label
    if not root.is_dir():
        sys.exit(f"error: {root} not found")
    data = {}
    for scenario in sorted(p for p in root.iterdir() if p.is_dir()):
        t2t, no_order_md, throwing, averages = [], [], [], []
        start, end = THROW_WINDOWS.get(scenario.name, (None, None))
        for run in sorted(p for p in scenario.iterdir() if p.is_dir()):
            groups = read_run(run)
            t2t += groups["tick_to_trade"]
            no_order_md += groups["handler_md"]
            averages.append(read_report(run / "report.txt")[1])
            if start is None:
                continue
            deliveries, sends, completed = load(run)
            sent = {i for i, _ in sends}
            for i, (kind, key, sim, arrived) in deliveries.items():
                if kind == "md" and i not in sent and key > 2 and start <= sim < end:
                    throwing.append(completed[(kind, key)] - arrived)
        data[scenario.name] = {"t2t": sorted(t2t), "no_order_md": no_order_md,
                               "throwing": throwing, "averages": averages}
    data["all"] = {"t2t": sorted(v for d in data.values() for v in d["t2t"]),
                   "no_order_md": [v for d in data.values() for v in d["no_order_md"]],
                   "throwing": [], "averages": []}
    return data


def cell(before, after):
    if before is None or after is None:
        return f"{'-':>24}"
    change = f"{(after / before - 1) * 100:+.0f}%" if before else "n/a"
    return f"{before:>7.0f} -> {after:>6.0f} {change:>6}"


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python3 bench/compare.py <before> <after>")
    before, after = collect(sys.argv[1]), collect(sys.argv[2])
    names = [n for n in before if n in after]
    print(f"before: {sys.argv[1]}    after: {sys.argv[2]}    (ns)")

    print("\n1. Tick-to-trade, pooled over all runs")
    print(f"{'scenario':<12}{'p50':>24}{'p90':>24}{'p99':>24}")
    for n in names:
        b, a = before[n]["t2t"], after[n]["t2t"]
        print(f"{n:<12}" + "".join(cell(percentile(b, p), percentile(a, p)) for p in (0.5, 0.9, 0.99)))

    print("\n2. Median handler time, feed messages that sent no order")
    print(f"{'scenario':<12}{'all of them':>24}{'throwing window':>24}")
    for n in names:
        med = lambda xs: statistics.median(xs) if xs else None
        print(f"{n:<12}{cell(med(before[n]['no_order_md']), med(after[n]['no_order_md']))}"
              f"{cell(med(before[n]['throwing']), med(after[n]['throwing']))}")

    print("\n3. Original metric: median of the per-run averages")
    for n in names:
        if before[n]["averages"] and after[n]["averages"]:
            print(f"{n:<12}{cell(statistics.median(before[n]['averages']), statistics.median(after[n]['averages']))}")


if __name__ == "__main__":
    main()
