#!/usr/bin/env python3
"""Summarises the runs saved by bench/run.sh.

    python3 bench/summarize.py <label>

For each scenario: the number of runs, the number of messages per run, and
the lowest, median and highest of the per-run "average latency" figures
printed by the original latency report.
"""
import pathlib
import re
import statistics
import sys


def read_report(path):
    text = path.read_text()
    messages = int(re.search(r"messages: (\d+)", text).group(1))
    average = float(re.search(r"average latency: ([0-9.eE+-]+) ns", text).group(1))
    return messages, average


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 bench/summarize.py <label>")
    root = pathlib.Path("build/bench") / sys.argv[1]
    if not root.is_dir():
        sys.exit(f"error: {root} not found")

    info = root / "info.txt"
    if info.exists():
        print(info.read_text())

    print("Original report: per-run 'average latency' (ns)")
    print(f"{'scenario':<12}{'runs':>6}{'messages':>10}{'min':>10}{'median':>10}{'max':>10}{'max/min':>9}")
    for scenario in sorted(p for p in root.iterdir() if p.is_dir()):
        results = [read_report(r) for r in scenario.glob("*/report.txt")]
        messages = sorted({m for m, _ in results})
        averages = [a for _, a in results]
        print(f"{scenario.name:<12}{len(averages):>6}{','.join(map(str, messages)):>10}"
              f"{min(averages):>10.0f}{statistics.median(averages):>10.0f}{max(averages):>10.0f}"
              f"{max(averages) / min(averages):>9.2f}")


if __name__ == "__main__":
    main()
