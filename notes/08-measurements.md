# Measurements: the baseline, seen through the old and new reports

*Written 2026-10-19. Previous: [07-design-decisions.md](07-design-decisions.md).*

Phase 5, steps 1–3: measure the untouched program with the original latency report, fix the evaluation, and measure again. These numbers are the baseline for the market-maker fixes.

## Contents

1. [Setup](#1-setup)
2. [The original metric](#2-the-original-metric)
3. [Tick-to-trade](#3-tick-to-trade)
4. [Handler time by delivery type](#4-handler-time-by-delivery-type)
5. [Breakdown: cold first orders, and the cost of a throw](#5-breakdown-cold-first-orders-and-the-cost-of-a-throw)
6. [Findings](#6-findings)
7. [What this means for the critique](#7-what-this-means-for-the-critique)
8. [Reproducing](#8-reproducing)

---

## 1. Setup

| | |
|---|---|
| Machine | Apple M5 Pro (5 "Super" cores, 10 "Performance" cores), mains power, Low Power Mode off, no other heavy apps |
| Build | The `Makefile` as given (`-O2`), with `SDKROOT` set ([notes/02](02-build-setup.md)) |
| Method | [bench/run.sh](../bench/run.sh): each of the 7 scenarios 30 times, round-robin, with every run's orders checked against its `.expected` file. Raw files are kept in `build/bench/<label>/` (ignored by git) |
| Analysis | [bench/summarize.py](../bench/summarize.py) (sections 2–4) and [bench/breakdown.py](../bench/breakdown.py) (section 5). Percentiles are nearest-rank |
| Validation | The raw files reproduce each run's printed average in 210/210 runs. The new C++ report and the Python script give identical tick-to-trade figures on a sample run |
| Clock | `steady_clock` ticks every 41.67 ns (24 MHz), so every value is a multiple of about 41.7 ns. "0" means less than one tick |

**Batches:**

| Label | Commit | Report | Use |
|---|---|---|---|
| `baseline-battery` | `c4f251b` (main) | original | Superseded: ran on battery |
| **`baseline`** | `c4f251b` (main) | original | **Official baseline**, on mains power |
| `qos` | `fa3611f` (dropped) | original | Tested a "fastest cores" request in `main.cpp`. The change was removed, and these results aren't used |
| **`measurement`** | `bc8b9a8` (`measurement` branch) | new | Same trading code as `baseline`, with the new report. The starting point for every fix branch |

---

## 2. The original metric

The per-run "average latency" printed by the original report, 30 runs per scenario (`baseline`):

| Scenario | Deliveries per run | Lowest (ns) | Median (ns) | Highest (ns) | Highest ÷ lowest | Median on battery (ns) |
|---|---|---|---|---|---|---|
| basic | 54 | 667 | 910 | 2,119 | 3.18 | 1,073 |
| empty_side | 42 | 1,068 | 1,332 | 4,385 | 4.10 | 1,865 |
| gap | 36 | 1,393 | 1,703 | 3,563 | 2.56 | 2,308 |
| loss | 118 | 798 | 900 | 1,176 | 1.47 | 1,301 |
| position | 117 | 531 | 611 | 1,079 | 2.03 | 862 |
| quiet | 48 | 800 | 921 | 1,439 | 1.80 | 1,107 |
| sweep | 59 | 667 | 814 | 1,228 | 1.84 | 1,070 |

---

## 3. Tick-to-trade

For every order sent while handling a market data message: the order's `Send` stamp minus that message's arrival stamp, both from the capture tap. Pooled over all 30 runs, from the `baseline` batch's raw files:

| Scenario | Orders | p50 (ns) | p90 (ns) | p99 (ns) | Max (ns) | Mean (ns) |
|---|---|---|---|---|---|---|
| basic | 270 | 292 | 4,875 | 8,459 | 12,125 | 1,335 |
| empty_side | 180 | 583 | 5,250 | 53,000 | 56,291 | 2,862 |
| gap | 120 | 3,750 | 5,708 | 10,167 | 11,709 | 4,090 |
| loss | 330 | 458 | 4,500 | 6,458 | 8,500 | 1,294 |
| position | 720 | 333 | 1,875 | 6,250 | 14,917 | 857 |
| quiet | 60 | 4,708 | 5,791 | 9,875 | 9,875 | 4,822 |
| sweep | 300 | 417 | 4,833 | 8,958 | 10,458 | 1,320 |
| **all** | **1,980** | **375** | **4,875** | **8,459** | **56,291** | **1,563** |

The `measurement` batch gives the same picture, within run-to-run noise: for all scenarios combined, p50 416, p90 5,417 and p99 11,084 ns.

---

## 4. Handler time by delivery type

Medians, pooled over all runs (`baseline`), in ns:

| Scenario | Order after an exec report (tick-to-trade style) | Delivery sent an order | No order: feed message | No order: report | No order: timer |
|---|---|---|---|---|---|
| basic | 250 | 292 | 42 | 41 | 41 |
| empty_side | – | 625 | **1,583** | 62 | 0 |
| gap | – | 4,167 | **2,208** | 1,167 | 0 |
| loss | 208 | 334 | **812** | 42 | 0 |
| position | 208 | 375 | 42 | 42 | 41 |
| quiet | – | 5,188 | 42 | 42 | 0 |
| sweep | 292 | 459 | 42 | 42 | 41 |
| **all** | **208** | **375** | **42** | **42** | **0** |

---

## 5. Breakdown: cold first orders, and the cost of a throw

From [bench/breakdown.py](../bench/breakdown.py):

**A. Tick-to-trade by order number within the run.** Each run is a fresh process.

| | `baseline` | `measurement` |
|---|---|---|
| 1st order of each run (n = 210) | 4,250 ns | 4,646 ns |
| 2nd order of each run (n = 210), sent in the same delivery as the 1st, so it includes the 1st order's work | 5,312 ns | 5,709 ns |
| Every later order (n = 1,560) | **334 ns** | **334 ns** |

**B. Feed messages that sent no order, when their requote throws vs when it doesn't.** The windows come from the walkthroughs; sequence numbers 1–2 are excluded.

| Scenario | What throws | Median, throwing (`baseline` / `measurement`) | Median, not throwing |
|---|---|---|---|
| gap | Sequence-gap check, after the halt | 2,292 / 2,333 ns (n = 120) | 41 ns (n = 120) |
| empty_side | "Book invalid" (no market asks) | 1,667 / 1,708 ns (n = 150) | 41 ns (n = 180) |
| position | Position limit (bid blocked) | 1,625 / 1,625 ns (n = 180) | 41 ns (n = 900) |

---

## 6. Findings

1. **The original metric is unstable and mostly measures the message mix.** Identical runs differ by up to 4.1×. Scenarios rank by what they're made of (cold start, throws, timer ticks), not by how fast orders leave. In one `basic` run, a single delivery (the first message, 34.8 µs) made up 73% of the 887 ns average.
2. **Sending an order is where the time goes.** A typical delivery that sends nothing takes about 41 ns, about one clock tick. A typical delivery that sends an order takes about 300–450 ns.
3. **Tick-to-trade has two modes.** The median is 375 ns, but the 90th percentile is 4.9 µs. The slow mode is the first orders of each run: **4.3–4.6 µs for the first order, against 334 ns for later ones**, because the order path is cold.
4. **A throw costs about 1.6–2.3 µs per message,** 40–55× the 41 ns of a message that doesn't throw. All three kinds of throw (sequence gap, book invalid, position limit) cost about the same.
5. **Measurement conditions matter.** Running on battery instead of mains power raised every median by 15–31%.
6. **Resolution limit.** With 41.7 ns clock ticks, differences smaller than a tick per sample can't be resolved. Compare distributions over many samples instead.

---

## 7. What this means for the critique

| Decision ([notes/07](07-design-decisions.md)) | Evidence so far |
|---|---|
| #1 Evaluation | Findings 1 and 3. The same runs give "average 910 ns" under the old metric, but tick-to-trade p50 375 ns, p90 4.9 µs and p99 8.5 µs under the new one. The average hides both the typical order and the slow tail |
| #9 Exceptions | Finding 4: about 1.6–2.3 µs per throwing message, on a code path the doc calls free. Together with the counts in notes/07 (73 throws against 58 order-sending deliveries) |
| #13 No warm-up | Finding 3: the first use of the order path is 13–17× slower than later uses |
| #11 Decision log | Not yet isolated. Finding 2 shows the order path costs about 300 ns more than a no-order delivery; fix B will show how much of that is the log |

---

## 8. Reproducing

```sh
export SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
make && make verify
bash bench/run.sh <label>
python3 bench/summarize.py <label>
python3 bench/breakdown.py <label>
```

Next: the market-maker fixes, each on its own branch from `measurement`, compared against the `measurement` batch. A = exceptions → status codes; B = decision log moved off the order path; then A + B.
