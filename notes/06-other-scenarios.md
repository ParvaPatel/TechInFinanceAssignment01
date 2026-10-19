# The other scenarios: `quiet`, `empty_side` and `sweep`

*Written 2026-10-18. Previous: [05-risk-walkthroughs.md](05-risk-walkthroughs.md).*

Message-by-message walkthroughs of the last three scenarios, in the same style as [03](03-reading-the-trace.md) and [05](05-risk-walkthroughs.md). All three sent exactly the orders in their `.expected` files. To reproduce:

```sh
./build/market_maker sim/fixtures/quiet.scn --trace
./build/market_maker sim/fixtures/empty_side.scn --trace
./build/market_maker sim/fixtures/sweep.scn --trace
```

The usual rules apply: feed delay 5 µs, order and report delay 10 µs each way, and the app re-decides both quotes after every feed message and every report. The credit stays at $0.01 throughout all three runs.

## Contents

1. [quiet](#1-quiet)
2. [empty_side](#2-empty_side)
3. [sweep](#3-sweep)
4. [All seven scenarios side by side](#4-all-seven-scenarios-side-by-side)
5. [Answers to the check-your-understanding questions](#5-answers-to-the-check-your-understanding-questions)

---

## 1. quiet

The scenario's comment: *a one-tick market with activity behind the top and a few size changes at the top, but no trades. Most messages lead to no order.* The run makes exactly 2 orders, both in the first 205 µs.

### Timeline

```
sim time (ns)   market                                          our app
         0      p2 bids 100.00, 99.99, 99.98 (no asks yet)
     5,000                                                      feed 1-3 -> book invalid x3 -> nothing
   200,000      p3 offers 100.01, 100.02, 100.03
   205,000                                                      feed 4 -> ENTER bid 99.99, ENTER ask 100.02
   225,000                                                      Accepted x2; quiet from here on
2 - 8 ms        p5 adds and pulls orders behind the top         7 messages -> nothing
9 - 13 ms       sizes change at the top (100.00 and 100.01)    4 messages -> fair value moves, quotes don't
14 - 18 ms      p5 adds and pulls more depth                    5 messages -> nothing
```

### Start: the app waits for asks

- **5,000:** p2's three bids arrive. With no asks, the book is invalid, and all three messages throw in `CheckBook`.
- **205,000:** p3's 100.01 ask arrives (seq 4). The book becomes valid at 100.00 × 500 / 100.01 × 500. Fair value is 100.005, so the app sends **ENTER bid 99.99** and **ENTER ask 100.02**. The market is 1 cent wide, so our quotes *join* existing levels: behind p2's 400 at 99.99 and behind p3's 400 at 100.02.
- **220,000 to 225,000:** our orders appear in the feed behind the best prices (no bump), then they're accepted. From here the app sends nothing.

### 2 to 8 ms: activity behind the top

p5 adds and pulls orders at 99.97, 100.04, 99.96 and 100.05 (seq 9–16). None of this touches the best prices (100.00 / 100.01), so fair value stays at exactly 100.005. Every message still goes through the full routine:

- decode, sequence check, book update;
- risk checks, fair value, credit, rounding;
- two `QuoteSide` calls that find nothing to do;
- the latency record.

### 9 to 13 ms: sizes change at the top, fair value moves, quotes don't

| Time | Message | Best bid / best ask | Fair value | Bid | Ask |
|---|---|---|---|---|---|
| (before) | | 100.00 × 500 / 100.01 × 500 | 100.0050 | 99.99 | 100.02 |
| 9,005,000 | p2 cuts its 100.00 bid from 500 to 200 (a partial cancel: `CANCEL ref=1 -300`) | 100.00 × **200** / 100.01 × 500 | 100.0028 | 99.99 | 100.02 |
| 10,005,000 | p3 adds 300 at 100.01 | 100.00 × 200 / 100.01 × **800** | 100.0020 | 99.99 | 100.02 |
| 12,005,000 | p2 adds 300 at 100.00 | 100.00 × **500** / 100.01 × 800 | 100.0038 | 99.99 | 100.02 |
| 13,005,000 | p3 cuts its first 100.01 ask from 500 to 100 | 100.00 × 500 / 100.01 × **400** | 100.0055 | 99.99 | 100.02 |

A `CANCEL` shrinks an order and leaves it on the book. A `DELETE` removes it entirely.

### 14 to 20 ms

More depth comes and goes (seq 22–26), and nothing changes. The best prices never move, so every timer tick samples the same mid (100.005): the volatility estimate stays at 0 and P&L at $0.

### quiet in numbers

| | |
|---|---|
| Deliveries | 48: 26 feed messages, 2 reports, 20 timer ticks |
| Orders sent | 2, both while handling seq 4 |
| Deliveries that led to an order | **1 of 48** |
| Feed messages that changed fair value | 5: seq 4, plus the 4 top-of-book size changes |
| Throws | 3 ("book invalid" at seq 1–3) |

### What quiet shows

- **The app can't quote until both sides exist.**
- **Fair value ignores depth.** Only the best bid, the best ask and their sizes matter.
- **Size changes at the top move fair value, but rounding absorbs them** in a 1-cent market with a 1-cent credit.
- **Almost every delivery does full work and sends nothing:** 47 of 48 here.

---

## 2. empty_side

The scenario's comment: *the ask side empties for a while, then comes back. While there are no asks (excluding our own), the book is invalid: the app must skip requoting but leave its resting quotes alone.*

### Timeline

```
sim time (ns)   market                                        our app
         0      100.00 x 100.01, one more level each side
     5,000                                                    ENTER bid 99.99, ENTER ask 100.02
 5,000,000      p3 pulls its 100.01 ask
 5,000,100      p3 pulls its 100.02 ask -> no market asks left
 5,005,000                                                    seq 7 (book still valid): REPLACE bid 100.00, ask 100.03
 5,005,100                                                    seq 8: no asks -> book invalid -> quotes left alone
 7,005,000      p2 bids 100.01 (above our bid)                book invalid -> nothing
 8,005,000      p2 pulls its 100.00 bid                       book invalid -> nothing
12,000,000      p3 offers 100.04 and 100.05
12,005,000                                                    book valid: REPLACE bid 100.01, ask 100.04
```

### Start

The same opening as `gap`: 100.00 × 500 / 100.01 × 500, with p2's 99.99 × 400 and p3's 100.02 × 400 behind. Seq 1 and 2 are bids only, so the book is invalid. At seq 3, the app sends **ENTER bid 99.99** and **ENTER ask 100.02**; both join existing levels, behind the other traders.

### 5 ms: the asks disappear in two steps, and the app requotes in between

| Time | Message | Our view afterwards | What the app does |
|---|---|---|---|
| 5,005,000 | seq 7: p3's 100.01 ask deleted | 100.00 × 500 / **100.02 × 400**: still valid | Fair value = (100.00 × 400 + 100.02 × 500) / 900 = **100.0111**: **REPLACE bid → 100.00**, **REPLACE ask → 100.03** |
| 5,005,100 | seq 8: p3's 100.02 ask deleted | no asks | **Book invalid**: `CheckBook` throws, `Requote` skips. Our quotes stay where they are |

**The prices left in place came from a half-updated book.** The asks disappeared in two messages, and in the 100 ns between them the book was briefly valid at a higher best ask. That's the same price-every-message effect as in `loss` at 3 ms, but harmless here.

**On the exchange from 5,015,000, our ask at 100.03 is the only ask on the entire exchange.** Our app still sees the ask side as "empty", because its view excludes its own orders.

### 5 to 12 ms: book invalid, nothing touched

| Time | Message | What the app does |
|---|---|---|
| 5,020,000 | seq 9 and 10: our replaces in the feed | Book invalid: **throws** (×2) |
| 5,025,000 | Two `REPLACED` reports (bid live at 100.00, ask at 100.03) | **Throws** (×2) |
| 7,005,000 | seq 11: p2 bids 200 at **100.01**, above our bid | **Throws** |
| 8,005,000 | seq 12: p2 pulls its 100.00 bid | **Throws** |

The bid side keeps changing, but without an ask there's no fair value to compute, so the app leaves both quotes alone. The timer ticks from 6 to 12 ms skip the volatility sample. Nothing trades, so P&L stays $0.

### 12 ms: the asks return, higher

| Time | Message | Our view afterwards | What the app does |
|---|---|---|---|
| 12,005,000 | seq 13: ask 100.04 × 300 | 100.01 × 200 / 100.04 × 300: **valid** | Fair value = (100.01 × 300 + 100.04 × 200) / 500 = **100.022**: **REPLACE bid → 100.01**, **REPLACE ask → 100.04** |
| 12,005,000 | seq 14: ask 100.05 × 300 | depth | Pending |
| 12,020,000 and 12,025,000 | Our replaces shown and confirmed | — | Quiet to the end |

The later timer ticks sample a mid of 100.025, a 2-cent rise since the last valid sample. The credit formula gives just under $0.01, so the credit stays at the minimum.

### empty_side in numbers

| | |
|---|---|
| Deliveries | 42: 16 feed messages, 6 reports, 20 timer ticks |
| Orders sent | 6: 2 ENTER, 4 REPLACE |
| Deliveries that led to an order | 3 (seq 3, seq 7, seq 13) |
| Throws | 9, all "book invalid": 2 at the start, 7 during the empty period |

### What empty_side shows

- **"Book invalid" means: skip this requote, and leave resting orders exactly where they are,** even while the other side of the market changes.
- **"Empty" means empty of *other* traders' orders.** For 7 ms our ask was the only ask on the exchange.
- **The prices left behind can come from a half-updated book.**
- **Every message during the invalid period does full work and then throws.**

---

## 3. sweep

The scenario's comment lists three steps:

1. a partial fill of our bid, with the remainder "not topped up";
2. a requote that "restores full size";
3. a full fill of our ask, re-entered "while handling the fill report".

In the actual run, **a race changes *when* steps 2 and 3 happen**. The comment describes what would happen without the race.

### Timeline

```
sim time (ns)   market                                          our app                          position
     5,000      100.00 x 100.01, three levels each side        ENTER bid 99.99, ENTER ask 100.02       0
 3,000,000      IOC sell 950: 100.00 (500), p2's 99.99 (400),
                then 50 of OUR 100 at 99.99
 3,005,000                                                      price moved: REPLACE bid 99.98, ask 100.01
 3,010,000                                                      partial fill report (50)               +50
 3,015,000      our replace arrives: the 50-share remainder
                is replaced by a fresh 100 at 99.98
 5,005,000      p2 refills 100.00 and 99.99                     REPLACE bid 99.99, ask 100.02
10,000,000      IOC buy 1000: 100.01 (500), p3's 100.02 (400),
                then ALL of our 100 at 100.02
10,005,000                                                      REPLACE bid 100.00, ask 100.03 (doomed)
10,010,000                                                      full fill report (100)                 -50
10,025,000                                                      ask replace rejected -> ENTER ask 100.03
12,005,000      p3 refills 100.01 and 100.02                    REPLACE bid 99.99, ask 100.02
```

### Start

The book has three bids (100.00 × 500, 99.99 × 400, 99.98 × 300) and three asks (100.01 × 500, 100.02 × 400, 100.03 × 300). Seq 1–3 are bids only, so the book is invalid. At seq 4, fair value is 100.005, so the app sends **ENTER bid 99.99** and **ENTER ask 100.02**. Our bid is **behind p2's 400 at 99.99**, and that queue position matters next.

### 3 ms: a partial fill

On the exchange, p4's IOC sell for 950 at 99.99 fills best price first, then oldest first:

| Order hit | Price | Shares | Feed |
|---|---|---|---|
| ref 1: p2 | 100.00 | 500 | seq 9 |
| ref 2: p2 (at 99.99 since t = 0, so ahead of us) | 99.99 | 400 | seq 10 |
| ref 7: **our bid** (at 99.99 since 15,000) | 99.99 | **50 of 100** | seq 11 |

| Message | Our view afterwards | Fair value | Action |
|---|---|---|---|
| seq 9: p2's 100.00 gone | 99.99 × 400 / 100.01 × 500 | 99.9988 | **REPLACE bid → 99.98**, **REPLACE ask → 100.01**, each for the full 100 shares |
| seq 10: p2's 99.99 gone | 99.98 × 300 / 100.01 × 500 | 99.99125 | Pending |
| seq 11: **50** of our order executed | unchanged (ours) | — | Pending |

- **3,010,000: our Executed report, for 50 at 99.99.**
  - Position **+50**. [OnExecuted](../app/execution/orders.cpp#L90) reduces the bid's open shares to 50, and the order stays live.
  - **The app sends nothing in response to the partial fill**: it only replaces an order when the *price* should change.
- **3,015,000 (exchange): the replace arrives.** Token 1 still has 50 shares live, so the replace is **valid**. The exchange removes the 50-share remainder and puts a **fresh 100-share order at 99.98** in its place. A replace always sets the size, and the app always asks for 100. So full size is restored here, as a side effect of a price-driven replace, not at 5 ms as the comment suggests.
- **3,025,000:** both replaces are confirmed.

### 5 ms: the bid refills

p2 bids again at 100.00 and 99.99. Fair value is back to 100.005, so the app sends **REPLACE bid → 99.99** and **REPLACE ask → 100.02**. Our new bid at 99.99 is behind p2's new 400.

### 10 ms: a full fill

p4's IOC buy for 1,000 at 100.02 takes p3's 500 at 100.01 (seq 18), p3's 400 at 100.02 (seq 19), then **all 100 of our ask at 100.02** (seq 20).

| Message | Our view afterwards | Fair value | Action |
|---|---|---|---|
| seq 18: p3's 100.01 gone | 100.00 × 500 / 100.02 × 400 | 100.0111 | **REPLACE bid → 100.00**; **REPLACE ask → 100.03**, which is doomed because the ask is fully filled |
| seq 19: p3's 100.02 gone | 100.00 × 500 / 100.03 × 300 | 100.01875 | Pending |
| seq 20: our ask executed | unchanged | — | Pending |

- **10,010,000: our Executed report, for 100 at 100.02.** The position goes from +50 to **−50** (short). The ask has no live order, but its replace is in flight, so **it can't re-enter yet**.
- **10,015,000 (exchange):** the bid replace succeeds. The ask replace names a fully filled token, so it's **rejected (reason D)**.
- **10,025,000:**
  - `REPLACED` confirms the bid at 100.00.
  - `REJECTED` means the ask has no order and nothing pending, so the app sends **ENTER SELL 100 at 100.03**. The position check passes: −150 is within the limit. So the re-entry happens on the *rejection*, not on the fill report.
- **10,040,000 to 10,045,000:** our new ask appears in the feed at the best ask price (inflating that level for 5 µs), then it's accepted.

### 12 ms: the asks refill

p3 offers at 100.01 and 100.02 again. Fair value is 100.005, so the app sends **REPLACE bid → 99.99** and **REPLACE ask → 100.02**. Quiet to the end.

### sweep in numbers

| | |
|---|---|
| Deliveries | 59: 26 feed messages, 13 reports, 20 timer ticks |
| Orders sent | 11: 3 ENTER, 8 REPLACE |
| Deliveries that led to an order | 6 |
| Fills | Bought 50 at 99.99 (partial); sold 100 at 100.02 (full) |
| Final position, P&L | **−50**; **+$2.25** ($1.50 realised, $0.75 unrealised) |
| Throws | 3 ("book invalid" at seq 1–3) |

### What sweep shows

- **Partial fills leave an order live with fewer shares**, and the position can end up an odd size.
- **A partial fill alone never triggers an order.** Only a price change does.
- **Every replace asks for the full 100 shares**, so a replace after a partial fill tops the order up as a side effect.
- **Whether a racing replace succeeds depends on whether the order is still live:** a partial fill means it works, a full fill means it's rejected and the app re-enters on the rejection.
- **Queue position decides who gets filled.**

---

## 4. All seven scenarios side by side

All counts come from going through each trace message by message.

| Scenario | Deliveries | Orders | Deliveries that led to an order | Throws |
|---|---|---|---|---|
| basic | 54 | 14 | 11 | 2 |
| gap | 36 | 4 | 2 | 9 |
| loss | 118 | 21 | 16 | 33 |
| position | 117 | 30 | 19 | 14 |
| quiet | 48 | 2 | 1 | 3 |
| empty_side | 42 | 6 | 3 | 9 |
| sweep | 59 | 11 | 6 | 3 |
| **Total** | **474** | **88** | **58 (about 1 in 8)** | **73** |

**Across all seven runs, about 7 out of 8 deliveries do the full amount of work and send nothing.** That matters when judging the evaluation and the decisions on the hot path.

---

## 5. Answers to the check-your-understanding questions

<details>
<summary><strong>quiet</strong></summary>

1. **Why are the quotes guaranteed to stay at 99.99 / 100.02?** The microprice is a weighted average of the best bid (100.00) and best ask (100.01), so it always lies between them. That makes bid = fair value − 0.01 lie somewhere from 99.99 up to just under 100.00, so it always rounds down to 99.99. Likewise ask = fair value + 0.01 lies somewhere from just over 100.01 up to 100.02, so it always rounds up to 100.02.
2. **What would make our bid move?** A best *price* has to change, or the credit has to widen. The credit only widens when the sampled mid moves, which also needs a best price to change. Size changes alone can't do it.

</details>

<details>
<summary><strong>empty_side</strong></summary>

1. **If p3's cancels had arrived in the opposite order, would the app have sent any orders at 5 ms?** No. Removing the 100.02 ask (depth) doesn't change fair value, and the quotes are already right. Removing the 100.01 ask then empties the ask side, so the app skips. The same market change in a different message order gives different orders.
2. **What if a buyer had sent an IOC buy at 100.03 during the empty period?** Our ask, the only one on the exchange, would be filled: we sell 100 at 100.03 and the position goes to −100. When the report arrives, the book is invalid, so `Requote` throws before quoting and there's **no re-entry** until the asks return at 12 ms. It's the same as in `loss` at 2,010,000, on the other side.

</details>

<details>
<summary><strong>sweep</strong></summary>

1. **Why did we get only 50 shares, and why did p2's 400 at 99.99 fill first?** The 950 went to the best price first (p2's 500 at 100.00), then to the oldest order at 99.99: p2's 400, there since t = 0. That left 950 − 500 − 400 = 50 for us, since we joined that level later, at 15,000.
2. **Without the replace at 3,005,000, what would our bid look like?** 50 shares at 99.99, resting until the next time its price should change. The replace sent then asks for 100 shares, which restores full size.

</details>
