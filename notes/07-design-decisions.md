# Design decisions: analysis

*Written 2026-10-19. Previous: [06-other-scenarios.md](06-other-scenarios.md).*

> This is Claude's analysis of the 13 design decisions in the [design doc](../docs/design.pdf), prepared to help with understanding. Cost figures marked *estimate* are typical values, not measurements on this Mac; phase 5 is where they get measured. The assignment requires the critique itself to be written in your own words, and the collaboration statement should say that Claude Code helped analyse the design decisions.

## Contents

1. [Summary](#1-summary)
2. [Recommended picks for the critique](#2-recommended-picks-for-the-critique)
3. [Each decision in detail](#3-each-decision-in-detail)
4. [Suggested hot-path execution for prompt 1](#4-suggested-hot-path-execution-for-prompt-1)
5. [What still needs measuring](#5-what-still-needs-measuring)

---

## 1. Summary

| # | Section | Decision | Verdict | How often it runs |
|---|---|---|---|---|
| 1 | §2.1 | Evaluation: handler finish time minus arrival time, averaged over every delivery | **Bad** | — |
| 2 | §2.2.1 | Flat array indexed by order ref | **Good** | Almost every feed message |
| 3 | §2.2.1 | Price ladder, one slot per cent | **Good**, with caveats | Every change to the book |
| 4 | §2.2.1 | Cached best bid and ask | **Good** | Every requote |
| 5 | §2.2.1 | Decode with `memcpy` | **Good** | Every delivery |
| 6 | §2.2.2 | Fixed-point integer prices | **Good** | Everywhere |
| 7 | §2.2.2 | Credit recomputed on every message | **Bad**, small | Every requote |
| 8 | §2.2.2 | One function for both sides, branching on side | **Neutral** | Every requote |
| 9 | §2.2.3 | Risk checks throw exceptions | **Bad**, major | 73 of 474 deliveries in our runs |
| 10 | §2.2.3 | `Halt` marked `[[gnu::noinline]]` | **Good**, minor | At most once per run |
| 11 | §2.2.4 | Decision log written before every send | **Bad**, major | Every order |
| 12 | §2.2.4 | Quote history kept for the whole run | **Bad**, moderate | Every order |
| 13 | §2.2.5 | No cache warm-up | **Bad**, moderate | — |

Evidence used throughout comes from the scenario walkthroughs ([notes/06](06-other-scenarios.md), section 4). Across all seven scenarios: **474 deliveries, 58 of which sent an order (about 1 in 8), and 73 exceptions thrown.**

---

## 2. Recommended picks for the critique

| Critique prompt | Pick | Runners-up |
|---|---|---|
| Flaw in the evaluation | #1 | — |
| Good decision in the market maker | #2, flat array indexed by ref | #4, cached best bid and ask; #3, price ladder |
| Flaw 1 in the market maker | #9, risk checks throw exceptions | #12, quote history |
| Flaw 2 in the market maker | #11, decision log before every send | #13, no warm-up; #7, credit |

Why these: #1, #9 and #11 have the clearest mechanism, the largest likely cost, a doc rationale that demonstrably fails, and a fix that leaves `make verify` unchanged. #2 is the most substantial good decision and its reasoning holds up.

---

## 3. Each decision in detail

### #1 Evaluation (§2.1): **bad**

**What the doc says.** The capture tap stamps each delivery's arrival. Each handler records a wall-clock timestamp when it finishes. Joining the two gives each handler's duration, and the report averages it over every message. The log is preallocated, with no I/O and one clock read per handler.

**Code.**
- Arrival stamp: [Simulator::Deliver](../sim/runtime/simulator.h#L148).
- Finish stamp: [LatencyLog::Record](../app/evaluation/latency_log.h#L30), called at the end of each handler.
- The average: [PrintLatencyReport](../app/evaluation/analysis.h#L24).
- The send stamp, which the evaluation never uses: [SendPacket](../sim/runtime/simulator.cpp#L19).

**What's wrong:**

1. **Wrong end point.** Tick-to-trade ends when the order leaves (`Send`). This measures to the end of the handler, which includes work done *after* the order left: for example, the second side's quoting after the first side's `Send`, and the latency record itself.
2. **Wrong messages.** It includes every delivery. Only 58 of 474 deliveries in our runs sent an order. The no-order deliveries and the timer ticks dominate the average, even though the design calls `OnTimer` the cold path. A change that slows order sending can hide inside that average. A change that speeds up only the no-order path looks like a win.
3. **Wrong statistic.** A mean hides the slow cases, the tail, which is what matters in trading. In `basic`, the reported average ranged from 1.3 to 2.6 µs across identical runs, and a single number can't show why.

**What's fine.** The instrumentation is cheap and well designed: preallocated, one clock read per handler, no I/O, and the clock is shared with the tap.

**Fix.**
- For each order sent: **tick-to-trade = send time − arrival time of its delivery**, both from the tap.
- Report the count, median, 99th percentile and maximum, over a large workload or many runs. A 99th percentile needs hundreds of samples at least; with 54 samples it's just the maximum.
- Report separately: processing time for no-order deliveries (a throughput measure), and timer ticks.
- Where one delivery sends two orders, report each. The second order's latency includes the first order's send path.

**Likely interview questions.**
- What is tick-to-trade, and where does each end get measured?
- Why not include no-order messages? They matter for throughput and queueing (a slow no-order message delays the next message in a real system), so report them separately. In this simulator, messages are delivered back to back and arrival is stamped at callback entry, so queueing isn't captured anyway.
- Which percentiles would you report, and how many samples do you need?

---

### #2 Flat array indexed by order ref (§2.2.1): **good**

**Code.** The array is allocated in [Book::Book](../app/market_data/book.cpp#L19), lookups go through [Book::Lookup](../app/market_data/book.cpp#L24), and the entry is the `Order` struct in [book.h](../app/market_data/book.h#L45). Each entry is 16 bytes, so 4 fit in a 64-byte cache line. 2²⁰ entries make 16 MB.

**How often.** Every Executed, Cancel and Delete message, twice per Replace, every Add, and every `MarkOwn`.

**Why it's good.**
- **A lookup is a bounds check plus one memory load.** A hash map hashes the key, finds the bucket, then follows a pointer to a separately allocated node, often a cache miss (*estimate*: about 100 ns to main memory). It also allocates on every insert and occasionally rebuilds the whole table as it grows.
- **The exchange assigns refs in increasing order.** The array is dense, and recent orders (the ones still live) sit close together, which is good for the cache.
- **The 16 MB are written once at startup** (each entry gets its default values), so the operating system maps every page before trading starts. No first-touch page faults happen on the hot path.

**Caveats (raise them yourself in the interview).**
- **Hard cap of 2²⁰ refs.** A larger ref makes `Lookup` throw and ends the run. A real trading day produces far more refs, so a production version would use a ring buffer indexed by ref modulo its size, relying on old orders being dead.
- **16 MB of memory.**

**Likely interview questions.** Why is a hash map slower? What's a cache miss, a cache line, a page fault? What if refs weren't sequential?

---

### #3 Price ladder (§2.2.1): **good, with caveats**

**Code.** The `Ladder` struct in [book.h](../app/market_data/book.h#L53), [AddLiquidity](../app/market_data/book.cpp#L100), [RemoveLiquidity](../app/market_data/book.cpp#L117), and `kMaxPrice` in [config.h](../app/config.h#L29). Each side has 200,000 slots × 8 bytes = 1.6 MB.

**Why it's good.** Adding or removing size at a price is one indexed update: no tree to walk, no memory allocation when a new price level appears.

**Caveats.**
- **Fixed range.** A price of $2,000 or more makes `Book::Apply` throw and ends the run. Some real stocks trade above $2,000.
- **3.2 MB of memory**, though only the region near the best prices is touched often.
- **Scan length.** When the best level empties, [RecomputeBest](../app/market_data/book.cpp#L131) scans slot by slot. That's short when levels are a cent apart, but can be long when a side is sparse.

---

### #4 Cached best bid and ask (§2.2.1): **good**

**Code.** `top_` in [book.h](../app/market_data/book.h#L67). It's updated in `AddLiquidity` and `RemoveLiquidity`, and [Requote](../app/market_maker.cpp#L77) reads it through `book_.top()`.

**Why it's good.** The strategy reads the best bid and ask on every requote, and caching makes that a copy of four numbers. This is *denormalisation*: keeping a redundant copy of exactly the data the hot path needs. The cost is extra work on updates, plus the scan when the best level empties.

**Caveat.** The cache has to be kept correct on every update; a bug here means wrong prices. `RecomputeBest` is called on any removal at the best price, even a partial one, though in that case it finds the level immediately.

---

### #5 Decode with `memcpy` (§2.2.1): **good**

**Code.** [sim::Decode](../sim/messages/wire.h#L40) (part of `sim/`, so fixed). It's used throughout `OnMarketData` and `OnExecutionReport`.

**Why it's good.** Casting a byte pointer to a struct pointer is undefined behaviour in C++ (misaligned access, strict aliasing). A `memcpy` with a size known at compile time is turned into a handful of load instructions, so it's correct *and* as fast as a cast.

**Minor costs.** `Decode` checks the size on every call, a branch that's always predicted correctly. The header is copied separately, and then again as part of the full message: 19 extra bytes. Both are negligible.

---

### #6 Fixed-point integer prices (§2.2.2): **good**

**Why it's good.**
- **Integer maths is exact and deterministic,** which is what lets `make verify` compare output exactly.
- **It's the wire format,** so there's no conversion step.
- **It's cheap.** The microprice needs one integer division. Rounding to the tick divides by a constant (100), which compilers turn into a multiply and a shift.

**Note.** The volatility and credit computation uses floating point: `log` on the timer, `sqrt` in the credit. The result is converted back to an integer with `ceil`. Overflow isn't a concern at these magnitudes.

---

### #7 Credit recomputed on every message (§2.2.2): **bad, small**

**Code.** [Requote line 89](../app/market_maker.cpp#L89) calls [CalcCredit](../app/strategy/pricing.h#L57).

**How often.** Every requote with a valid book: most feed messages and reports.

**Cost** (*estimate*). A square root, two multiplications, a `ceil` and a conversion: a few nanoseconds per message, on the path before `Send`.

**Why it's bad.** The inputs (the variance and the sampled mid) change only in `OnTimer`, so the credit is constant between timer ticks. The doc's reason, "so every quote is always priced off the latest volatility estimate", is met just as well by computing it once, in `OnTimer`, when the inputs change.

**Fix.** Compute a `credit_` value at the end of `OnTimer`'s sampling, starting at `kMinCredit`, and have `Requote` read it. Same inputs, same formula, so the output is identical and `make verify` is unchanged.

**Honest size.** It's a few nanoseconds per message: real waste, but small next to #9 and #11.

---

### #8 One function for both sides (§2.2.2): **neutral**

**Code.** [QuoteSide](../app/market_maker.cpp#L95), [CheckPosition](../app/risk/risk.h#L67), [RoundToTick](../app/strategy/pricing.h#L64), `OrderManager::quote`, and the book's helper functions.

**Why it's neutral.**
- `Requote` always calls bid then ask, a perfectly regular pattern that branch predictors handle.
- Many of the `buy ? a : b` choices compile to conditional-select instructions with no branch at all.
- A misprediction would cost about 15 cycles, a few nanoseconds.

**Alternative.** Make the side a template parameter (`template <Side S>`), so it's known at compile time. That removes the branches, but it duplicates the code, which enlarges the instruction-cache footprint. That can cost more than predictable branches. This trade-off is a good point to raise if asked.

---

### #9 Risk checks throw exceptions (§2.2.3): **bad, major**

**Code.**
- `RiskViolation`: [risk.h:32](../app/risk/risk.h#L32).
- The checks: [CheckStanding](../app/risk/risk.h#L48), [CheckBook](../app/risk/risk.h#L58), [CheckPosition](../app/risk/risk.h#L67).
- The catches: in [Requote](../app/market_maker.cpp#L75) and [QuoteSide](../app/market_maker.cpp#L96).

**How often** (my counts from the traces):

| Scenario | "Book invalid" | "Position limit" | After a halt | Total throws | Deliveries that sent an order |
|---|---|---|---|---|---|
| basic | 2 | 0 | 0 | 2 | 11 |
| gap | 2 | 0 | 7 | 9 | 2 |
| loss | 10 | 13 | 10 | 33 | 16 |
| position | 2 | 12 | 0 | 14 | 19 |
| quiet | 3 | 0 | 0 | 3 | 1 |
| empty_side | 9 | 0 | 0 | 9 | 3 |
| sweep | 3 | 0 | 0 | 3 | 6 |
| **Total** | **31** | **25** | **17** | **73** | **58** |

**The app throws more often than it trades.**

**What a throw costs** (*estimate*: around a microsecond or more when warm, much more the first time):
1. Memory is allocated for the exception object. Here a second allocation copies the message string, because `std::runtime_error` stores its own copy.
2. The runtime walks the stack twice using unwind tables: once to find a matching `catch`, once to clean up.
3. The exception's type is matched against the `catch` clause.
4. The memory is freed again.

**The doc's claims, checked:**
- *"Exceptions are free when not thrown."* Mostly true: with table-based exception handling, the normal path runs no extra instructions. The problem is how *often* they are thrown.
- *"Once they are thrown, we are no longer in the hotpath."* **False.**
  - **Position limit:** the blocked side throws, then the other side sends an order on the *same* message. This happened at 15,005,000 and 20,005,000 in `position`, and at 12,025,000, 15,005,000 and 15,025,000 in `loss`.
  - **Gap halt:** the cancels are sent from inside the `catch` block, so pulling quotes after bad data waits for the unwinding.
  - **Book invalid:** no order goes out on that message, but in a real system the time spent delays whatever message arrives next.
- *"Exceptions cannot be accidentally ignored the way a return code can."* A `[[nodiscard]]` return value gives the same protection at compile time.

These conditions are routine business events, not exceptional errors.

**Fix.**
- Each check returns a status, for example `enum class RiskResult { Ok, BookInvalid, … }`, marked `[[nodiscard]]`. The caller branches on it, with the failure path marked `[[unlikely]]`.
- Ignoring the result becomes a compiler warning, or an error with `-Werror`.
- The halt logic stays as it is: the latched flags, and `Halt` called once.
- The decisions are the same, so `make verify` is unchanged.

**Trade-off.** Each call site has to check the result; `[[nodiscard]]` enforces that.

**Likely interview questions.**
- What does "zero-cost" exception handling mean?
- What happens step by step when an exception is thrown?
- How often did throws happen in your runs, and on which paths?
- Is the doc right that a throw takes you off the hot path?
- How do you keep the safety benefit without exceptions?

---

### #10 `Halt` marked `[[gnu::noinline]]` (§2.2.3): **good, minor**

**Code.** The declaration is in [market_maker.h](../app/market_maker.h#L45). It's called from `Requote`'s `catch` block and from `OnTimer`.

**Why it's good.** It runs at most once per run. Keeping it out of line keeps `Requote` and `OnTimer` smaller, so the code that runs on every message packs more densely into the instruction cache. When it does run, the cost is one function call.

**Could add.** `[[gnu::cold]]`, which also moves it to a separate section and tells the compiler that paths leading to it are unlikely.

**Caveat.** The real slowness on the gap-halt path is the exception around it, not the function call.

---

### #11 Decision log written before every send (§2.2.4): **bad, major**

**Code.** [SendQuote](../app/execution/orders.cpp#L13) calls `log_.Record` *before* `session_.Send`. The log uses `fopen` and `fprintf`: [decision_log.h](../app/execution/decision_log.h#L31).

**How often.** Every order (88 across our runs), always inside the tick-to-trade window.

**What it costs** (*estimate*):
- **On every line,** `fprintf` parses the format string, converts six values to text, locks the file, and copies the text into a buffer. That's hundreds of nanoseconds per line.
- **Every few KB,** about every 100 lines, the buffer fills and `fprintf` calls `write()`, a system call into the kernel. That can take microseconds, and longer if the disk is busy.

**The doc's safety argument fails.**
- **The log isn't actually written out.** `fprintf` only fills a buffer inside the program's own memory, and nothing calls `fflush` or `fsync` until the file is closed at exit. If the process dies mid-send, the buffered lines (up to about 100 orders) are lost. The "window in which an order is live with no record of it" already exists, and it's *bigger* than the one the doc is trying to avoid.
- **Real write-ahead durability would need `fflush` plus `fsync` before every send.** `fflush` gets the data into the kernel's page cache, which survives the process dying. Only `fsync` gets it onto the disk, which survives a power cut, and `fsync` takes milliseconds.

**Also:**
- the quote history (#12) records the same fields;
- the cancels sent by `Halt` aren't logged at all;
- in practice, the exchange's own records are what a firm uses to rebuild its order state after a restart.

**Fix options:**
1. Write a small fixed-size binary record into a preallocated buffer, or reuse the quote history. Then format and write the text **off the critical path**: after `Send`, on the timer, in a background thread (allowed, as long as only the simulator thread calls `Send`), or at shutdown.
2. If crash survival is genuinely required, use a **memory-mapped file**. Writes are plain memory stores, nanoseconds each, and the operating system keeps the pages even if the process dies. That's more durable than today's `fprintf` buffer, and much faster.

**Trade-off.** Option 1 keeps the same durability as today, which is effectively none until the buffer flushes, so nothing real is lost. Option 2 adds some complexity in managing the file.

**Likely interview questions.**
- Where does `fprintf`'s data go?
- What's the difference between `fflush` and `fsync`?
- What survives a process crash, and what survives a power cut?
- Wouldn't logging after `Send` open a window? (Yes in principle, but today's design already has a bigger one.)

---

### #12 Quote history kept for the whole run (§2.2.4): **bad, moderate**

**Code.** `history_` is declared in [orders.h](../app/execution/orders.h#L78), appended in [SendQuote](../app/execution/orders.cpp#L12) before `Send`, and read by [Reconcile](../app/market_maker.cpp#L134).

**How often.** Every order, before `Send`.

**What it costs.**
- **Usually,** a 40-byte write.
- **Occasionally, a reallocation.** When the vector runs out of space (after 1, 2, 4, 8, 16… entries), `push_back` allocates a new, larger block and copies *every* existing record across, on the order path. Each spike grows with the length of the run.
- **At production scale** (*estimate*): a million quotes is about 40 MB, and copying that is a few milliseconds in one go.
- **Memory is never freed.**

**The doc's reasoning, checked.** "Needed for end-of-day reconciliation", but nothing in the program reads the history at the end of the run. The timer only reads the entries added since its last tick (it tracks how far it got in `reconciled_`).

**Fix.**
- Reserve space up front. That removes the reallocation spikes, but not the unbounded growth.
- Better: after the timer reconciles new entries, drop them, or use a fixed-size ring buffer.
- Append *after* `Send`.
- If end-of-day records are needed, stream them to disk off the hot path.

**Likely interview questions.** "Amortised O(1)" vs the worst case; why the tail matters; why reserving space alone isn't enough.

---

### #13 No cache warm-up (§2.2.5): **bad, moderate**

**The doc's argument.** The app is small enough to fit in cache, and nearly every message already runs the book and pricing code, so the caches stay warm.

**Why it doesn't hold:**
1. **The order-sending path runs on only about 1 in 8 deliveries** (58 of 474): `SendQuote`, the history, the decision log, encoding, `Send`. It's the coldest part of the code, at exactly the moment speed matters most.
2. **The data isn't small:** a 16 MB order table plus 3.2 MB of ladders.
3. **Real markets have quiet periods.** Other processes, the operating system and interrupts push our code and data out of the caches, and the branch predictor forgets. The first message after a lull, often the big market move, runs cold. Idle cores also slow their clock.
4. **Our runs show the cold-start effect.** These runs are tiny, so cold-start effects dominate, and the averages varied 2× between identical runs.

**Fix.**
- Keep the order path warm: periodically run it on dummy data *without* calling `Send`. That means building the order message and touching the history and log buffers. Also touch the important data at startup.
- In production: pin the thread to a performance core and busy-poll, so the core stays at full speed. Use huge pages for the big tables.

**Trade-off.** Extra CPU work. The warm-up must have no side effects (no orders, no log lines), or it changes behaviour.

**Note.** In this simulator, deliveries come back to back with no idle wall time, so warm-up mainly helps the start of each run. The production argument is the stronger one.

---

## 4. Suggested hot-path execution for prompt 1

Write this in your own words. A good choice is **`position` at 15,005,000 (seq 39: p2 refills its 100.00 bid)**, because it passes through the decisions criticised above:

1. [OnMarketData](../app/market_maker.cpp#L14): decode the header (`memcpy`); check the sequence number; decode the AddOrder.
2. [Book::Apply](../app/market_data/book.cpp#L31): look up ref 34 in the flat array, add 500 shares to the 100.00 rung, and update the cached best bid (99.98 → 100.00).
3. [Requote](../app/market_maker.cpp#L73):
   - standing checks pass, and the book is valid;
   - fair value = 100.005 (integer microprice);
   - credit = $0.0123, recomputed from the timer's inputs.
4. [QuoteSide](../app/market_maker.cpp#L95) for the bid: `CheckPosition` (position +500) **throws** a `RiskViolation`, which is caught. Nothing is sent for the bid.
5. `QuoteSide` for the ask: it should be 100.02 but is live at 100.01, so it calls [SendQuote](../app/execution/orders.cpp#L7):
   - token 25;
   - **history `push_back`**;
   - **decision-log `fprintf`**;
   - build the `ReplaceOrder` (24 → 25);
   - `session_.Send`, where the tap stamps the order-out time.

The simpler alternative is `basic` seq 3 at 5,000 ([notes/03](03-reading-the-trace.md)).

---

## 5. What still needs measuring

Phase 5, in order:

1. **Build the corrected evaluation:** tick-to-trade per order from the tap, reporting the count, median, 99th percentile and maximum, with no-order deliveries and timer ticks reported separately.
2. **Generate a larger workload,** a scenario with thousands of messages, kept outside `sim/`.
3. **Measure the suspects:** the cost per throw and the throw counts; the time spent in `log_.Record`; the history reallocations.
4. **Apply each fix one at a time,** run `make verify`, and compare the distributions over many runs.
