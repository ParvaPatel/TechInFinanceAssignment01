# Risk scenarios: message-by-message walkthroughs

*Written 2026-10-18. Previous: [04-risk-scenarios.md](04-risk-scenarios.md), a summary of these same three runs.*

This file follows `gap`, `loss` and `position` message by message, in the same style as [03-reading-the-trace.md](03-reading-the-trace.md). The traces are in `build/out/<name>/trace.txt` after running:

```sh
./build/market_maker sim/fixtures/gap.scn --trace
./build/market_maker sim/fixtures/loss.scn --trace
./build/market_maker sim/fixtures/position.scn --trace
```

The usual rules apply: feed delay 5 µs, order and report delay 10 µs each way, and the app re-decides both quotes after every feed message and every report. Timer ticks never send orders.

## Contents

1. [Key concepts](#1-key-concepts)
2. [gap](#2-gap)
3. [loss, part 1: 0 to 6 ms](#3-loss-part-1-0-to-6-ms)
4. [loss, part 2: 7 ms to the end](#4-loss-part-2-7-ms-to-the-end)
5. [position](#5-position)
6. [Answers to the check-your-understanding questions](#6-answers-to-the-check-your-understanding-questions)

---

## 1. Key concepts

### IOC (immediate-or-cancel)

When an IOC order reaches the exchange:

1. It trades straight away against whatever resting orders match its price (that price or better).
2. Any shares that can't trade at that moment are **cancelled immediately**. They never rest on the book.

The opposite is a **Day** order: whatever doesn't trade immediately rests on the book until it's filled or cancelled. Our app always uses Day orders, because a market maker wants its quotes to sit there and wait.

| Run | Order | Result |
|---|---|---|
| `loss`, 8 ms | IOC sell 600 at 99.89 | 500 trade with p2's bid at 99.90. The other 100 can't trade, since our bid at 99.88 is below the limit, so they're **cancelled** |
| `basic`, 5 ms | **Day** buy 400 at 100.05 | 200 trade. The other 200 **rest** as a new bid at 100.05 |

In the scenarios, trader p4 uses IOC orders to sweep the book. In the exchange code: [exchange.cpp:59](../sim/exchange/exchange.cpp#L59).

### The two halts

Both cancel all our orders and stop quoting **for the rest of the run**.

| | Sequence-gap halt (`gap`) | Loss-limit halt (`loss`) |
|---|---|---|
| Trigger | A feed message is missing | P&L below −$100 |
| Detected in | [OnMarketData](../app/market_maker.cpp#L16), when the next message arrives | [OnTimer](../app/market_maker.cpp#L118), on a timer tick |
| How `Halt` gets called | `Requote` → `CheckStanding` **throws** → caught → `Halt` | `OnTimer` calls `Halt` **directly**, with no exception |
| Afterwards | Every feed message and report throws in `CheckStanding` | Same |

The other two risk rules are **not halts**. Their effect is temporary:

| Rule | Scope | Effect | Lasts |
|---|---|---|---|
| Book invalid | One message | Skip this requote; resting orders stay | Until the book is valid again |
| Position limit | One side | Don't send on that side; the other side keeps quoting | Until the position moves back |

A halt stops *quoting*, not *losing*: the position stays open.

### Position vs P&L

| | Position | P&L (profit and loss) |
|---|---|---|
| What it is | How many shares we hold, net | How much money we've made or lost so far |
| Units | Shares | Dollars |
| Changes when | One of our orders fills (buys add, sells subtract) | We trade, **or** the market price moves |
| Measures | **Risk**: how exposed we are to price moves | **Result**: how well we've done |
| In the code | `position_` in [OrderManager](../app/execution/orders.h#L76), updated in [OnExecuted](../app/execution/orders.cpp#L90) | Computed in [OnTimer](../app/market_maker.cpp#L119) |

> P&L = cash + position × mid

Cash goes down when we buy and up when we sell. The shares are valued at the current mid; this is called *marking to market*.

| Example | Position | P&L | Why |
|---|---|---|---|
| End of `basic` | 0 | +$4.00 | Bought 100 at 100.01 and sold 100 at 100.05. No risk left, profit locked in (**realised** P&L) |
| `loss` at 16 ms | +500 | −$106.50 | Bought 500 at an average of 99.918; the mid is 99.705. The loss exists only on paper until we sell (**unrealised** P&L) |
| Right after a fill at the mid | +100 | about $0 | Plenty of risk, no profit or loss yet |

### The limits

All of them live in [app/config.h](../app/config.h).

| Limit | Value | Checked | If exceeded |
|---|---|---|---|
| **Position limit** (`kPositionLimit`) | 500 shares, long or short | Before sending a new order or replacement, in [CheckPosition](../app/risk/risk.h#L67). It asks whether a 100-share fill could take us past ±500 | That side isn't quoted; an order already resting there is left alone; the other side keeps quoting |
| **Loss limit** (`kLossLimit`) | $100 | Only on timer ticks, against the sampled mid | Permanent halt |

Strategy settings that shape every quote: `kQuoteShares` = 100 (the size of every quote), `kMinCredit` = $0.01 (the minimum distance from fair value), `kCreditK` = 2.0 (how strongly volatility widens the credit).

Capacity limits, which are technical rather than about risk:

- `kMaxPrice` = $2,000. Prices outside the ladder's range end the run with an error.
- `kMaxOrderRefs` ≈ 1 million. This is the size of the order table.
- The exchange's `kMaxOrderShares` = 1,000,000. Bigger orders are rejected.

---

## 2. gap

The scenario file sets `drop_market_data 8`: the simulator throws away feed message 8 before our app sees it.

### Timeline

```
sim time (ns)   exchange / simulator                      our app
         0      4 orders from p2, p3 -> refs 1-4
     5,000                                                feed 1-4 -> ENTER bid 99.99, ENTER ask 100.02
    15,000      our orders arrive -> refs 5, 6
    20,000                                                feed 5, 6 (ours) -> nothing
    25,000                                                2 Accepted -> nothing
 3,000,000      p5 adds a bid at 99.98 -> ref 7
 3,005,000                                                feed 7 -> nothing
 6,000,000      p5 adds an ask at 100.03 -> ref 8,
                feed message 8 DROPPED
 8,000,000      p5 adds a bid at 99.97 -> ref 9
 8,005,000                                                feed 9: GAP -> halt, CANCEL bid, CANCEL ask
 8,015,000      our cancels arrive -> refs 5, 6 removed
 8,020,000                                                feed 10, 11 -> nothing (halted)
 8,025,000                                                2 Canceled -> nothing (halted)
10,000,000      p3 pulls its 100.01 ask
10,005,000                                                feed 12 -> nothing (halted)
12,000,000      p2 bids 100.01
12,005,000                                                feed 13 -> nothing (halted)
1–20 ms                                                   timer every 1 ms; never sends anything
```

### t = 0 to 25,000: quotes join the market

| Side | Price × shares | Ref | Trader |
|---|---|---|---|
| Ask | 100.02 × 400 | 4 | p3 |
| Ask | 100.01 × 500 | 3 | p3 |
| Bid | 100.00 × 500 | 1 | p2 |
| Bid | 99.99 × 400 | 2 | p2 |

The spread is only **1 cent**.

- **Seq 1 and 2** are bids only, so the book is invalid and both are skipped.
- **At seq 3**, fair value = 100.005. bid = 99.995, rounded down to **99.99**; ask = 100.015, rounded up to **100.02**.
- **Our quotes join the market instead of improving it.** In `basic` they landed inside the spread. Here a 1-cent credit on each side puts them *behind* the best prices: our bid joins p2's 400 at 99.99, our ask joins p3's 400 at 100.02, and in both queues we're behind the other trader.
- **No bump.** At 20,000 the feed shows our orders before we know they're ours, but they aren't at the best price, so fair value (which uses only the best bid and ask) doesn't move. Compare `basic`'s bump at 25,000.

### 1 to 7 ms: the dropped message

- **Timer ticks** sample the mid at 100.005. The returns are 0, so the credit stays $0.01. P&L is $0.
- **3,005,000:** p5's bid at 99.98 arrives (seq 7). It's behind the best bid, so nothing changes.
- **6,000,000:** p5 adds an ask at 100.03. The exchange publishes it as seq 8, but the simulator drops it (the `DROP` line, printed when the exchange produced it).

From this point the exchange's book has p5's 100.03 ask and **ours doesn't**. The app can't know until the *next* message arrives.

### t = 8,005,000: the gap is detected

p5's bid at 99.97 arrives as **seq 9**:

1. **[OnMarketData](../app/market_maker.cpp#L14)** expected sequence **8** but got **9**, so it calls `LatchSequenceGap()`. That sets a flag that stays on for the rest of the run. It then sets the expected number to 10, so later messages don't count as new gaps.
2. **The message is still applied.** The 99.97 bid goes into the book.
3. **[Requote](../app/market_maker.cpp#L73)** calls [CheckStanding](../app/risk/risk.h#L48), which **throws** `RiskViolation(SequenceGap)`.
4. **`Requote` catches it** and, since the app hasn't halted yet, calls [Halt](../app/market_maker.cpp#L144).
5. **`Halt`:**
   - sets `halted_`;
   - writes `8005000 market data sequence gap` to `decisions.log`;
   - calls [CancelAll](../app/execution/orders.cpp#L43), which sends `CANCEL token=1 to 0` and `CANCEL token=2 to 0` ("to 0" means reduce to 0 shares, i.e. cancel completely).
6. Back in `OnMarketData`, the finish time goes into the latency log.

So the cancels are sent from inside a `catch` block, after an exception has been thrown and caught.

**Why stop everything?** The app knows a message is missing, but not *which* one. It could have been a new best price or the deletion of the best bid, so the book may now be wrong, and so may any fair value computed from it. Real systems usually try to recover, by requesting the missing messages or a fresh copy of the book. This strategy simply stops.

**Two details:**
- The cancels don't go through `SendQuote`. They aren't in the quote history, and `decisions.log` contains only the halt note, not a line per cancel.
- `CancelAll` would also cancel any enter or replace still in flight. Here there are none.

### After the halt

| Time | Event | What the app does |
|---|---|---|
| 8,020,000 | seq 10 and 11: our orders deleted | Book updated, then `CheckStanding` **throws**, is caught, and the app returns |
| 8,025,000 | Two `CANCELED` reports (reason `U`: user-requested; `-100` is the shares removed) | [OnCanceled](../app/execution/orders.cpp#L118) marks each side as having no order, then **throws**, is caught, returns |
| 10,005,000 | seq 12: p3 pulls its 100.01 ask | **Throws**. Without the halt, the app would have requoted |
| 12,005,000 | seq 13: p2 bids 100.01 | **Throws**. Without the halt, the app would have requoted |

Timer ticks continue until 20 ms. They never call `Requote`, so they never throw, and `OnTimer` doesn't halt twice because `halted_` is already set.

### gap in numbers

| | |
|---|---|
| Deliveries | 36: 12 feed messages, 4 reports, 20 timer ticks |
| Orders sent | 4: 2 ENTER, 2 CANCEL |
| Throws | 9: 2 "book invalid" (seq 1 and 2), 7 sequence-gap (seq 9 and the 6 messages after it) |
| Fills, P&L | None, $0 |

---

## 3. loss, part 1: 0 to 6 ms

The market steps down 5 cents every 3 ms. Each step has the same shape: a seller sweeps the bids, then the market re-forms 5 cents lower.

### Timeline

```
sim time (ns)   market                                     our app
     5,000      book: 100.00 x 100.01                     ENTER bid 99.99, ENTER ask 100.02
 2,000,000      seller sweeps 100.00 and our 99.99 bid    (fill 1: bought 100 @ 99.99)
 2,005,000                                                book invalid (no bids) -> nothing
 2,010,000                                                fill report -> book still invalid -> no new bid
 3,000,000      new bid 99.95, new ask 99.96,
                old 100.01 ask pulled
 3,005,000                                                half-updated view -> ENTER bid 99.97, REPLACE ask 99.99
 3,015,000      our 99.97 bid hits p3's 99.96 ask         (fill 2: bought 100 @ 99.96, we crossed the spread)
 3,025,000                                                REPLACE bid 99.94 (doomed), REPLACE ask 99.97
 3,045,000                                                bid replace rejected -> ENTER bid 99.94
 4,000,000      timer: credit jumps to $0.0245
 5,000,000      seller sweeps 99.95 and our 99.94 bid     (fill 3: bought 100 @ 99.94)
 5,005,000                                                book invalid -> nothing
 6,000,000      new bid 99.90, new ask 99.91, old ask pulled
 6,005,000                                                ENTER bid 99.90, REPLACE ask 99.96
 6,025,000                                                REPLACE bid 99.88, REPLACE ask 99.93
```

### t = 0 to 25,000

The book is p2's 500 at 100.00 and p3's 500 at 100.01: one level per side, a 1-cent spread. Seq 1 is bids only, so the book is invalid. At seq 2, fair value = 100.005, so the app sends **ENTER bid 99.99** and **ENTER ask 100.02**, behind the best prices as in `gap`. The 1 ms timer samples a mid of 100.005; P&L is $0.

### 2 ms: fill 1, and the app can't re-enter

On the exchange, p4's IOC sell for 600 at 99.99 takes p2's 500 at 100.00 (seq 5) and **our 100 at 99.99** (seq 6). The 2 ms timer runs first and sees the old book, so the return is 0.

- **2,005,000:** after seq 5, p2's bid is gone. Our own bid doesn't count, so there are **no market bids**. The book is invalid, and both messages throw in `CheckBook`.
- **2,010,000:** the Executed report. Position **+100**, cash −$9,999.00. In `basic`, the app re-entered its bid at this point. **Here the book is still invalid, so it can't.** Our ask at 100.02 stays, since resting orders are left alone.

### 3 ms: quoting off a half-updated book, and crossing the spread

On the exchange: at 3,000,000 p2 bids 500 at 99.95 (ref 6) and p3 offers 500 at 99.96 (ref 7). At 3,000,100 p3 pulls its old 100.01 ask.

The 3 ms timer finds the book invalid and skips the sample. P&L is marked to the last sampled mid (100.005): **+$1.50**, a stale mark.

| Message | Our view afterwards | Fair value | Action |
|---|---|---|---|
| seq 7: p2's bid 99.95 × 500 | 99.95 × 500 / **100.01** × 500 (the old ask is still there) | 99.98 | **ENTER bid at 99.97**; **REPLACE ask 100.02 → 99.99** |
| seq 8: p3's ask 99.96 × 500 | 99.95 × 500 / 99.96 × 500 | 99.955 | Both pending, so nothing |
| seq 9 *(3,005,100)*: old ask deleted | unchanged | 99.955 | Nothing |

**Why nothing happens at 3,005,100.** Two reasons, either one enough on its own:
- The deleted order (100.01) wasn't the best ask any more, so fair value doesn't change.
- Both sides already have a request in flight.

The app still does a full round of work for that message: decode, sequence check, book update, risk checks, fair value, and two `QuoteSide` calls that return early.

**The cross.** After seq 7 the app had seen p2's new bid but not p3's new ask, and it bid 99.97: *above* p3's real new ask at 99.96. At 3,015,000 our bid reaches the exchange and trades immediately at **99.96**, the resting order's price. Our report says `REMOVED`: we were the aggressor. The order never rests, so there's no Add for it in the feed.

**3,025,000:** three reports, handled in order.
1. **`ACCEPTED token=3`.** The app thinks its bid is live at 99.97. Fair value is 99.9555, so the bid should be 99.94: **REPLACE token 3 → 5**. This is doomed, because token 3 is already filled.
2. **`EXECUTED token=3 … REMOVED`.** Position **+200**, cash −$19,995.00. The bid's replace is in flight, so it waits.
3. **`REPLACED token 2 → 4`.** The ask is live at 99.99 but should be 99.97: **REPLACE token 4 → 6**.

**3,045,000:** `REJECTED token=5 reason=D`. The bid is empty, so **ENTER token 7 at 99.94**. The ask is confirmed at 99.97.

### 4 ms: volatility appears

The 4 ms timer samples a mid of **99.955**: a 5-cent drop from the last sample (100.005). This is the first real return the estimate has seen, and the credit jumps from $0.01 to **$0.0245**. (The 3 ms tick missed the move because the book was invalid then.) P&L = −$19,995 + 200 × 99.955 = **−$4.00**. The timer never requotes, so the new credit only takes effect on the next message.

### 5 ms: fill 3

p4's IOC sell for 600 at 99.94 takes p2's 500 at 99.95 and **our 100 at 99.94**. The book is invalid again, and at 5,010,000 the report arrives: position **+300**, cash −$29,989.00. There's no re-entry, and our ask stays at 99.97.

### 6 ms: the wider credit prevents a cross

On the exchange: p2 bids 500 at 99.90, p3 offers 500 at 99.91, and p3's 99.96 ask is pulled. The 6 ms timer skips its sample (book invalid), and P&L is marked stale at **−$2.50**.

| Message | Our view afterwards | Fair value | Action |
|---|---|---|---|
| seq 16: p2's bid 99.90 × 500 | 99.90 × 500 / 99.96 × 400 (old ask) | 99.9333 | **ENTER bid at 99.90**; **REPLACE ask 99.97 → 99.96** |
| seq 17: p3's ask 99.91 × 500 | 99.90 × 500 / 99.91 × 500 | 99.905 | Both pending, so nothing |
| seq 18: old ask deleted | unchanged | 99.905 | Nothing |

It's the same half-updated situation as at 3 ms. But now the credit is $0.0238, so 99.9333 − 0.0238 rounds down to **99.90**, *below* p3's 99.91. No cross.

**6,020,000 to 6,045,000:**
- **6,020,000:** our new bid appears in the feed **at the best price** (99.90), inflating that level from 500 to 600 for 5 µs.
- **6,025,000:** its Accepted report removes it again. Fair value is 99.905, so the app sends **REPLACE bid → 99.88** and **REPLACE ask → 99.93**.
- **6,045,000:** both are confirmed.

**End of part 1:** the market is 99.90 / 99.91. Our bid is at 99.88, our ask at 99.93. Position +300.

---

## 4. loss, part 2: 7 ms to the end

### Timeline

```
sim time (ns)   market                                      our app
 7,000,000      timer: credit $0.0337, P&L -$17.50
 8,000,000      seller sweeps 99.90, stops above our 99.88  (our bid NOT hit)
 8,005,000                                                 book invalid -> bid left at 99.88
 9,000,000      new bid 99.85; new ask 99.86 hits our 99.88 (fill 4: stale quote)
 9,005,000                                                 REPLACE bid 99.84 (doomed), REPLACE ask 99.92
 9,025,000                                                 bid replace rejected -> ENTER bid 99.82 (position 400)
11,000,000      seller sweeps 99.85, stops above our 99.82  (our bid NOT hit)
12,000,000      new bid 99.80; new ask 99.81 hits our 99.82 (fill 5: stale quote)
12,010,000                                                 position +500 -> bid BLOCKED
12,025,000                                                 bid replace rejected -> no re-entry
15,000,000      market re-forms at 99.70 / 99.71
15,005,000                                                 ask follows down: 99.81, then 99.75
16,000,000      timer: P&L -$106.50 -> HALT                CANCEL ask
18, 21 ms       market keeps falling                       nothing (halted)
```

### 7 to 8 ms: the seller misses our bid

- **7 ms timer:** the book is valid at 99.90 / 99.91, so the mid is **99.905**. The credit is $0.0337. P&L = −$29,989 + 300 × 99.905 = **−$17.50**, the honest number.
- **8,000,000:** p4's IOC sell for 600 at 99.89 takes p2's 500 at 99.90. The remaining 100 would need a bid at 99.89 or higher, and ours is at 99.88, so the IOC stops and its remainder is cancelled. **The wider credit keeps our bid 2 cents below the market, out of reach.**
- **8,005,000:** there are no market bids, so the book is invalid and the app **skips requoting**. Our bid stays at 99.88, now the only bid on the exchange.

### 9 ms: fill 4, a stale quote is hit

On the exchange at 9,000,000:
- p2 bids 500 at 99.85.
- p3 offers 500 at 99.86. The best bid on the exchange is **ours at 99.88**, so they trade: **we buy 100 at 99.88**. Our report says `ADDED`, since we were the resting order.
- p3's other 400 rest at 99.86.
- At 9,000,100 p3 pulls its old 99.91 ask.

The new market is about 99.855, and we paid 99.88. **Our quote had gone stale and was traded against.** A faster app couldn't have avoided it: the strategy *deliberately* left the bid alone while the book was invalid, and p3's sell arrived at the same instant as p2's new bid.

| Message | Our view afterwards | Fair value | Action |
|---|---|---|---|
| seq 24: p2's bid 99.85 × 500 | 99.85 × 500 / 99.91 × 500 (old ask) | 99.88 | **REPLACE bid → 99.84** (doomed); **REPLACE ask → 99.92** |
| seq 25: our ref 17 executed | unchanged | 99.88 | Pending |
| seq 26: p3's ask 99.86 × 400 | 99.85 × 500 / 99.86 × 400 | 99.8555 | Pending |
| seq 27: old ask deleted | unchanged | 99.8555 | Pending |

- **9,010,000:** the report. Position **+400**, cash −$39,977.00.
- **9,025,000:** the bid replace is rejected. The position check passes, since 400 + 100 = 500 is exactly at the limit: **ENTER at 99.82**. The ask is confirmed at 99.92 but should be 99.89: **REPLACE**.

**10 ms timer:** mid 99.855, credit $0.0400. P&L = **−$35.00**.

### 11 to 12 ms: the same pattern, and the position limit

- **11,000,000:** the IOC sell at 99.84 takes p2's 99.85 bid and stops above our 99.82. The book is invalid, so our bid stays put.
- **12,000,000:** p2 bids 99.80. p3's new ask at 99.81 hits our stale 99.82: **fill 5**.
- **12,005,000:** the app sees p2's bid first. It sends **REPLACE bid → 99.79** (doomed) and **REPLACE ask → 99.88**.

**12,010,000: the report. Position +500**, cash −$49,959.00. From now on, [CheckPosition](../app/risk/risk.h#L67) throws for the bid on every requote: 500 + 100 > 500.

| Time | Event | Bid side | Ask side |
|---|---|---|---|
| 12,020,000 | seq 36 | throws | pending |
| 12,025,000 | `REJECTED token=16` | **throws, so no re-entry** (compare 9,025,000) | pending |
| 12,025,000 | `REPLACED` (ask at 99.88) | throws | should be 99.85: **REPLACE**. An order sent *after* a throw on the same message |
| 12,040,000 and 12,045,000 | the replace is shown and confirmed | throws | in place |

**13 and 14 ms timers:** mid 99.805. P&L = −$49,959 + 500 × 99.805 = **−$56.50**.

### 15 ms: the market drops 10 cents, and only the ask follows

On the exchange: p2 moves its bid from 99.80 to 99.70, and p3 offers at 99.71 and pulls its 99.81 ask. p3's ask trades with nobody. **The position limit saved us here:** an unblocked bid would have been sitting at about 99.76, and it would have been filled.

| Message | Our view afterwards | Bid side | Ask side |
|---|---|---|---|
| seq 38: p2's 99.80 deleted | no market bids | Book invalid: `Requote` throws before reaching either side | — |
| seq 39: p2's bid 99.70 | 99.70 / 99.81 (old ask) | throws (position) | Fair value 99.7611: **REPLACE → 99.81** |
| seq 40: p3's ask 99.71 | 99.70 / 99.71 | throws | pending |
| seq 41: old ask deleted | unchanged | throws | pending |

At 15,025,000 the ask's replace is confirmed. Fair value is 99.705, so the ask should be 99.75: **REPLACE → 99.75**, again sent after a throw on the same message.

### 16 ms: the loss limit trips

The timer's mid is **99.705**, so P&L = −$49,959 + 500 × 99.705 = **−$106.50**. That's past −$100.

[OnTimer](../app/market_maker.cpp#L110):
1. latches the loss flag;
2. calls [Halt](../app/market_maker.cpp#L144) **directly**, with no exception;
3. `Halt` writes `16000000 loss limit breached` and calls `CancelAll`:
   - **bid:** nothing to cancel;
   - **ask:** **CANCEL token 20**.

That's why there's only one cancel.

### After the halt

- **Our cancel completes** (seq 44 at 16,015,000, the report at 16,020,000). The market keeps falling, to 99.60 / 99.61 at 18 ms and 99.50 / 99.51 at 21 ms. Every one of these messages throws in `CheckStanding` and returns: 10 throws after the halt.
- **The loss keeps growing.** `Halt` cancels orders but doesn't sell the 500 shares, and the strategy has no rule for closing a position. P&L is −$156.50 at 19 ms and **−$206.50** from 22 ms to the end.

### loss in numbers

| | |
|---|---|
| Deliveries | 118: 52 feed messages, 26 reports, 40 timer ticks |
| Orders sent | 21: 5 ENTER, 15 REPLACE, 1 CANCEL |
| Fills | 5 buys: 99.99, 99.96, 99.94, 99.88, 99.82 (average 99.918). No sells |
| P&L | −$106.50 at the halt; −$206.50 at the end, with +500 still held |
| Throws | 33: 10 "book invalid", 13 "position limit", 10 after the halt |
| Messages where an order went out after a throw | 3 (12,025,000; 15,005,000; 15,025,000) |

---

## 5. position

Sellers repeatedly hit our bid until the 500-share limit blocks it. Then a buyer takes our ask, and the bid comes back.

### t = 0: the book

| Side | Price × shares | Ref | Trader |
|---|---|---|---|
| Ask | 100.03 × 300 | 5 | p3 |
| Ask | 100.02 × 400 | 4 | p3 |
| Ask | 100.01 × 500 | 3 | p3 |
| Bid | 100.00 × 500 | 1 | p2 |
| Bid | 99.98 × 300 | 2 | p2 |

**What differs from `loss`:** p2's **second bid** at 99.98 keeps the book valid after each sweep, so the app can keep quoting.

### Timeline

```
sim time (ns)   market                                      our app                       position
     5,000      100.00 x 100.01                            ENTER bid 99.99, ask 100.02        0
 2 ms           sweep: p2's 100.00 + our 99.99 bid          requote; bid replace doomed     +100
 3 ms           p2 refills 100.00                           bid 99.99, ask 100.02
 5 ms           sweep again                                 same pattern                    +200
 8 ms           sweep again                                 same pattern                    +300
11 ms           sweep again                                 same pattern                    +400
14 ms           sweep again                                 bid BLOCKED, no re-entry        +500
15-18 ms        refill, other activity                      only the ask quotes
20 ms           buyer takes p3's asks and ours at 100.02    bid comes back                  +400
22 ms           p3 refills its asks                         normal quoting again
```

At the start, fair value is 100.005, so the app sends **ENTER bid 99.99** and **ENTER ask 100.02**. Our bid sits alone on its own price level (99.99), between p2's two bids. When a seller sweeps down to 99.99, our bid is the only thing there.

### Round 1 in detail (2 to 3 ms)

p4's IOC sell for 600 at 99.99 takes p2's 500 at 100.00 (seq 8) and our 100 at 99.99 (seq 9).

| Time | Event | What the app does | Position |
|---|---|---|---|
| 2,005,000 | seq 8: p2's 500 executed | The best bid is now p2's 99.98, so the book stays valid. Fair value = 99.99125. **REPLACE bid → 99.98** (doomed: our bid was filled in the same sweep). **REPLACE ask → 100.01** | 0 |
| 2,005,000 | seq 9: our bid executed | Pending | 0 |
| 2,010,000 | Executed report: bought 100 at 99.99 | The bid's replace is in flight, so it waits | **+100** |
| 2,025,000 | `REJECTED token=3 reason=D` | The position check passes: **ENTER at 99.98** | +100 |
| 2,025,000 | `REPLACED` (ask at 100.01) | Already at the right price | +100 |
| 3,005,000 | seq 12: p2 refills 100.00 | Fair value 100.005: **REPLACE bid → 99.99**, **REPLACE ask → 100.02** | +100 |

This is `basic`'s 5 ms race, every round: the app reprices off p2's fill a moment before learning its own bid was filled too.

### Rounds 2 to 4

| Round | Sweep | Fill report | Position after | Rejected replace → re-entry | Refill and requote |
|---|---|---|---|---|---|
| 2 | 5 ms | 5,010,000 | +200 | 5,025,000: ENTER at 99.98 | 6,005,000 |
| 3 | 8 ms | 8,010,000 | +300 | 8,025,000: ENTER at 99.98 | 9,005,000 |
| 4 | 11 ms | 11,010,000 | +400 | 11,025,000: ENTER at 99.98 (400 + 100 = 500, exactly *at* the limit) | 12,005,000 |

**The credit creeps up.** The timer samples the mid sometimes between a sweep and a refill (99.995) and sometimes after a refill (100.005). That bouncing looks like volatility, so from 10 ms the credit is slightly above $0.01, reaching $0.0117 by 14 ms.

### Round 5 (14 ms): the limit is hit

| Time | Event | Bid side | Ask side | Position |
|---|---|---|---|---|
| 14,005,000 | seq 36: p2's 500 executed | Credit $0.0117, so it should be **99.97** (not 99.98): **REPLACE** (doomed) | **REPLACE → 100.01** | +400 |
| 14,010,000 | Report: bought 100 at 99.99 | [CheckPosition](../app/risk/risk.h#L67): 500 + 100 > 500, so it **throws**; caught in [QuoteSide](../app/market_maker.cpp#L95) | pending | **+500** |
| 14,020,000 | seq 38 | throws | pending | +500 |
| 14,025,000 | `REJECTED` | throws, so **no re-entry** | pending | +500 |
| 14,025,000 | `REPLACED` (ask at 100.01) | throws | already right | +500 |

### 15 to 18 ms: the blocked period

| Time | Event | Bid side | Ask side |
|---|---|---|---|
| 15,005,000 | seq 39: p2 refills 100.00 | throws (would have been 99.99) | **REPLACE → 100.02**, sent *after* the bid's throw on the same message |
| 15,020,000 | seq 40 | throws | pending |
| 15,025,000 | `REPLACED` | throws | in place |
| 17,005,000 | seq 41: p2 adds 200 at 99.99 | throws | nothing to do |
| 18,005,000 | seq 42: p2 cancels it | throws | nothing to do |

Messages that change nothing for us still cost a full requote and a throw.

### 20 ms: a buyer takes our ask, and the bid comes back

p4's IOC buy for 1,000 at 100.02 takes p3's 500 at 100.01 (seq 43), p3's 400 at 100.02 (seq 44), then **our 100 at 100.02** (seq 45). Ours is behind p3's at the same price, because p3 was there first.

| Time | Event | Bid side | Ask side | Position |
|---|---|---|---|---|
| 20,005,000 | seq 43 | throws | **REPLACE → 100.03** (doomed) | +500 |
| 20,005,000 | seq 44 and 45 | throws (×2) | pending | +500 |
| 20,010,000 | Report: **sold 100 at 100.02** | Check passes (400 + 100 = 500): **ENTER at 100.00** | pending | **+400** |
| 20,025,000 | `REJECTED` | — | **ENTER at 100.04** | +400 |

**22 ms:** p3 refills its asks, fair value returns to 100.005, and the app sends **REPLACE bid → 99.99** and **REPLACE ask → 100.02**. Normal quoting continues to the end at 30 ms.

### position in numbers

| | |
|---|---|
| Deliveries | 117: 51 feed messages, 36 reports, 30 timer ticks |
| Orders sent | 30 |
| Fills | 5 buys at 99.99, 1 sell at 100.02 |
| Final position, P&L | +400; **+$9.00** ($3 realised on the round trip, $6 unrealised on the 400 held) |
| Throws | 14: 2 "book invalid", 12 "position limit" (14,010,000 to 20,005,000) |
| Messages where an order went out after a throw | 2 (15,005,000 and 20,005,000) |

### position vs loss

| | `loss` | `position` |
|---|---|---|
| Position reached | +500 | +500 |
| Why we kept buying | The market kept falling, and our bid was hit at stale prices | Sellers kept sweeping, but the market kept refilling at the same level |
| P&L at its worst | −$106.50, which tripped the loss limit and halted | Never negative at the timer checks |
| How it ended | Halted for good, still holding 500 shares | A buyer took our ask, and quoting resumed |

**The position limit caps how much risk we hold. It says nothing about whether we're making or losing money.** That's why the strategy has a separate loss limit.

---

## 6. Answers to the check-your-understanding questions

<details>
<summary><strong>gap</strong></summary>

1. **If the dropped message were the last feed message, when would the app detect the gap?** Never. A gap only shows up when a *later* message arrives with a higher sequence number, and the timer doesn't check sequence numbers. Real feeds use heartbeats ("nothing new, the next sequence number is N") so that a gap at the end still shows up.
2. **Why does `CancelAll` also cancel orders whose enter or replace is in flight?** To avoid orphan orders. Our messages reach the exchange in the order we sent them. A replace from token 3 to token 5 that's in flight arrives *before* our cancel: token 3 dies and token 5 goes live, and then our cancel of token 3 is ignored. Without a cancel for token 5, a live order would sit on the exchange that the halted app never manages again. Sending both is safe, because the exchange ignores cancels for dead tokens.

</details>

<details>
<summary><strong>loss, part 1</strong></summary>

1. **If p3's ask (seq 8) had arrived before p2's bid (seq 7)?** After seq 8 there are no market bids, so the app skips. After seq 7 it sees 99.95 / 99.96, so fair value is 99.955: bid 99.94, ask 99.97. No cross, and no fill at 99.96. The order the feed messages arrive in changed the outcome.
2. **Why is −$2.50 at 6 ms misleading?** The book was invalid, so the mid wasn't sampled, and P&L was marked to the old mid of 99.955. The market had really moved to about 99.905. Marked there, P&L is −$29,989 + 300 × 99.905 = **−$17.50**. A stale mark understates the loss.

</details>

<details>
<summary><strong>loss, part 2</strong></summary>

1. **At 8 and 11 ms the IOC stopped just above our bid, but at 2 and 5 ms it hit us. What changed?** The credit. With a 1-cent credit our bid sat 1 cent below the best bid, inside the IOC's reach. From 4 ms, volatility widened the credit to 2–4 cents, which put our bid out of reach.
2. **If the loss limit were checked on every message, when would it trip?** With 500 shares bought for $49,959, P&L goes below −$100 when the mid falls below **99.718**. At seq 39 (15,005,000) the mid is 99.755, so P&L is −$81.50. At seq 40 (15,005,100) it's 99.705, so P&L is **−$106.50**. It would trip at **15,005,100**, about 1 ms before the timer caught it. (An earlier version of this hint said 99.759; the correct threshold is 99.718.)

</details>

<details>
<summary><strong>position</strong></summary>

1. **Why could the app requote straight after the 2 ms sweep, when in `loss` it couldn't?** p2's second bid at 99.98 survived the sweep, so the book stayed valid. In `loss` the only market bid was swept away, so the book was invalid.
2. **With `kPositionLimit` = 450, when would the bid be blocked?** The check is position + 100 > 450. At +300 it gives 400, which is allowed. At +400 it gives 500, which is blocked. So the bid would be blocked after the **4th fill, at +400**. With 100-share fills, the position could never actually reach 450.

</details>
