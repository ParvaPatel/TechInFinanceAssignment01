# Critique: reference write-up

*Written 2026-10-19 by Claude Code at the user's request. Previous: [09-fixes.md](09-fixes.md).*

> **Not the submission.** This is a long-form reference, written by Claude and longer than the one-page limit. The submitted critique ([docs/critique.tex](../docs/critique.tex)) is to be written and condensed by the student. If any wording from here is used, the AI-use statement must say so. Every figure is traceable to a measured batch; see [Sources](#sources).

---

**Collaboration and AI-use statement.** I used Claude Code (Anthropic) throughout this assignment, inside VS Code. It explained the codebase and the market-making concepts, walked me through the message traces of all seven scenarios, and produced an analysis of the design decisions in the design document, which I reviewed before choosing what to critique. It also wrote the code behind my measurements: benchmark scripts that run each scenario 30 times and summarise the results, a revised latency report that measures tick-to-trade, and the two fixes I evaluate (risk checks that return values instead of throwing, and a decision log written off the order path). The experiments ran on my laptop, and I checked the results and the code changes. *[Describe any collaboration with classmates. If you wrote the critique yourself, say so; if any part was drafted by Claude, say which.]*

**1. One possible execution of the hot path.** Take the market data message with sequence number 39 in the `position` scenario, which arrives 15,005,000 ns into the simulation. Participant 2 has just bid for 500 shares at $100.00, and the market maker is already long 500 shares, its position limit. The capture tap records the arrival time and calls `OnMarketData`. The handler copies the header out of the raw bytes with `memcpy`, checks that the sequence number is the one it expects, and passes the AddOrder to the book. The book looks up the order's reference in its flat array, adds 500 shares to the $100.00 slot of the bid ladder, and updates its cached best bid from $99.98 to $100.00. `Requote` then runs the standing risk checks, confirms both sides of the book are present, computes the microprice ($100.005), and recomputes the credit from the volatility sampled at the last timer tick ($0.0123). For the bid, `CheckPosition` sees that another 100 shares would take the position past 500, so it throws a `RiskViolation`; `QuoteSide` catches it and no bid is sent. For the ask, the desired price is $100.02 but the resting order is at $100.01, so `SendQuote`:

- takes the next token;
- appends the quote to the in-memory history;
- writes a line to the decision log with `fprintf`;
- builds a `ReplaceOrder`;
- calls `Send`, where the tap records the order leaving.

Across 30 runs, this order's median tick-to-trade was 1,792 ns. About 1.6 µs of that was the exception and about 0.13 µs the decision log. With both of the fixes described below, it fell to 42 ns, a single tick of the clock.

*Alternative for section 1, a typical execution.* At 1,205,000 ns in the `basic` scenario (sequence number 10), participant 2 bids for 100 shares at $100.01. The tap records the arrival, and `OnMarketData` copies the header out with `memcpy`, checks the sequence number, and decodes the AddOrder. The book looks up reference 10 in its flat array, adds 100 shares to the $100.01 slot of the bid ladder, and updates its cached best bid from $100.00 to $100.01. `Requote` passes the risk checks and computes the microprice as ($100.01 × 300 + $100.05 × 100) / 400 = $100.02, lower than before because the new best bid is thin. With no volatility sampled yet, the credit is $0.01. The bid is already at its desired price of $100.01, so nothing is sent for it. The ask should move from $100.04 to $100.03, so `SendQuote` takes token 5, appends to the history, writes the decision-log line with `fprintf`, builds a `ReplaceOrder` and calls `Send`. Across 30 runs, this order's median tick-to-trade was 354 ns. With the decision log moved off the order path it was 125 ns; the exception fix doesn't apply here, because nothing throws.

| Candidate hot-path example (median order tick-to-trade, 30 runs) | Original | Fix A | Fix B | Both |
|---|---|---|---|---|
| `basic` seq 3: first quotes of a run (cold start, so avoid) | 5,083 ns | 6,312 | 2,209 | 2,375 |
| `basic` seq 10: typical repricing, 1 order | 354 ns | 292 | 125 | 167 |
| `position` seq 39: a check throws, then 1 order | 1,792 ns | 167 | 1,666 | 42 |

**2. A flaw in the evaluation.** The evaluation reports one number: the time from each message's arrival to the end of its handler, averaged over every delivery, timer ticks included. That is not tick-to-trade. Tick-to-trade ends when an order leaves the application, and the capture tap already records that moment for every `Send`, but the report never uses it. Averaging over every delivery also dilutes the result with work that never produces an order. Across the seven scenarios, only 58 of 474 deliveries sent an order, and a delivery that sends nothing takes about 42 ns, against about 375 ns for one that does. A single mean also hides the slowest orders and is unstable: over 30 identical runs, the average for one scenario varied by a factor of up to 4.1, and in one run a single message (the first, at 34.8 µs) made up 73% of the average.

As a result, the metric can rank things backwards. It reports the `quiet` scenario (921 ns) as about as fast as `basic` (910 ns), although `quiet`'s orders are the slowest of all seven scenarios, with a median tick-to-trade of 4.7 µs. It also rewards the wrong optimisation. Removing the exceptions lowered the reported average by 74–87% but improved the median tick-to-trade by only 20%. Moving the decision log off the order path lowered the average by only 4–15% but improved the median tick-to-trade by 70%.

A better evaluation would compute, for every order, the tap's `Send` timestamp minus the arrival timestamp of the message being handled. It would report the count, median, 90th and 99th percentiles, and maximum, pooled over many runs. Deliveries that send nothing, and timer ticks, would be reported separately, because they bear on throughput rather than on tick-to-trade. The logging mechanism itself can stay: it is preallocated, takes one clock read per handler and does no I/O, and our raw data reproduced its averages in all 210 runs. All figures here come from 30 runs of each scenario on an M5 Pro laptop on mains power; on battery, the same code measured 15–31% slower.

**3. A good design decision in the market maker.** Storing orders in a flat array indexed by the exchange's order reference, instead of a hash map, is a good decision. Executed, Cancel, Delete and Replace messages identify an order only by its reference, so the book does this lookup on almost every market data message. With the array, the lookup is a bounds check and one memory load. A `std::unordered_map` would hash the key, find the bucket and follow a pointer to a separately allocated node, often a cache miss. It would also allocate memory on every insert and occasionally rehash the whole table as it grows. The array works because the exchange assigns references sequentially. The table is therefore dense, and recently added orders, which are the ones still live, sit next to each other in memory; each entry is 16 bytes, so four fit in a cache line. The 16 MB table is written once at startup, so its pages are already in memory before trading starts, rather than being faulted in on the hot path. Our measurements reflect this: a market data message that updates the book but sends no order takes about one clock tick (42 ns), lookup included. The main limitation is capacity. A reference above 2²⁰ (about a million) ends the run, so a production version would need a ring buffer indexed by the reference modulo its size.

**4. A flaw in the market maker: risk checks that throw exceptions.** The design document argues that exceptions are free when not thrown, and that once one is thrown, the application is no longer on the hot path. Both parts fail here.

- **The checks fail routinely.** The book check throws on every message while one side of the book is empty. The position check throws on every message while a side is blocked by the position limit. The standing check throws on every message after a halt. By our count from the traces, the seven scenarios throw 73 times, while only 58 deliveries send an order.
- **Throwing is expensive.** The runtime allocates the exception object (and `std::runtime_error` copies its message), walks the stack twice using unwind tables to find the handler, and matches the exception's type. A market data message that sent no order took a median of 1.6–2.3 µs when its check threw, against 41 ns when it didn't. The first throw in the process cost about 35 µs.
- **The throw is still on the hot path.** In the `position` scenario, the bid's check throws, and then the ask's order is sent while handling the same message, so that order waits for the exception. And when a sequence gap halts trading, the cancels are sent from inside the `catch` block.

The fix is for each check to return a `RiskError` value, with the type marked `[[nodiscard]]`, so that ignoring a check produces a compiler warning. That keeps the safety argument the document makes for exceptions. With this change:

- orders and decision logs were identical in every scenario;
- failed checks took 41 ns;
- the halt's cancels went out in a median of 208 ns instead of 3.2 µs;
- orders sent after a failed bid check took 167 ns instead of 1.8 µs.

The typical order did not get measurably faster, though. And the first order of each run became about 28% slower: part of the one-time startup cost that the first exception used to pay now lands on it instead.

**5. A second flaw in the market maker: writing the decision log before every send.** The design document justifies this as a write-ahead log: if the process dies mid-send, the log still shows what the application meant to have on the exchange. But the logging happens inside the tick-to-trade window of every order. Each `fprintf` formats six fields as text, locks the file, copies the line into `stdio`'s buffer, and, whenever that buffer fills, makes a `write` system call.

It also doesn't deliver the safety it promises. `fprintf` only copies into a buffer in the process's own memory, and the file isn't flushed until it's closed at exit, so a crash loses the most recent few kilobytes of lines anyway. Real durability would require an `fsync` before every send, which costs milliseconds.

We moved the work off the order path. The log now copies a small fixed-size entry into a buffer reserved before the run, then formats and writes the text on each timer tick and when the run ends. The log came out byte-for-byte identical in all seven scenarios. At most one timer interval (1 ms) of entries is now at risk, comparable to what the original could lose.

The log turned out to cost about 250 ns per order, roughly three quarters of a typical tick-to-trade. The median for orders after the first two of each run fell from 334 ns to 83 ns, and the median tick-to-trade across all scenarios fell from 416 ns to 125 ns. The work didn't disappear: the timer now does it, and the timer's 90th-percentile handler time rose from 42 ns to 500 ns. That's acceptable, because no order is waiting at that point; a production version could use a background thread or a memory-mapped file instead.

With both fixes applied:

- the typical order fell from 334 ns to 83 ns;
- the median tick-to-trade fell from 416 ns to 84 ns;
- the 90th percentile fell from 5.4 µs to 2.4 µs.

**Further work (optional).** The slowest orders are now the first orders of each run, at about 1.9 µs against 83 ns for later ones. That points to the lack of any warm-up for the order path. The quote history's growing vector and the per-message credit calculation are likely smaller remaining costs, which we did not measure.

---

## Sources

All batches: 30 runs × 7 scenarios, M5 Pro, mains power, every run's orders checked against `.expected`. Medians and pooled percentiles use the nearest-rank method.

| Figure | Value | Source |
|---|---|---|
| Hot-path order (position seq 39): original / fix A / fix B / both | 1,792 / 167 / 1,666 / 42 ns | Direct measurement on the four batches; [notes/09](09-fixes.md) §5 |
| Alternative hot-path order (basic seq 10): original / fix A / fix B / both | 354 / 292 / 125 / 167 ns | Direct measurement on the four batches |
| Credit at 15 ms | $0.0123 | Volatility/credit calculation for `position`; recorded in [notes/07](07-design-decisions.md) §4 |
| 58 of 474 deliveries sent an order; 73 throws | — | Trace counts, [notes/06](06-other-scenarios.md) §4, [notes/07](07-design-decisions.md) #9 |
| No-order delivery vs order-sending delivery | 42 vs 375 ns | `baseline` batch, [notes/08](08-measurements.md) §4 |
| Old average varies up to 4.1× | empty_side 1,068–4,385 ns | `baseline`, notes/08 §2 |
| One message = 73% of a run's average | 34,834 ns of 887 ns × 54 deliveries | single `basic` run, notes/08 §6 |
| `quiet` vs `basic`, old average | 921 vs 910 ns | `baseline`, notes/08 §2 |
| `quiet` tick-to-trade median | 4,708 ns | `baseline`, notes/08 §3 |
| Old metric vs real tick-to-trade for the fixes | A −74 to −87% vs −20%; B −4 to −15% vs −70% | [notes/09](09-fixes.md) §4 |
| Raw data reproduces the old averages | 210/210 runs | notes/08 §1 |
| Battery vs mains | 15–31% slower | notes/08 §2 |
| Throwing vs not (no-order feed messages) | 1.6–2.3 µs vs 41 ns | notes/08 §5 |
| First throw in the process | about 35 µs (34,729 ns median) | notes/09 §2 |
| Halt cancels; orders after a failed bid check (fix A) | 3,208 → 208 ns; 1,792 → 167 ns | notes/09 §2 (direct measurement) |
| First order of each run, fix A | 4,646 → 5,959 ns (+28%) | notes/09 §2 |
| Decision log cost | 334 → 83 ns (typical); 416 → 125 ns (p50) | notes/09 §3 |
| Timer p90, fix B | 42 → 500 ns | notes/09 §3 |
| Both fixes | 334 → 83; 416 → 84; 5,417 → 2,416 ns | notes/09 §5–6 |
| First orders after both fixes | 1,896 ns | notes/09 §5 |
