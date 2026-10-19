# Reading the trace: `basic.scn`

*Written 2026-10-13. Previous: [02-build-setup.md](02-build-setup.md).*

A message-by-message explanation of `build/out/basic/trace.txt`, which this command produces:

```sh
./build/market_maker sim/fixtures/basic.scn --trace
```

## Contents

1. [How to read the trace](#how-to-read-the-trace)
2. [Part 1: from the start to the first timer tick](#part-1-from-the-start-to-the-first-timer-tick)
3. [Part 2: from 1.2 ms to the end](#part-2-from-12-ms-to-the-end)
4. [The whole run in numbers](#the-whole-run-in-numbers)
5. [What the trace shows](#what-the-trace-shows)
6. [Wall-clock timings of this run](#wall-clock-timings-of-this-run)

---

## How to read the trace

Each line starts with the simulated time in nanoseconds, followed by a prefix:

| Prefix | Meaning |
|---|---|
| `EXT>` | Another trader's order reaching the exchange |
| `MD` | A market data (feed) message delivered to our app |
| `APP>` | An order our app sent |
| `APP<` | An execution report delivered to our app |
| `TIMR` | A timer tick delivered to our app |
| `DROP` | A feed message deliberately dropped (only in `gap.scn`) |

- **There are two separate `seq` counters.** `MD seq=` numbers the public feed; `APP< seq=` numbers the private reports sent to us.
- **Some things never appear in the trace:** our own orders reaching the exchange (ours show up only as `APP>`, when we send them), and reports to other traders (the simulator discards those).
- **Delays:** other traders reach the exchange instantly. The feed reaches us 5 µs after the exchange publishes, and our orders and the exchange's replies take 10 µs each way. So it's 20 µs from sending an order to its Accepted report, and 15 µs from sending it to seeing it in the feed.
- **How the app reacts:** after every feed message and every report, it re-decides both quotes, bid first, then ask:
  - no order on that side: enter one;
  - the price should change: replace it;
  - otherwise: do nothing.

  It never touches a side that's waiting for a reply. Timer ticks never send orders.
- **Credit:** every quote in this run uses the $0.01 minimum. See the [6–10 ms section](#610-ms-only-timer-ticks).

---

## Part 1: from the start to the first timer tick

### Timeline

```
sim time (ns)   exchange                          our app
         0      4 orders from p2, p3 -> refs 1-4
     5,000                                        feed 1-4 -> ENTER bid 100.01, ENTER ask 100.04
    15,000      our 2 orders arrive -> refs 5, 6
    20,000                                        feed 5, 6: our own orders, not yet recognised
    25,000                                        2 Accepted -> REPLACE bid to 100.02
    35,000      replace arrives -> ref 7
    40,000                                        feed 7
    45,000                                        Replaced -> REPLACE bid to 100.01
    55,000      replace arrives -> ref 8
    60,000                                        feed 8
    65,000                                        Replaced -> nothing to do
   500,000      p3 adds a bid -> ref 9
   505,000                                        feed 9 -> nothing to do
 1,000,000                                        first timer tick
```

The rows at 15,000, 35,000 and 55,000 aren't in the trace (see above).

### t = 0: the book is built

Traders p2 and p3 each send two Day orders. Each trader picks its own tokens, so both can use 1 and 2. The exchange gives them refs 1–4 in arrival order. Nothing can trade (the highest bid, 100.00, is below the lowest ask, 100.05), so all four rest on the book. The exchange publishes four AddOrder messages, seq 1–4.

| Side | Price × shares | Ref |
|---|---|---|
| Ask | 100.06 × 200 | 4 |
| Ask | 100.05 × 300 | 3 |
| Bid | 100.00 × 300 | 2 |
| Bid | 99.99 × 200 | 1 |

### t = 5,000: the feed arrives and we quote

All four messages arrive at the same simulated time, but the app handles them one at a time.

| Message | Our view of the market afterwards | What the app does |
|---|---|---|
| seq 1: bid 99.99 × 200 | bids only | Book invalid (no asks), so it skips |
| seq 2: bid 100.00 × 300 | bids only | Book invalid, so it skips |
| seq 3: ask 100.05 × 300 | 100.00 × 300 / 100.05 × 300 | **Quotes both sides** |
| seq 4: ask 100.06 × 200 | unchanged (behind the best ask) | Both sides are waiting for replies, so nothing |

The quote prices at seq 3:

- fair value = (100.00 × 300 + 100.05 × 300) / 600 = **100.025**. Both sizes are equal, so it's simply the midpoint.
- bid = 100.025 − 0.01 = 100.015, rounded down to **100.01**
- ask = 100.025 + 0.01 = 100.035, rounded up to **100.04**

Both prices are inside the old 5-cent spread. Once our orders arrive, *we* are the best bid and offer on the exchange, at 100.01 × 100.04. Narrowing the spread like this is what a market maker does.

#### Seq 3 through the code, step by step

This is the first message that leads to an order:

1. **[OnMarketData](../app/market_maker.cpp#L14)** copies the 19-byte header out of the raw bytes (`sim::Decode`). It checks that the sequence number is the expected 3, then switches on the message type `'A'`.
2. **[Book::Apply](../app/market_data/book.cpp#L31)** finds slot 3 in the order array and stores the order's price, size and side. [AddLiquidity](../app/market_data/book.cpp#L100) adds 300 shares at the 100.05 rung of the ask ladder. The ask side was empty, so the cached best ask becomes 100.05 × 300.
3. **[Requote](../app/market_maker.cpp#L73)** runs the standing risk checks (no sequence gap, no loss halt). It reads the cached top of book, and [CheckBook](../app/risk/risk.h#L58) confirms the book is valid. Then [CalcMicroprice](../app/strategy/pricing.h#L31) returns 1,000,250 ($100.025), and [CalcCredit](../app/strategy/pricing.h#L57) returns 100 ($0.01).
4. **[QuoteSide](../app/market_maker.cpp#L95) for the bid at 100.01.** The position check passes: 0 + 100 ≤ 500. The bid has no order and nothing pending, so it calls [SendQuote](../app/execution/orders.cpp#L7), which:
   - takes token 1;
   - appends the quote to the in-memory history;
   - writes an `ENTER` line to `decisions.log`;
   - calls `session_.Send` with an `EnterOrder`. The capture tap records the time of that call, and the simulator schedules the order to reach the exchange at 15,000.

   The bid is then marked pending, waiting for token 1's reply.
5. **QuoteSide for the ask at 100.04:** the same steps, with token 2.
6. **Back in OnMarketData**, `latency_.Record` stores the time the handler finished.

This is a concrete example of tick-to-trade. The *tick* is the moment `OnMarketData` was entered for seq 3. The *trade* is the moment `Send` was called for token 1.

At seq 1 and 2, "book invalid" happens through an exception: `CheckBook` throws and `Requote` catches it (design doc §2.2.3).

### t = 15,000 (not in the trace): our orders reach the exchange

The exchange accepts token 1 as **ref 5** and token 2 as **ref 6**. Neither can trade (100.01 is below 100.05, and 100.04 is above 100.01), so both rest. For each one the exchange produces:

- an AddOrder on the public feed, which reaches us at **20,000** (5 µs later);
- an Accepted report, sent only to us, which reaches us at **25,000** (10 µs later).

The feed is faster than the reports, so we see our own orders 5 µs before we learn they're ours.

### t = 20,000: our own orders, not yet recognised

| Message | Our view afterwards | Fair value | Action |
|---|---|---|---|
| seq 5: bid 100.01 × 100 (ref 5, ours) | 100.01 × 100 / 100.05 × 300 | 100.02 | Both sides pending, so nothing |
| seq 6: ask 100.04 × 100 (ref 6, ours) | 100.01 × 100 / 100.04 × 100 | 100.025 | Both sides pending, so nothing |

The feed doesn't say whose orders these are, and the Accepted reports haven't arrived, so the app counts both as other traders' orders. Our own quotes are already skewing our fair value, but both sides are waiting for replies, so nothing gets sent.

### t = 25,000: the Accepted reports cause a bump

Two reports arrive at the same time and are handled one after the other.

**Accepted for token 1 (ref 5).**

1. The bid is now live at 100.01.
2. [MarkOwn(5)](../app/market_data/book.cpp#L72) removes ref 5 from our view of the market. The best bid falls back to 100.00 × 300; the app finds it by stepping down the ladder one rung.
3. Ref 6, our ask, still counts as someone else's order, so our view is 100.00 × 300 / 100.04 × 100.
4. fair value = (100.00 × 100 + 100.04 × 300) / 400 = **100.03**.
5. The bid should be 100.02 but is live at 100.01, so the app sends **REPLACE token 1 → token 3 at 100.02**. The bid is pending again.
6. The ask should be 100.04, but it's still pending, so nothing happens on that side.

**Accepted for token 2 (ref 6).**

1. The ask is now live at 100.04.
2. `MarkOwn(6)` removes it from our view, and the best ask goes back to 100.05 × 300.
3. Fair value returns to 100.025, so the bid should be 100.01 again. But its replace is still on its way, so the bid has to wait.
4. The ask is already at the price it should be (100.04).

The bump happens only because these two reports are processed one after the other. It follows from the fixed strategy rule that an order counts as ours once its Accepted arrives, so `basic.expected` requires it.

### t = 35,000 to 65,000: the bid moves back

| Time | Event | Effect |
|---|---|---|
| 35,000 | *(exchange)* The replace arrives: ref 5 is removed and **ref 7** rests at 100.02 | The Replaced report reaches us at 45,000; the feed message at 40,000 |
| 40,000 | seq 7: REPLACE ref 5 → ref 7 | Ref 5 was ours, so ref 7 is marked ours straight away. Our view doesn't change. The bid is still pending, so nothing |
| 45,000 | Replaced (token 3, ref 7) | The bid is live at 100.02 and no longer pending. It should be 100.01, so the app sends **REPLACE token 3 → token 4 at 100.01** |
| 55,000 | *(exchange)* That replace arrives and becomes **ref 8** | The report reaches us at 65,000; the feed message at 60,000 |
| 60,000 | seq 8: REPLACE ref 7 → ref 8 | Marked ours; nothing to do |
| 65,000 | Replaced (token 4, ref 8) | The bid at 100.01 and the ask at 100.04 are both where they should be. **Quiet** |

The 20 µs between our decisions (25,000 → 45,000) is one round trip: 10 µs to the exchange and 10 µs back.

### t = 500,000 to 505,000: a new bid joins and nothing changes

Trader p3 adds a bid for 100 shares at 100.00, which becomes ref 9. It queues *behind* p2's 300 at the same price: same price, later arrival. At 505,000 we see it as seq 9, and the best bid becomes 100.00 × 400.

- fair value = (100.00 × 300 + 100.05 × 400) / 700 = 100.028571…, which the integer arithmetic cuts down to **100.0285**
- bid = 100.0185, rounded down to **100.01**; ask = 100.0385, rounded up to **100.04**

Those are exactly the orders already resting, so **nothing is sent**. Fair value moved by about a third of a cent, and rounding to the cent absorbed it.

### t = 1,000,000: the first timer tick

[OnTimer](../app/market_maker.cpp#L110) never sends orders: the strategy only requotes on feed messages and reports. It does four things:

1. **Samples the mid:** (100.00 + 100.05) / 2 = **100.025**. This is the plain midpoint, not the microprice.
2. **Updates volatility.** This is the first sample, so there's no previous mid to compute a return from; it just stores 100.025. The variance stays 0, so the credit stays $0.01.
3. **Checks the loss limit.** P&L = cash 0 + position 0 × 100.025 = **$0**, which is fine.
4. **Reconciles the quote history.** It checks that the 4 quotes sent so far (tokens 1–4) all have a positive price, sit on the cent grid, and are 100 shares. All pass.

Then it records its finish time in the latency log.

### Where things stand at the first timer

| | Value |
|---|---|
| Market, excluding us | Bids: 100.00 × 400 (refs 2 and 9), 99.99 × 200. Asks: 100.05 × 300, 100.06 × 200 |
| Our bid | 100.01 × 100: token 4, ref 8, live |
| Our ask | 100.04 × 100: token 2, ref 6, live |
| Orders sent | 4 (2 ENTER, 2 REPLACE); the next token will be 5 |
| Position and cash | 0 and 0, since nothing has traded yet |
| Deliveries so far | 14 of the run's 54: 9 feed messages, 4 reports, 1 timer tick. Only 3 of them led to orders |

---

## Part 2: from 1.2 ms to the end

### Timeline

| Time | Market event | Our orders |
|---|---|---|
| 1.2 ms | p2 joins the best bid at 100.01 | Ask 100.04 → 100.03 |
| 2 ms | p4 sells 250: hits **our bid**, p2's bid, and part of the 100.00 bid | Ask → 100.04; new bid at 100.01; ask → 100.03 → 100.04 |
| 3 ms | p3 cuts its 100.05 ask to 100 shares, then pulls its 100.00 bid | Bid → 100.02, ask → 100.05 |
| 4 ms | p2 moves its bid up to 100.01 | Nothing |
| 5 ms | p4 buys 400: hits p3's ask and **ours**; 200 shares rest as a bid at 100.05 | Bid → 100.04; ask replace **rejected**; new ask at 100.07 |
| 6–10 ms | Nothing | Nothing (timer ticks only) |

### 1.2 ms: a better but thinner bid pulls fair value *down*

p2 adds 100 shares at 100.01 (ref 10). That's the same price as our bid, but ours arrived first, so ours is ahead in the queue. At 1,205,000 our view is 100.01 × 100 / 100.05 × 300:

- fair value = (100.01 × 300 + 100.05 × 100) / 400 = **100.02**, *down* from 100.0285 even though the best bid went *up*. The microprice weights each price by the *opposite* side's size. The new best bid is only 100 shares against 300 on the ask, so fair value leans toward the bid, the side most likely to be used up next.
- ask = 100.02 + 0.01 = **100.03**, so the app sends **REPLACE token 2 → 5**. The bid stays at 100.01.
- At 1,220,000 the feed shows the replace (ref 6 → 11); at 1,225,000 the Replaced report arrives. Quiet again.

### 2 ms: a sell order sweeps the bid, our first trade

**On the exchange at 2,000,000**, p4 sends an IOC sell for 250 shares at 100.00. It fills best price first, and at each price the oldest order first:

| Order hit | Price | Shares | Feed |
|---|---|---|---|
| ref 8: **our bid** (first in the queue at 100.01) | 100.01 | 100 | seq 12 |
| ref 10: p2 | 100.01 | 100 | seq 13 |
| ref 2: p2 | 100.00 | 50 of 300 | seq 14 |

Being IOC, nothing is left over to rest. The feed messages reach us at 2,005,000; our private Executed report reaches us at 2,010,000.

**The timer at 2,000,000** runs before any of that news arrives, so it sees the old book. The mid is (100.01 + 100.05) / 2 = **100.03**. That gives the first real volatility sample: a return from 100.025 to 100.03. The credit formula now gives about a quarter of a cent, which is below the $0.01 minimum, so the credit stays $0.01. P&L is still $0, because the app doesn't know about the fill yet.

**2,005,000: the three feed messages**

| Message | What the app sees | Fair value | Action |
|---|---|---|---|
| seq 12: ref 8 executed | Ref 8 is ours (known since 60,000), so the book drops it, but the market view doesn't change | 100.02 | Nothing |
| seq 13: ref 10 executed | Best bid falls to 100.00 × 400 | 100.0285 | Ask should be 100.04: **REPLACE token 5 → 6** |
| seq 14: ref 2 reduced by 50 | Best bid 100.00 × 350 | 100.0269 | Nothing (ask pending, bid unchanged) |

The feed shows our fill 5 µs *before* our own report, because the feed is faster. The book code sees that ref 8 is gone. But the order manager, which tracks our position and our quotes, only learns from the report. So for 5 µs the app still believes it has a bid at 100.01.

**2,010,000: our Executed report.** Our bid filled 100 shares at 100.01. `ADDED` means our order was the resting one, so we were the maker. [OnExecuted](../app/execution/orders.cpp#L90) updates the position from 0 to **+100** and cash by −$10,001. The bid side now has no order, so the app re-enters at once: **ENTER token 7, BUY 100 at 100.01**. The position check passes: 100 + 100 ≤ 500.

**2,020,000 to 2,065,000: the same bump as at the start**

| Time | Event | Effect |
|---|---|---|
| 2,020,000 | seq 15: ask replace ref 11 → 13 | Ours; nothing to do |
| 2,025,000 | Replaced (token 6): ask live at 100.04 | Nothing to do |
| 2,025,000 | seq 16: **our new bid** (ref 14), not yet recognised | It looks like someone's thin 100.01 × 100 bid, so fair value = 100.02 and the ask should be 100.03: **REPLACE token 6 → 8** |
| 2,030,000 | Accepted (token 7): ref 14 is ours | Fair value goes back to 100.0269. The ask should be 100.04 again, but its replace is still on its way |
| 2,045,000 | Replaced (token 8): ask live at 100.03 | **REPLACE token 8 → 9 at 100.04** |
| 2,060,000–2,065,000 | Feed message, then Replaced | Quiet: bid 100.01, ask 100.04 |

### 3 ms: the ask thins out and fair value rises

- **3,000,000:** p3 cuts its 100.05 ask from 300 to 100 shares (a partial cancel). The timer runs before the feed message arrives. The mid is 100.025, so P&L = −$10,001 + 100 × 100.025 = **+$1.50**: we bought at 100.01 and the mid is 1.5 cents higher.
- **3,005,000:** seq 19 (`CANCEL ref=3 -200`) arrives. Our view is now 100.00 × 350 / 100.05 × 100.
  - fair value = **100.0388**. The ask side is now the thin one, so fair value leans up.
  - Bid should be 100.02 and ask 100.05, so **one message triggers two replaces**: token 7 → 10 (bid) and token 9 → 11 (ask).
  - Our new ask at 100.05 queues *behind* p3's remaining 100 shares at that price.
- **3,020,000–3,025,000:** the feed shows both replaces (refs 17, 18), then both Replaced reports arrive. Quiet.
- **3,100,000–3,105,000:** p3 deletes its 100.00 bid (ref 9), leaving the best bid at 100.00 × 250. Fair value = 100.0357; the desired prices don't change, so the app sends **nothing**.

### 4 ms: another trader's replace

- p2 moves its remaining 250 at 100.00 to 150 shares at 100.01. It becomes ref 19 and loses its place in the queue.
- The timer sees a mid of 100.025 again, so the return is 0 and P&L is still +$1.50.
- **4,005,000:** seq 23 (`REPLACE ref=2 -> ref=19`). While the book applies it, ref 2 is removed first, so the best bid briefly drops to 99.99. Then ref 19 is added and the best bid becomes 100.01 × 150. The app requotes **once, after the whole message**, so that in-between state is never priced. Fair value = 100.034, bid 100.02, ask 100.05: unchanged, so **nothing** is sent.

### 5 ms: a buy lifts our ask, and a replace is rejected

**On the exchange at 5,000,000**, p4 sends a Day buy for 400 shares at 100.05:

| Order hit | Price | Shares | Feed |
|---|---|---|---|
| ref 3: p3 (first in the queue at 100.05) | 100.05 | 100 | seq 24 |
| ref 18: **our ask** (second in the queue) | 100.05 | 100 | seq 25 |
| Next ask is 100.06, above p4's limit | — | — | stop |

Being a Day order, the remaining 200 shares rest as a bid at 100.05 (ref 20, seq 26). On the exchange, the top of book is now 100.05 bid / 100.06 ask.

**The timer at 5,000,000** again sees the old book: the mid is 100.03, so P&L = **+$2.00**.

**5,005,000: three feed messages**

| Message | Our view afterwards | Fair value | Action |
|---|---|---|---|
| seq 24: ref 3 executed | 100.01 × 150 / 100.06 × 200 | 100.0314 | Bid 100.02 and ask 100.05 unchanged: nothing |
| seq 25: ref 18 (ours) executed | Unchanged | 100.0314 | Nothing: the app still thinks our ask is live |
| seq 26: p4's 200 at 100.05 | 100.05 × 200 / 100.06 × 200 | **100.055** | Bid should be 100.04: **REPLACE token 10 → 12**. Ask should be 100.07: **REPLACE token 11 → 13** |

That second replace targets an order that **no longer exists**. Our ask traded at 5,000,000, but the report saying so is still on its way.

- **5,010,000: Executed report.** Our ask filled 100 shares at 100.05. The position goes back to **0** and cash to **+$4.00**: we bought at 100.01 and sold at 100.05, earning the 4-cent spread on 100 shares. This is market making working as intended. The ask now has no live order, but a request is still in flight, so that side waits.
- **5,015,000 (exchange):** the bid replace succeeds (ref 21 at 100.04). The ask replace names token 11, which is no longer live, so it's **rejected with reason D (unknown order)**.
- **5,025,000:** the Replaced report arrives (bid live at 100.04), then `REJECTED token=13`. [OnRejected](../app/execution/orders.cpp#L108) clears the pending flag. The ask now has no order and nothing in flight, so the app sends **ENTER token 14, SELL 100 at 100.07**.
- **5,040,000:** seq 28 shows our new ask, not yet recognised. This time it sits *behind* the best ask (100.06), so the top of book doesn't change and fair value isn't affected.
- **5,045,000:** the Accepted report arrives (ref 22). Quiet. Final quotes: **bid 100.04, ask 100.07**.

### 6–10 ms: only timer ticks

- **Nothing else trades.** Five `TIMR` lines and nothing more.
- **The credit finally rises.** At 6 ms the mid jumps 2.5 cents (100.03 → 100.055), the first move big enough to lift the credit above the minimum.
- **No quote ever uses it.** The strategy requotes only on feed messages and reports, never on the timer, and none arrive after 5,045,000.
- **The run ends.** P&L stays at +$4.00, and the run stops at the 10 ms end time.

Volatility and credit at each timer tick:

| Timer | Mid | Credit from the formula | Credit used |
|---|---|---|---|
| 1 ms | 100.0250 | $0 (first sample, no return yet) | $0.01 |
| 2 ms | 100.0300 | $0.0025 | $0.01 |
| 3 ms | 100.0250 | $0.0035 | $0.01 |
| 4 ms | 100.0250 | $0.0034 | $0.01 |
| 5 ms | 100.0300 | $0.0041 | $0.01 |
| 6 ms | 100.0550 | $0.0129 | $0.0129 |
| 7–10 ms | 100.0550 | $0.0125 falling to $0.0114 | the same |

The formula's result is rounded up to $0.0001, and the credit used is the larger of that and $0.01. The rise from 6 ms onward never reaches a quote.

---

## The whole run in numbers

| | |
|---|---|
| Deliveries | 54: 28 feed messages, 16 reports, 10 timer ticks |
| Orders sent | 14: 4 ENTER and 10 REPLACE, matching `decisions.log` and `basic.expected` |
| Deliveries that led to an order | 11 of 54 |
| Fills | 2: bought 100 at 100.01, sold 100 at 100.05 |
| Final position and P&L | 0 shares, +$4.00 |
| Risk events | Book invalid twice (seq 1 and 2); 1 rejected replace; no gap, position or loss limit |
| Credit used by every quote | $0.01 |

---

## What the trace shows

- **Every order has two IDs:** a token we choose, and a ref the exchange assigns that we only learn a round trip later. The gap between seeing an order in the feed and knowing it's ours causes the bumps at 25,000 and 2,025,000.
- **Only one request per side at a time:** after each send, that side is frozen until its reply arrives, 20 µs later.
- **Most deliveries send nothing:** only 11 of the 54 led to an order.
- **Price-time priority decides who trades.** At 2 ms our bid was first in line at 100.01 because it arrived first. At 5 ms our ask was second at 100.05, behind p3.
- **We hear about each fill twice:** first anonymously in the feed, after 5 µs; then in our private report, after 10 µs. Position and cash only change on the report.
- **A full fill empties that side, and the app re-enters straight away** (2,010,000).
- **Races are normal.** At 5,005,000 the app replaced an order that had already traded, because the news hadn't arrived yet. The exchange rejected it, and the app recovered by entering a fresh order.
- **Fair value responds to size, not just price.** A better but thinner bid lowered it at 1.2 ms; a thinner ask raised it at 3 ms.
- **Timer ticks never move quotes.** Even when the credit changed at 6 ms, no quote changed.

---

## Wall-clock timings of this run

On 2026-10-13 this Mac (Apple M5 Pro) ran `basic` 15 times: 13 runs without `--trace` and 2 with it. Every run handled the same 54 deliveries and sent the same 14 orders. But the reported average latency for the runs without tracing ranged from **1,292 to 2,636 ns**, about 2×. The values fell into two groups, around 1.3–1.5 µs and around 2.5–2.6 µs. The two `--trace` runs (2,542 and 1,350 ns) landed within the same range.

Likely causes, to test later:

- **Two kinds of core.** 5 fastest cores ("Super") and 10 slower ones ("Performance"), and macOS decides which one runs the program.
- **Clock speed ramp-up.** Idle cores run slowly and speed up under load. The whole run is only about 100 µs of work, so it can finish before the core speeds up.
- **Cold start.** Every run is a new process, so almost every message is handled with empty caches and an untrained branch predictor, and code is loaded the first time it runs.
- **Background activity** from other apps and the operating system.
- **Clock resolution:** the clock ticks every 41.66 ns.

**Lesson:** a single run of a small scenario can't show whether a change helped, unless the gain is much bigger than the noise.
