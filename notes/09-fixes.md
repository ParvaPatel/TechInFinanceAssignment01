# Market-maker fixes: results

*Written 2026-10-19. Previous: [08-measurements.md](08-measurements.md).*

Each fix lives on its own branch from `measurement` and is compared with the `measurement` batch, 30 runs × 7 scenarios on mains power, using [bench/compare.py](../bench/compare.py). Every fix must pass `make verify` and the per-run order check in `bench/run.sh`.

## Contents

1. [How to read a comparison: the noise floor](#1-how-to-read-a-comparison-the-noise-floor)
2. [Fix A: risk checks return values instead of throwing](#2-fix-a-risk-checks-return-values-instead-of-throwing)
3. [Fix B: the decision log off the order path](#3-fix-b-the-decision-log-off-the-order-path)
4. [A and B side by side, and what the old metric said](#4-a-and-b-side-by-side-and-what-the-old-metric-said)

---

## 1. How to read a comparison: the noise floor

`baseline` and `measurement` run identical trading code, so the differences between them are pure run-to-run noise (`python3 bench/compare.py baseline measurement`):

| Measure | Moved between identical batches | Rule |
|---|---|---|
| Tick-to-trade p50 | 0–14% | A p50 change under about 15% may be noise |
| Tick-to-trade p90 | 2–30% | A p90 change under about 30% may be noise |
| Tick-to-trade p99 | −67% to +318% | **Don't draw conclusions from it.** With 120–330 orders per scenario, it's just the 1–3 slowest |
| Median of one cluster (e.g. the throwing window) | 0–2% | Very stable |
| `loss` no-order median | +77% | About half of `loss`'s no-order messages throw, so its median jumps between the two clusters. Ignore it |

---

## 2. Fix A: risk checks return values instead of throwing

**Branch:** `fix-exceptions` (commit `b4781f9`). **Decision:** #9 in [notes/07](07-design-decisions.md).

### The change

| | Before | After |
|---|---|---|
| [risk.h](../app/risk/risk.h) | `CheckStanding`, `CheckBook` and `CheckPosition` throw `RiskViolation` on failure | They return a `RiskError` (`None` means OK). The enum is `[[nodiscard]]`, so ignoring a result is a compiler warning |
| [market_maker.cpp](../app/market_maker.cpp) | `try`/`catch` in `Requote` and `QuoteSide` | `if (… != RiskError::None) return;` The halt reason comes from `Describe(error)`, the same text as before |

**Unchanged:**
- **Behaviour:** `make verify` passes 7/7, the tests pass, and every one of the 210 runs matched its `.expected` orders.
- **Decision logs:** byte-for-byte identical for `gap`, `loss` and `position`.
- **Safety:** ignoring a check now produces *"warning: ignoring return value of type 'RiskError' declared with 'nodiscard' attribute"*.

### Results (`python3 bench/compare.py measurement fix-exceptions`)

**The direct effect: messages whose risk check failed**

| Scenario | Before (it threw) | After (it returns) | Change | Noise floor |
|---|---|---|---|---|
| gap (after the halt) | 2,333 ns | 41 ns | **−98%** | ±2% |
| empty_side (book invalid) | 1,708 ns | 41 ns | **−98%** | ±2% |
| position (bid blocked) | 1,625 ns | 41 ns | **−97%** | ±2% |
| First message of each run (seq 1) | 34,729 ns | 250 ns | **−99%** | — |

**Orders that follow a failed check**

| Where | Measure | Before | After | Change | Noise floor |
|---|---|---|---|---|---|
| gap: the halt's cancels, sent after the gap is detected | tick-to-trade p50 | 4,000 ns | 417 ns | **−90%** | 0–14% |
| position: ask orders sent after the bid's check failed | tick-to-trade p90 | 1,917 ns | 625 ns | **−67%** | 2–30% |
| loss: orders around the blocked bid and the halt | tick-to-trade p50 | 459 ns | 334 ns | **−27%** | 0–14% |

**Typical orders:** every order after the first two of a run went from 334 ns to 292 ns (−13%). That's within the noise floor, so we can't claim it.

**A side effect: the first orders of each run got slower.**

| | Before | After |
|---|---|---|
| 1st order of each run | 4,646 ns | 5,959 ns (+28%) |
| 2nd order of each run | 5,709 ns | 7,063 ns (+24%) |

The program's first exception cost about 35 µs, partly one-time start-up work. Some of that work now lands on the first order instead. The likely reason: the first throw used to set up the memory allocator, and now the first order's own allocations (the history vector and the log's buffer) do it. That's a likely explanation, not a proven one. This also explains why tick-to-trade p90 rose in several scenarios: the slowest 10% of orders are mostly first orders. It only affects the very first order after start-up, and it strengthens the case for a warm-up (#13).

### What the old metric would have said

The original "average latency" fell **74–87%** in every scenario. Judged by the old metric, this fix made the program 4–8× faster. The new report shows the real picture:
- failed checks are 40× cheaper;
- the halt's cancels go out 10× faster;
- orders after a blocked side are faster;
- the typical order is unchanged.

The old metric overstated the benefit because it's dominated by the first message and by no-order messages. That's a concrete example for the evaluation critique (#1).

### For the critique and the interview

- **Cost of a throw on this machine:** about 1.6–2.3 µs per message once warm; the first throw in the process about 35 µs.
- **The doc's claim "once thrown, we are no longer in the hotpath" is false, with numbers:**
  - the gap halt's cancels went out in about 4 µs instead of about 0.4 µs;
  - orders after a blocked side were slower by about 1.3 µs at p90.
- **The fix keeps the safety argument** (`[[nodiscard]]`) and the exact behaviour (`make verify`, identical logs).
- **Be honest about the limits:**
  - the typical order didn't get measurably faster;
  - the first order of each run got slower, because start-up costs moved rather than disappeared.

### Reproducing

```sh
git checkout fix-exceptions
make && make verify
bash bench/run.sh fix-exceptions
python3 bench/compare.py measurement fix-exceptions
python3 bench/breakdown.py fix-exceptions
```

---

## 3. Fix B: the decision log off the order path

**Branch:** `fix-decision-log` (commit `2ce0eab`), from `measurement`, *without* fix A. **Decision:** #11 in [notes/07](07-design-decisions.md).

### The change

| | Before | After |
|---|---|---|
| `Record` (every order, inside `SendQuote`, before `Send`) | `fprintf` a formatted line: format six values, lock the file, copy into the `stdio` buffer, and sometimes a `write()` system call | Copy a fixed-size entry into a vector reserved before the run (4,096 entries): no formatting, no lock, no I/O |
| `Note` (halt, reconciliation mismatch) | `fprintf` | The same kind of copy. The text is copied, because a halt reason can point into a short-lived exception |
| Writing the text | Immediately | `Flush()`, called at the end of every timer tick (the cold path) and in the destructor at the end of the run. Same formats, same order |

Files: [decision_log.h](../app/execution/decision_log.h); [market_maker.cpp](../app/market_maker.cpp) (one line in `OnTimer`); and the comment in [market_maker.h](../app/market_maker.h).

**Unchanged:**
- **Behaviour:** `make verify` passes 7/7, the tests pass, and all 210 runs matched their `.expected` orders.
- **The log itself:** `decisions.log` is **byte-for-byte identical in all 7 scenarios**.

**Durability:** the original also buffered its lines, losing up to about 4 KB of `stdio` buffer if the process died. Now at most one timer interval (1 ms) of entries is at risk.

### Results (`python3 bench/compare.py measurement fix-decision-log`)

**Tick-to-trade**

| Measure | Before | After | Change | Noise floor |
|---|---|---|---|---|
| p50, all scenarios | 416 ns | **125 ns** | **−70%** | 0–14% |
| p90, all scenarios | 5,417 ns | **2,625 ns** | **−52%** | 2–30% |
| p50 per scenario | basic 333, loss 459, position 333, sweep 417 ns | 83, 125, 42, 125 ns | **−70% to −87%** | 0–14% |
| Every order after the first two of a run | 334 ns | **83 ns** | **−75%** | — |
| 1st order of each run | 4,646 ns | 1,958 ns | −58% | — |
| 2nd order of each run | 5,709 ns | 2,708 ns | −53% | — |

**What the log cost.** The typical order went from 334 ns to 83 ns. So about **250 ns of every order, three quarters of its tick-to-trade, was the decision log's `fprintf`**. The first orders improved too, because the first `fprintf` also had to set up the file's buffer.

**Unchanged, as predicted:** messages that send no order (median 42 ns), including the throwing ones (1.6–2.3 µs). Fix B doesn't touch them, and fix A is not on this branch.

**Where the work went: the timer.** The formatting moved, it didn't disappear.

| Timer ticks (n = 4,770) | Before | After |
|---|---|---|
| Median | 0 ns | 41 ns |
| p90 | 42 ns | 500 ns |
| p99 | 208 ns | 4,542 ns, mostly each run's first flush, which sets up the file buffer |

The total work is about the same. It now runs when no order is waiting.

### For the critique and the interview

- **Measured cost of the decision log on the order path: about 250 ns per order,** about 75% of the typical tick-to-trade.
- **The doc's safety argument doesn't survive scrutiny:**
  - the original `fprintf` didn't make the log durable either: it was buffered and never flushed;
  - the fix keeps the same kind of guarantee, losing at most 1 ms of entries;
  - true durability would need `fsync`, which takes milliseconds.
- **The trade-off to state:** the log is written up to 1 ms later than before, and the timer tick now does the formatting.
- **Production version:** a background thread, or a memory-mapped file, instead of the timer.

### Reproducing

```sh
git checkout fix-decision-log
make && make verify
bash bench/run.sh fix-decision-log
python3 bench/compare.py measurement fix-decision-log
python3 bench/breakdown.py fix-decision-log
```

---

## 4. A and B side by side, and what the old metric said

| | Fix A: no exceptions | Fix B: log off the order path |
|---|---|---|
| Tick-to-trade p50, all scenarios | 416 → 334 ns (−20%) | 416 → **125 ns (−70%)** |
| Typical order (after the first two) | 334 → 292 ns (−13%, within noise) | 334 → **83 ns (−75%)** |
| Where it helps most | Messages whose check fails (40× cheaper), halt cancels (10× faster), orders after a blocked side | **Every order** |
| **Original metric** (median of per-run averages) | **−74% to −87%** | **−4% to −15%** |

**The original metric ranks the two fixes backwards.** It reports fix A as a 4–8× improvement and fix B as almost nothing. For the latency that matters, how fast orders leave, fix B is by far the bigger win:
- Fix A mostly removes the cost of the first message (a 35 µs first throw) and of messages that send nothing, which is exactly what dominates an average over every delivery.
- Fix B speeds up the orders themselves, which are 1 in 8 deliveries, so the average barely notices.

This is the strongest single piece of evidence for the evaluation critique (#1). An engineer optimising against the original report would pick the wrong fix.
