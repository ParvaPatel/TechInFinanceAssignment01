# Assignment 1: project overview and study notes

*Technologies for Finance, Fall 2026. Written 2026-10-13.*

**Sources read:** [assignment brief](../docs/assignment.pdf), [design doc](../docs/design.pdf), [critique template](../docs/critique.tex), [README](../README.md), and every source file in [`app/`](../app/) and [`sim/`](../sim/).

> These notes describe the project and the task. They don't say which design decisions are good or bad, because working that out is the assignment itself.

## Contents

1. [What the application is](#1-what-the-application-is)
2. [Terminology](#2-terminology)
3. [What you have to do](#3-what-you-have-to-do)
4. [Status and next steps](#4-status-and-next-steps)

---

## 1. What the application is

### In short

It's a **simulated stock exchange and a market-making trading program**, both running inside one C++ process.

- **The exchange** takes orders from scripted "other traders", matches buyers with sellers, and broadcasts every change to its order book.
- **The market maker** reads that broadcast and rebuilds its own copy of the book. It estimates what the stock is worth, keeps one buy order just below that value and one sell order just above it, and moves them as the market moves.

The job isn't the trading. It's to critique how **fast** the program is, without changing a single order it sends.

### The pieces

```
 scripted traders ──(0 µs)──▶ ┌──────────┐ ── market data (5 µs) ──▶ ┌──────────────┐
  (sim/fixtures/*.scn)        │ exchange │ ── exec reports (10 µs) ─▶│ market maker │
                              │  (sim/)  │ ◀── our orders (10 µs) ── │    (app/)    │
                              └──────────┘                           └──────────────┘
```

| Folder | What's in it | Can you change it? |
|---|---|---|
| [sim/exchange/](../sim/exchange/) | Matching engine (price-time priority) | No |
| [sim/messages/](../sim/messages/) | Binary message formats | No |
| [sim/runtime/](../sim/runtime/) | Event loop, the two clocks, the capture tap | No |
| [sim/fixtures/](../sim/fixtures/) | 7 scenarios (`.scn`), plus the exact orders each must produce (`.expected`) | No |
| [app/market_data/](../app/market_data/) | The app's copy of the order book | Yes, but behaviour must stay identical |
| [app/strategy/](../app/strategy/) | Fair value, volatility, credit, rounding | Yes, same rule |
| [app/risk/](../app/risk/) | The 4 risk checks | Yes, same rule |
| [app/execution/](../app/execution/) | Order state, tokens, sending, decision log | Yes, same rule |
| [app/evaluation/](../app/evaluation/) | Latency measurement and the report | Yes |
| [app/market_maker.cpp](../app/market_maker.cpp) | The three handlers that tie everything together | Yes, same rule |
| [app/config.h](../app/config.h) | Strategy parameters (quote size, limits, ladder range) | No: changing them changes the orders |

### How a run works

The app only runs inside three callbacks, which the simulator calls:

- `OnMarketData`: a feed message arrived.
- `OnExecutionReport`: the exchange replied about one of our orders.
- `OnTimer`: fires every 1 ms in all 7 scenarios.

There are **two clocks**, and the difference between them is central to the assignment:

- **Simulated time** is the scenario's schedule. It *freezes* while a callback runs. So no matter how fast or slow the code is, it sends the same orders at the same simulated times. That's why `make verify` can require an identical order stream.
- **Wall-clock time** is real time on the machine, from `sim::WallClockNow()` in nanoseconds. It's the only clock that measures performance.

The **capture tap** ([capture.h](../sim/runtime/capture.h)) records two wall-clock times: when each callback is entered, and when each `Send` is called. It belongs to the simulator, so the app can't influence what it records. Think of it as a network capture taken at a switch.

### Running it

On this Mac, set the SDK first (see [section 4](#4-status-and-next-steps)).

| Command | What it does |
|---|---|
| `make` | Build everything into `build/` |
| `make test` | Run the simulator's unit tests |
| `make verify` | Run every scenario and diff its orders against `.expected` |
| `./build/market_maker sim/fixtures/basic.scn` | Run one scenario; outputs go to `build/out/basic/` |
| `./build/market_maker sim/fixtures/basic.scn --trace` | Same, plus `trace.txt` (slow, so don't measure with it) |
| `./build/sim_replay sim/fixtures/basic.scn` | Show what a scenario does, with no app trading |

Each `market_maker` run prints a latency report and writes:

| File | Contents |
|---|---|
| `capture.csv` | The capture tap: every delivery and every order sent, with wall-clock times |
| `latency_log.csv` | The app's own record of when each callback finished |
| `orders.txt` | Every order the app sent, with its simulated time (this is what `make verify` compares) |
| `decisions.log` | The app's decision log |
| `trace.txt` | Only with `--trace`: every message, human-readable |

### The strategy

This is fixed, so you never change it ([design doc](../docs/design.pdf), Appendix A).

1. **Fair value = the microprice** of the best bid and offer, excluding our own orders: (P_bid·Q_ask + P_ask·Q_bid) / (Q_bid + Q_ask).
2. **Credit**, the distance from fair value we quote at: max($0.01, ⌈2·σ·mid⌉). σ is a volatility estimate that is only updated on the timer.
3. **Quotes:** bid = fair − credit, rounded *down* to the cent; ask = fair + credit, rounded *up*. 100 shares each, as Day orders.
4. **Requote after every feed message and every exec report** (but not on timer ticks):
   - no order on a side: enter one;
   - price differs: replace it;
   - same price: do nothing.

   At most one request can be in flight per side.
5. **Risk:**

   | Condition | Reaction |
   |---|---|
   | Book invalid: a side (excluding ours) is empty, or the book is crossed | Skip this requote; resting orders stay |
   | Sequence gap: a feed sequence number was skipped | Cancel everything; stop quoting for the rest of the run |
   | Position limit: a new 100-share buy could go above +500 (or a sell below −500) | Don't send on that side; the other side keeps quoting |
   | Loss limit: on a timer tick, P&L marked to the sampled mid is below −$100 | Cancel everything; stop quoting for the rest of the run |

### Worked example

The first four lines of [basic.expected](../sim/fixtures/basic.expected):

```
5000 ENTER token=1 BUY 100 @ 100.0100 DAY
5000 ENTER token=2 SELL 100 @ 100.0400 DAY
25000 REPLACE token=1 -> token=3 100 @ 100.0200
45000 REPLACE token=3 -> token=4 100 @ 100.0100
```

**Lines 1–2.** At 5,000 ns the book (excluding us) is 100.00 × 300 bid / 100.05 × 300 ask:

- fair = (100.00·300 + 100.05·300) / 600 = **100.025**
- credit = $0.01, because there are no volatility samples yet (σ = 0)
- bid = 100.015 rounded down = **100.01**; ask = 100.035 rounded up = **100.04**

**Lines 3–4** show why it matters *when* we learn which orders are ours:

- Our two orders reach the exchange at 15,000 ns. The feed shows them to us at 20,000 ns, but the `Accepted` reports carrying their order refs only arrive at 25,000 ns. Until then, they look like someone else's orders.
- At 25,000 ns the bid's `Accepted` is processed while our ask (100.04 × 100) still counts as market liquidity. Fair value = (100.00·100 + 100.04·300) / 400 = 100.03, so the bid wants 100.02. That's line 3.
- The ask's `Accepted` is processed next, and fair value goes back to 100.025, so the bid wants 100.01 again. But the bid's replace is still in flight, so that side waits for its `Replaced` report at 45,000 ns. That's line 4.

To see this timeline message by message, run `./build/market_maker sim/fixtures/basic.scn --trace` and open `build/out/basic/trace.txt`.

---

## 2. Terminology

### Market structure

| Term | Meaning |
|---|---|
| Limit order book | All resting buy and sell orders, sorted by price and then by arrival time |
| Bid / ask (offer) | A buy order / a sell order |
| Best bid and offer (BBO), top of book | The highest bid and the lowest ask |
| Spread, mid | Ask − bid; (bid + ask) / 2 |
| Crossed book | Best bid ≥ best ask. The app treats this as invalid |
| Price level, depth | All orders at one price; the levels behind the best price |
| Tick size, tick grid | The smallest price step ($0.01); the prices that are valid |
| Price-time priority | Best price fills first; at the same price, the earliest order fills first |
| Maker / taker | A resting order "adds liquidity"; the incoming order that trades against it "removes liquidity" (it's the *aggressor*) |
| Market maker | A firm that always shows both a bid and an ask, earns the spread, and carries inventory risk |
| Position (inventory) | Net shares held: positive = long, negative = short |
| Mark-to-market P&L | cash + position × mid |
| Sweep | An aggressive order big enough to clear several price levels |

### Orders

| Term | Meaning |
|---|---|
| Day / IOC | Rests until filled or canceled / fills what it can immediately and cancels the rest |
| Enter / Replace / Cancel | A new order / a new price or size (loses queue position) / reduce or remove |
| Token | The ID *we* choose for an order. Must be unique; assigned 1, 2, 3… |
| Order ref | The ID the *exchange* assigns. We only learn it from `Accepted`/`Replaced`, a full round trip after sending |
| In flight (pending) | Sent, with no response yet |
| Fill / partial fill | The order traded fully / partly |

### Protocols

| Term | Meaning |
|---|---|
| ITCH | NASDAQ's market data format. It's *order-by-order*: each message is about one order (Add / Execute / Cancel / Delete / Replace), so the receiver has to rebuild the book itself |
| OUCH | NASDAQ's order entry format: our requests, and the exchange's replies (the *execution reports*) |
| Sequence number, gap | Feed messages are numbered 1, 2, 3…; a skipped number means a missed message, so our copy of the book could be wrong |
| Packed struct, wire format | Messages are raw bytes at fixed offsets, little-endian. Decoding means copying the bytes into a struct |
| Fixed-point price | An integer with 4 implied decimals: $100.25 = 1,002,500. Exact, with no floating-point rounding |

### Strategy

| Term | Meaning |
|---|---|
| Fair value, microprice | The firm's estimate of the true price; here, a size-weighted average of the bid and ask that leans toward the thinner side |
| Credit | Our half-spread: how far from fair value we buy and sell |
| Log return, EWMA volatility | ln(m / m_prev); an exponentially weighted moving average of squared returns (λ = 0.94) |
| Latched halt | Once tripped, it stays tripped for the rest of the run |

### Performance engineering

| Term | Meaning |
|---|---|
| Tick-to-trade latency | The time from a market data message ("tick") reaching the app to the resulting order leaving it ("trade"). **This is what the brief says to minimise** |
| Hot path / cold path | Code that runs between the tick and the trade on (nearly) every message / code that runs rarely or off that path |
| Mean, median, percentiles (p99, p99.9), tail, jitter | Ways to summarise a latency *distribution*. The tail is the rare slow cases; jitter is how much latency varies |
| Observer effect | Measuring takes time too. Each tap timestamp costs about 20 ns |
| CPU cache (L1/L2/L3), cache line, miss | Small fast memory next to the core, filled in 64-byte lines. L1 takes about 1 ns; a miss all the way to RAM takes about 100 ns |
| Instruction cache vs data cache | Code and data are cached separately. Rarely run code can push hot code out of the cache |
| Warm / cold, page fault | The first touch of code or data is slow; the OS also maps memory lazily, so the first write to a page traps into the kernel |
| Heap allocation, `reserve` | `new`/`malloc` can be slow. `vector::push_back` reallocates and copies everything when it runs out of space; `reserve` allocates up front |
| System call, buffered I/O | `fprintf` writes into a buffer in your program; when the buffer fills, it calls `write()` into the kernel |
| Branch prediction | The CPU guesses which way each `if` will go; a wrong guess costs about 15 cycles |
| Inlining, `[[gnu::noinline]]` | The compiler pastes a function's body into its caller; `noinline` forbids that |
| C++ exceptions ("zero-cost" model) | Nothing extra is paid when no exception is thrown. Throwing allocates the exception object and unwinds the stack using lookup tables, which typically takes microseconds |
| Direct indexing vs hash map | `array[ref]` is a single memory load; `unordered_map` hashes the key and then follows a pointer to a node |
| Denormalisation | Keeping a redundant copy of derived data (such as the best bid/ask) so reads are cheap, at the cost of extra work on every write |

---

## 3. What you have to do

### The task

You play a **performance engineer** at the market maker. The goal is to minimise tick-to-trade latency without changing the strategy: no change to fair value, credit or risk handling. `make verify` enforces this by checking that every scenario produces the same orders, with the same times, prices, sizes and tokens. The deliverable is a **written critique**, not code.

### What you submit

One PDF built from [critique.tex](../docs/critique.tex). Fill in your name and NetID, and don't change the fonts, margins or structure.

- **Page 1 (not counted):** the collaboration and AI-use statement. Say how you worked with classmates, which AI tools you used, and how. That includes Claude Code, for example for setting up the repo, explaining the code and running experiments.
- **Page 2 (one page maximum):** five answers.

| # | Prompt | Scope |
|---|---|---|
| 1 | Describe one possible execution of the hot path | Trace one message through the code |
| 2 | A flaw in the **evaluation**, and a fix | [app/evaluation/](../app/evaluation/), design doc §2.1 |
| 3 | A **good** decision in the market maker | Design doc §2.2 |
| 4 | A flaw in the market maker, and a fix | Design doc §2.2 |
| 5 | A second flaw in the market maker, and a fix | Design doc §2.2 |

### Rules that matter

- Only critique decisions the design doc actually discusses.
- Code changes are optional. You *may* change the market maker and the evaluation to collect numbers that back up your claims. Keep `make verify` passing, and leave `sim/` alone.
- You can use AI to *understand* the code, but **the critique text has to be written by you**. The interview is done without outside help.
- The brief doesn't give a deadline, so check the course site.

### The decisions you'll choose from

These are all the decisions the design doc discusses, listed without verdicts:

| Design doc section | Decision |
|---|---|
| §2.1 Evaluation | Join the tap's entry time with a completion timestamp recorded by each handler; average over every message (feed, reports, timer); preallocated log, one clock read per handler |
| §2.2.1 Book | A flat array indexed by order ref (about 1M slots, 16 MB, zeroed at startup) instead of a hash map |
| | A price ladder: one slot per tick per side, up to $2,000 |
| | A cached top of book; when the best level empties, scan the ladder for the next one |
| | Decode messages with `memcpy` instead of a pointer cast |
| §2.2.2 Pricing | 64-bit fixed-point integer prices |
| | Credit recomputed on every message from the inputs sampled on the timer |
| | One function for both sides that branches on the side |
| §2.2.3 Risk | Risk checks that throw exceptions |
| | `Halt` marked `[[gnu::noinline]]` |
| §2.2.4 Order management | A write-ahead decision log, written before every send |
| | A quote history kept in memory for the whole run and checked on the timer |
| §2.2.5 General | No cache warm-up |

Appendix A.2 says outright that sampling volatility on the timer is a *modelling* decision, not a performance one, so it's out of scope.

### What the interview will test

It's 15 minutes, with no notes and no AI. Expect to:

- **Explain the system in about 2 minutes:** what market making is, `sim/` vs `app/`, the two clocks, and why simulated time can't measure speed.
- **Walk through your hot-path trace** from memory, naming the actual functions and data structures.
- **Answer six things about each point in your critique:**
  1. *Mechanism:* what the CPU, cache, OS or C++ runtime physically does.
  2. *Frequency:* how often it happens per message.
  3. *Size:* how many nanoseconds, ideally measured.
  4. *Fix:* what you'd change.
  5. *Correctness:* why the fix leaves `make verify` unchanged.
  6. *Trade-off:* what the fix gives up, such as safety, durability or simplicity.
- **Defend your numbers:** how you measured, and why that metric is the right one.

---

## 4. Status and next steps

*As of 2026-10-13.*

- **Repo:** commit `5e4c7ca` is the unmodified starter code. `.DS_Store` and `.claude/` are ignored through `.git/info/exclude`, which only exists on this machine.
- **Build:** fixed. The link error was this Mac's toolchain, not the code. In each new terminal window, run this before building:
  ```sh
  export SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
  ```
  Full diagnosis and explanation: [02-build-setup.md](02-build-setup.md).
- **Baseline:** 0 warnings, 20 of 20 unit tests pass, 7 of 7 scenarios pass `make verify`.
- **zsh tip:** by default zsh doesn't accept `#` comments typed or pasted into the terminal, so commented commands (including the ones in the README) fail. `setopt interactivecomments` turns comments on for the current window; adding that line to `~/.zshrc` makes it permanent.

Next:

1. **Run each scenario** and look at what it produces. Done for `basic` ([03-reading-the-trace.md](03-reading-the-trace.md)) and for `gap`, `loss` and `position` (summary: [04-risk-scenarios.md](04-risk-scenarios.md); walkthroughs: [05-risk-walkthroughs.md](05-risk-walkthroughs.md)), and for `quiet`, `empty_side` and `sweep` ([06-other-scenarios.md](06-other-scenarios.md)). All seven scenarios are covered.
2. **Judge the design decisions.** Done; see [07-design-decisions.md](07-design-decisions.md).
3. **Measure.** Baseline and the new tick-to-trade report done; see [08-measurements.md](08-measurements.md).
4. **Market-maker fixes.** Fix A (exceptions) and fix B (decision log) done; see [09-fixes.md](09-fixes.md). Next: A + B combined.
