# Interview preparation

*Written 2026-10-22. Previous: [10-critique-reference.md](10-critique-reference.md).*

**Format** (from friends who've done it): 15–20 minutes, about 7–8 questions. The TA is relaxed; the professor goes deep. The professor reads the critique word by word, then asks about each point:

- where did you see it?
- how did you find it out?
- why does it happen?
- how does your fix solve it?
- why this fix and not another?
- how do you justify it?

**How to answer every question**, in about 30–60 seconds:

1. **The claim**, in one sentence.
2. **The mechanism:** why it happens, in the machine or the code.
3. **The evidence:** where you saw it and the number you measured.
4. **The method:** how you measured it, and why the number isn't noise.
5. **The fix, and its trade-off or limit.**

The model answers below are for practice, so you can explain each point in your own words. Don't memorise them word for word.

## Contents

1. [Numbers to know by heart](#1-numbers-to-know-by-heart)
2. [Method: how you found and measured things](#2-method-how-you-found-and-measured-things)
3. [The hot path](#3-the-hot-path)
4. [The evaluation flaw](#4-the-evaluation-flaw)
5. [The good decision: the flat order table](#5-the-good-decision-the-flat-order-table)
6. [Flaw 1: exceptions in the risk checks](#6-flaw-1-exceptions-in-the-risk-checks)
7. [Flaw 2: the decision log before every send](#7-flaw-2-the-decision-log-before-every-send)
8. [Both fixes, and what's left](#8-both-fixes-and-whats-left)
9. [The eight most likely questions](#9-the-eight-most-likely-questions)
10. [Glossary: every term in the critique](#10-glossary-every-term-in-the-critique)

---

## 1. Numbers to know by heart

| Topic | Number |
|---|---|
| Method | 30 runs × 7 scenarios per version, mains power, every run's orders checked; 1,980 tick-to-trade samples per batch |
| Clock resolution | 41.7 ns per tick (24 MHz), so "42 ns" means about one tick |
| Noise between identical batches | p50 0–14%, p90 2–30%, single-cluster medians 0–2%; p99 unusable |
| Deliveries that send an order | 58 of 474 (about 1 in 8) |
| No-order delivery vs order-sending delivery | about 42 ns vs about 375 ns (medians) |
| Old metric instability | up to 4.1× between identical runs; one message = 73% of one run's average |
| `basic`: old metric vs reality | old average 910 ns; tick-to-trade median 292 ns, p90 about 4.9 µs |
| `quiet` | old average 921 ns; tick-to-trade median 4.7 µs (slowest of all seven) |
| Old metric vs real effect of the fixes | A: −74 to −87% vs −20%; B: −4 to −15% vs −70% |
| Throws | 73 throws vs 58 order-sending deliveries (counted from traces) |
| Cost of a throw | 1.6–2.3 µs per throwing message vs 41 ns; first throw about 35 µs |
| Fix A, where it matters | orders after a failed bid check 1,792 → 167 ns; halt cancels 3,208 → 208 ns |
| Fix A, typical order | 334 → 292 ns (within noise); first order 4,646 → 5,959 ns (+28%) |
| Decision log cost | about 250 ns per order: typical order 334 → 83 ns |
| Hot-path order (`basic` seq 10) | 354 ns → 125 ns with fix B |
| Both fixes | median 416 → 84 ns; p90 5.4 → 2.4 µs; typical order 334 → 83 ns |
| What's left | first order of each run about 1.9 µs vs 83 ns |
| Order table | 2²⁰ = 1,048,576 entries × 16 bytes = 16 MiB |
| Battery vs mains | battery 15–31% slower |

---

## 2. Method: how you found and measured things

**"How did you find these flaws?"**

1. **Read and trace.** I read the design document's decisions next to the code, then ran all seven scenarios with `--trace` and followed messages one by one. That's where I saw the risk checks throwing on routine messages (an empty side, a blocked side, every message after a halt), and `fprintf` running inside `SendQuote` before `Send`.
2. **Measure.** I wrote a benchmark that runs each scenario 30 times and checks every run's orders against the expected output. I computed tick-to-trade from the capture tap's own timestamps.
3. **Test each fix.** Each fix went on its own branch and was compared against the same baseline, so each effect is isolated.

**"How do you know it isn't noise?"** I ran the unchanged code twice, as two separate batches. Between them, medians moved by at most 14% and medians of a single cluster by at most 2%. My effects are far outside that:

- throwing messages −97%;
- typical order −75% with fix B.

I don't use p99 for conclusions: with 120–330 orders per scenario, it's just the one to three slowest.

**"Why medians and percentiles, not means?"** The distribution has two modes: cold first orders at 4–6 µs, and steady orders at about 300 ns. A mean blends them and is pulled around by outliers. Percentiles show both the typical case and the tail.

**"Why leave out the first two orders as 'typical'?"** Each run is a fresh process, so its first orders pay one-time costs: setting up the log buffer, the first memory allocations, cold caches. That's 4–6 µs. I report them separately, so start-up and steady state aren't mixed.

**"Does making the app faster change the trading in the simulator?"** No. Simulated time stands still while our code runs, so speed can never change which orders go out or when. That's what lets `make verify` require identical orders. Speed shows up only in wall-clock time. In a real market, faster processing shrinks the window in which our quotes are stale and can be picked off.

**"How do you know your fixes didn't change behaviour?"**

- `make verify` passes 7/7;
- every one of the 210 runs in each batch matched its expected orders;
- the decision log is byte-for-byte identical;
- the unit tests pass.

**"Any limits to your measurements?"**

- It's a laptop on macOS, with no core pinning.
- Every run is short and fresh, so cold-start effects are over-represented.
- The clock's resolution is 41.7 ns.
- The 73 throws are counted from the traces, not by instrumentation.

---

## 3. The hot path

**"Walk me through the execution you described."** `basic`, 1,205,000 ns, sequence 10: participant 2 bids 100 shares at $100.01.

1. The capture tap stamps the arrival (the start of tick-to-trade) and calls `OnMarketData`.
2. It copies the header out with `memcpy`, checks the sequence number, and decodes the AddOrder.
3. `Book::Apply` looks up reference 10 in the flat array, adds 100 shares at the $100.01 rung of the ladder, and updates the cached best bid from $100.00 to $100.01.
4. `Requote` runs the standing check and the book check, computes the microprice ($100.02), and recomputes the credit ($0.01).
5. **Bid:** `CheckPosition` passes, and the bid is already at $100.01, so nothing is sent.
6. **Ask:** the desired price is $100.03, but it's live at $100.04, so `SendQuote`:
   - takes token 5;
   - appends to the history;
   - writes the log line with `fprintf`;
   - builds a `ReplaceOrder` and calls `Send`, where the tap stamps the order leaving (the end of tick-to-trade).

Median 354 ns over 30 runs; 125 ns with fix B.

**"Why did the microprice go down when the best bid went up?"** The microprice weights each price by the *opposite* side's size. The new best bid is only 100 shares against 300 on the ask, so it leans toward the bid, the side more likely to be used up next. Before, it was $100.0285; after, $100.02.

**"Where exactly does tick-to-trade start and end?"** It starts at the tap's stamp just before `OnMarketData` is called, and ends at the tap's stamp at the start of `Send`. Both are taken by the simulator, outside our code.

**"What happens after `Send`?"** The side is marked pending, the handler returns, and the latency log records the finish time. That work is outside this order's window, but it delays the next message, or the second order if the delivery sends two.

**"What would a failed check change?"** In `position`, sequence 39, the bid's position check throws first, and the ask's order then waits for the exception: 1.8 µs instead of 167 ns.

---

## 4. The evaluation flaw

**"What exactly is wrong with the evaluation?"** Three things.

1. **The wrong end point.** It measures to the end of the handler, but tick-to-trade ends at `Send`. The tap records `Send`, and the report never uses it. In a two-order delivery, the first order left a median 166 ns before the handler finished.
2. **The wrong messages.** It averages over every delivery, timer ticks included. Only 58 of 474 deliveries send an order, and the rest cost about 42 ns each, so they dominate.
3. **The wrong statistic.** A single mean. It moved up to 4.1× between identical runs, and in one run the first message alone was 73% of it.

**"Show me it actually misleads."**

- For `basic`, the report says 910 ns. The real median order took 292 ns, and the slowest 10% took 4.9 µs or more.
- `quiet` looks as fast as `basic` (921 ns), but its orders are the slowest of any scenario: a 4.7 µs median.
- It even ranks the fixes backwards: −74 to −87% for removing exceptions, against −20% real; −4 to −15% for the log fix, against −70% real.

**"Why does `quiet` look fast?"** It has 48 deliveries, and only one sends orders: its two orders, both cold first orders. The 47 cheap deliveries dilute them in the average.

**"Why does it rank the fixes backwards?"**

- Fix A removed the 35 µs first throw and made throwing no-order messages 40× cheaper. Those are exactly what dominate an average over every delivery.
- Fix B sped up only the deliveries that send orders, 1 in 8, so the average hardly moves even though every order got 4× faster.

**"Don't no-order messages matter?"** Yes, but for a different reason. In a real system, a slow message delays the next one, so their cost affects throughput and queueing. They should be reported, just separately, not blended into tick-to-trade.

**"How did you compute tick-to-trade?"** From the capture tap's CSV. Each delivery row has the wall time at callback entry. Each send row has the wall time at `Send` and the index of the delivery being handled. For every order, I take its send time minus that delivery's arrival time, grouped by what triggered it (market data, report or timer), and report the count, median, p90, p99 and max. The new C++ report and my Python script agree exactly. The raw data also reproduces the old average in all 210 runs, so I'm sure I understood the original metric.

**"What would you keep?"** The instrumentation. It's preallocated, takes one clock read per handler, does no I/O, and uses the same clock as the tap. The data collection is fine; the definition and the summary are the problem.

**"Wouldn't you still want an average?"** You can show it, but next to the percentiles, never alone. In trading, the slow orders matter most: they're the ones whose quotes go stale and get picked off.

---

## 5. The good decision: the flat order table

**"Why is the array better than a hash map?"**

- **How often:** Executed, Cancel, Delete and Replace identify an order only by its reference, so a lookup happens on almost every feed message.
- **The array:** a bounds check and one memory load.
- **`std::unordered_map`:** hashes the key, finds the bucket, then follows a pointer to a separately allocated node. That's often a cache miss, roughly 100 ns to main memory. It also allocates on every insert, and occasionally rehashes the whole table.

**"16 MB doesn't fit in cache. Isn't that bad?"** Only a small part is ever touched. References are assigned in sequence, so the live orders are the recent ones, sitting next to each other. Those few cache lines stay hot, and the rest of the table isn't touched after startup.

**"Why does it work at all?"** The exchange assigns references sequentially from 1, so the table is dense. If references were random or sparse, the array would waste memory; I'd use an open-addressing hash table or a ring buffer instead.

**"What's the limit?"** A fixed capacity: `kMaxOrderRefs = 1 << 20` in `config.h`, so 2²⁰ entries. A higher reference makes `Lookup` throw `out_of_range`, which ends the run. A real feed passes a million references in a day, so in production I'd reuse slots as a ring buffer indexed by the reference modulo its size.

**"How do you know it's fast?"** Indirectly. A whole feed message that updates the book without sending an order (decode, lookup, ladder, requote) takes a median of about 42 ns, about one clock tick. I didn't time the lookup on its own, and I'd say so.

**"Anything else good about it?"** The constructor writes every entry once at startup, so all its memory pages are mapped before trading begins, and there are no first-touch page faults while messages are handled. If asked for a second good decision: the cached best bid/ask, which turns the strategy's read of the top of book on every requote into copying four numbers.

---

## 6. Flaw 1: exceptions in the risk checks

**"What happens when a C++ exception is thrown? Why is it slow?"**

1. **Allocation.** `__cxa_allocate_exception` allocates memory for the exception object. Here `std::runtime_error` also copies its message string, which is a second allocation.
2. **`__cxa_throw` starts the unwinder, which walks the stack twice:**
   - a **search** pass: for each frame, it reads the unwind tables, and the personality routine checks for a matching `catch`;
   - a **cleanup** pass: it unwinds the frames and runs destructors until it lands in the `catch`.
3. **Type matching** uses runtime type information.
4. **When the `catch` ends,** the exception is destroyed and freed.

That's microseconds of work, against tens of nanoseconds for a normal return.

**"But exceptions are 'zero-cost'."** "Zero-cost" means the *normal* path runs no extra instructions, because the handling information sits in tables. All of the cost is paid when you throw. So exceptions are cheap only if they're rare, and here they aren't.

**"Where did you see them thrown?"** In the traces:

- `empty_side`, while the market has no asks (5 to 12 ms): every message throws "book invalid";
- `position`, while the bid is blocked at +500 (14 to 20 ms): every message throws in `CheckPosition`;
- `gap` and `loss`, after the halt: every message throws in `CheckStanding`.

Counting them gives 73 throws against 58 deliveries that send an order: it throws more often than it trades.

**"How did you measure 1.6–2.3 µs?"** I compared feed messages that sent no order, inside the windows where every requote throws, with the same kind of messages outside them. The medians were 1.6–2.3 µs against 41 ns. Then I confirmed it causally: with fix A, the same messages take 41 ns.

**"Why is the first throw 35 µs?"** One-time set-up: the first throw has to find and load the program's unwind information and resolve the exception-handling functions, all with cold caches. Later throws reuse that.

**"The document says once thrown you've left the hot path. Why is that wrong?"**

- **Position limit:** the bid's check throws, and then the *ask* is quoted on the same message, so its order waits for the exception. Measured: 1.8 µs, against 167 ns without exceptions.
- **The gap halt:** the cancels are sent from inside the `catch` block. Pulling quotes when your data is bad is about the most time-critical thing you do, and it took 3.2 µs instead of 208 ns.

**"Why this fix? What else did you consider?"** Each check returns a `RiskError` enum value marked `[[nodiscard]]`. The alternatives:

| Alternative | Why not |
|---|---|
| `std::expected` | C++23; this project is C++20 |
| A plain `bool` | Loses the reason, which the halt writes to the log |
| Output parameters | Clumsier, and easy to misuse |
| Keep the exceptions with `[[unlikely]]` | Moves code around but doesn't remove the throw's cost |

The enum costs nothing at run time, keeps the reason through `Describe()`, and the compiler enforces the check.

**"Isn't that less safe than exceptions?"** It catches the same mistake the document worried about, forgetting to check, but at compile time. The limits:

- it's a warning unless built with `-Werror`;
- it checks that the result is used, not that it's handled correctly;
- exceptions can also be swallowed by an empty `catch`.

**"Did it make orders faster?"** For the orders that met a failed check, yes, about 10×. The typical order didn't change measurably (334 → 292 ns is within noise), because it never throws. And the first order of each run got about 28% slower: part of the one-time start-up work that the first throw used to do, probably setting up the memory allocator, now falls on the first order. That last point is likely, not proven.

**"Why did you keep the other throws in the code?"** An order reference beyond the table, a price outside the ladder, the log file failing to open: these are real errors that never happen in normal operation. Exceptions are fine for genuinely exceptional events.

---

## 7. Flaw 2: the decision log before every send

**"What does `fprintf` do that costs time?"**

- parses the format string;
- converts six numbers to text, digit by digit;
- locks the file;
- copies the line into the `stdio` buffer;
- when the buffer fills, about every 100 lines, makes a `write()` system call: the program switches into the kernel, which copies the buffer into the page cache.

All of this happens before `Send`, inside every order's tick-to-trade.

**"How did you measure 250 ns?"** By testing fix B against the same baseline. The typical order went from 334 to 83 ns, and the median across all scenarios from 416 to 125 ns. Messages that send nothing didn't change (42 ns), which acts as a control: only the order path moved.

**"Explain the durability argument."** There are three places a line can be:

1. the program's `stdio` buffer, lost if the program crashes;
2. the kernel's page cache, which survives a program crash;
3. the disk, which survives a power cut.

`fprintf` only reaches the first. The line moves to the second when the buffer fills or the program exits, and nothing ever calls `fflush` (which moves it to the second now) or `fsync` (which forces it to disk). So if the program crashed mid-send, the line for that order was most likely lost anyway. A real write-ahead log needs `fsync` before every send, which costs milliseconds.

**"Isn't your fix less safe?"** At most one timer interval (1 ms) of entries is at risk. The original could lose up to a buffer's worth, about 100 lines. That's comparable. Also, the cancels sent when trading halts were never logged at all.

**"Why do it on the timer?"** The timer is already the cold path. It runs every 1 ms, never sends a quote, and needs no locking between threads. The cost moved there: the timer's p90 rose from 42 to 500 ns, at a moment when no order is waiting. The log stays byte-for-byte identical.

**"Why not just log after `Send`?"** That takes the log out of this order's window, but the formatting still runs on the trading thread before the next message is handled, and it's still not durable. Deferring it to the timer takes the formatting out of message handling entirely.

**"What would you do in production?"** Write the log from a background thread through a lock-free queue, or use a memory-mapped file: plain memory writes that survive the process dying. For recovery after a crash, use the exchange's own records of your orders.

**"Why did the first order also get faster (4.6 → 2.0 µs)?"** The first `fprintf` used to set up the file's buffer on the first order. Now that happens on the first timer flush.

---

## 8. Both fixes, and what's left

**"Do the two fixes add up?"** Roughly, in absolute terms. On the median, fix A saved 82 ns and fix B 291 ns, a sum of 373 ns; together they saved 332 ns, within noise. They remove different costs (a throw vs a `fprintf`) on mostly different messages, so they don't interact.

**"What's slowest now, and why?"** The first order of each run: about 1.9 µs, against 83 ns later. The order path is cold the first time it runs. That's decision #13, no warm-up. The quote history vector's first allocation (#12) is probably part of it.

**"What would you do with more time?"**

- warm up the order path without sending anything;
- reserve space for the quote history, or bound it as a ring buffer;
- compute the credit once per timer tick instead of on every message;
- measure on a larger workload, on Linux, pinned to one core, with hardware counters to count cache misses.

---

## 9. The eight most likely questions

Practise these aloud until each answer takes under a minute without notes:

1. Walk me through the hot path you described. Where does tick-to-trade start and end?
2. Why is the evaluation's average wrong? Show me it misleads.
3. How did you measure tick-to-trade, and how do you know your numbers aren't noise?
4. Why is the flat array better than a hash map, given that 16 MB doesn't fit in cache?
5. What happens when an exception is thrown, and why is the doc's "off the hot path" claim false here?
6. Why `[[nodiscard]]` status values and not another fix? Is it as safe?
7. Why is the decision log slow, and does it really protect against crashes?
8. What did each fix change, what's left, and what would you do next?

---

## 10. Glossary: every term in the critique

**Tick-to-trade:** the time from a market data message (the tick) reaching the program to the order it causes leaving it (the trade). Here it is measured from the capture tap's arrival stamp, just before `OnMarketData`, to its order-out stamp at the start of `Send`. It does **not** include the simulated network delays, it is **not** the whole handler time, and it is **not** simulated time.

### Market terms

| Term | One-line meaning |
|---|---|
| Market maker | A firm that always shows a price to buy (bid) and to sell (ask), earning the difference |
| Bid / ask | An order to buy / an order to sell |
| Order book | All resting buy and sell orders, sorted by price |
| Best bid / best ask | The highest buy price / the lowest sell price on the book |
| Microprice | Fair value: the best bid and ask weighted by the *opposite* side's size, so it leans toward the thinner side |
| Credit | Distance from fair value to our quotes: at least $0.01, wider when the market is volatile |
| Position / position limit | Shares held / ±500. A side is blocked if one more fill could break the limit |
| Halt | Permanently stop quoting and cancel everything, after a missed feed message or a loss over $100 |
| Order reference | The exchange's ID for a resting order. Later messages about it carry only this ID |

### Messages and code names

| Term | One-line meaning |
|---|---|
| Market data / feed message / tick | An exchange message describing a book change (Add, Executed, Cancel, Delete, Replace) |
| Delivery | Anything handed to our program: a feed message, an execution report, or a timer tick |
| Sequence number | Feed messages are numbered 1, 2, 3…; a skipped number means a lost message |
| Header | The first bytes of a message: type, sequence number, timestamp |
| `memcpy` / decoding | Copying raw message bytes into a struct so the fields can be read safely |
| AddOrder / ReplaceOrder | Feed message: a new order is resting / our request to move an order to a new price |
| Bid ladder | An array with one slot per cent of price, holding the total shares at each price |
| Cached best bid | A copy of the best price and size, kept up to date so it's never searched for |
| `Requote` / `QuoteSide` / `SendQuote` / `Send` | Re-decide both quotes / handle one side / record and send one order / hand the order to the exchange connection |
| Quote history | An in-memory list of every quote sent |
| Timer tick | A callback every 1 ms: samples volatility and checks P&L; never sends quotes |
| Capture tap | The simulator's recorder: stamps when each delivery reaches us and when each order leaves |

### Performance terms

| Term | One-line meaning |
|---|---|
| Hot path | The code between a tick arriving and the order leaving, run on almost every message |
| Handler | The function that processes one delivery (`OnMarketData`, `OnExecutionReport`, `OnTimer`) |
| Mean / median / percentile / tail | Average / middle value / p90 = 90% at or below / the rare slow cases |
| Clock tick | The clock's resolution, 41.7 ns; "42 ns" means about one tick |
| Bounds check | Checking an index is inside the array before reading |
| Memory load | One read from memory |
| Cache / cache miss | Small fast memory by the CPU / data not there, fetched from main memory (about 100 ns vs about 1 ns) |
| Hash map / node / pointer | A table finding items by hashing the key / each item stored separately / an address leading to it |
| Allocate | Ask for new memory at run time: slow and unpredictable |
| Dense table | No gaps: references 1, 2, 3… fill consecutive slots |

### Exception terms

| Term | One-line meaning |
|---|---|
| Exception / throw / catch | `throw` jumps out of the current code to the nearest matching `catch` |
| "Free unless thrown" (zero-cost) | The normal path runs no extra instructions; all the cost is paid on throwing |
| Unwinds the stack | The runtime walks back through the calls, using lookup tables, to find the `catch` and clean up |
| Catch block | Code that runs after an exception is caught; the gap halt's cancels are sent from here |
| Status value / `[[nodiscard]]` | A returned result instead of an exception / the compiler warns if it's ignored |

### Decision log terms

| Term | One-line meaning |
|---|---|
| `fprintf` | Formats values as text and writes them to a file through a buffer |
| File lock | `fprintf` locks the file so two threads can't write at once |
| `write` system call | Handing data from our program to the operating system: a switch into the kernel |
| `stdio` buffer | A 4 KB block (measured) in our program's memory where `fprintf` collects text; written out every ~100 lines |
| Flush / `fflush` | Push the buffer's contents to the operating system now |
| Durability / `fsync` | Surviving a crash or power cut / forcing data onto the disk (milliseconds) |
| Write-ahead log | Record what you're about to do before doing it, so you can recover after a crash |
| Preallocated buffer | Memory reserved before the run, so storing an entry never allocates |
| Typical order | Orders after the first two of each run; the first ones are slowed by start-up costs |

**Most likely to cause a blank:** tick-to-trade, microprice, credit, unwinds the stack, zero-cost, cache miss, `stdio` buffer vs `fsync`, typical order.
