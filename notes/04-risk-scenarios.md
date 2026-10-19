# The risk scenarios: `gap`, `loss` and `position`

*Written 2026-10-13. Previous: [03-reading-the-trace.md](03-reading-the-trace.md). Message-by-message walkthroughs of these runs: [05-risk-walkthroughs.md](05-risk-walkthroughs.md).*

These three scenarios trigger the risk rules, so they run code that [`basic`](03-reading-the-trace.md) never reaches. All three sent exactly the orders in their `.expected` files. To reproduce:

```sh
./build/market_maker sim/fixtures/gap.scn --trace
./build/market_maker sim/fixtures/loss.scn --trace
./build/market_maker sim/fixtures/position.scn --trace
```

Each run writes `trace.txt` and `decisions.log` into `build/out/<name>/`. The comments at the top of each `.scn` file describe what the scenario is designed to do.

## Contents

1. [gap: one missed message halts everything](#gap-one-missed-message-halts-everything)
2. [loss: losing money until the loss limit trips](#loss-losing-money-until-the-loss-limit-trips)
3. [position: the limit blocks one side only](#position-the-limit-blocks-one-side-only)
4. [The three side by side](#the-three-side-by-side)
5. [What you need to know](#what-you-need-to-know)
6. [How this connects to the rest of the assignment](#how-this-connects-to-the-rest-of-the-assignment)

---

## gap: one missed message halts everything

| Time (ns) | What happens |
|---|---|
| 5,000 | Quotes go out at 99.99 / 100.02. The market spread is only 1 cent, so with a 1-cent credit our quotes *join* existing price levels rather than improving on them. That's also why our own orders appearing in the feed causes no bump this time |
| 6,000,000 | The exchange publishes seq 8 (p5's ask at 100.03), but the simulator drops it (the `DROP` line) |
| 8,005,000 | seq 9 arrives when the app expected 8. Gap detected, and the app sends **CANCEL for both quotes**. `decisions.log` records `market data sequence gap` |
| 8,020,000–12,005,000 | Our cancels are confirmed. The market keeps moving (p3 pulls its ask, p2 bids 100.01), but the app sends nothing |

**How the code does it:**

1. **Detection.** [OnMarketData](../app/market_maker.cpp#L14) compares each sequence number with the one it expects. On a mismatch it **latches** a flag, which stays set for the rest of the run. The message is still applied to the book.
2. **The throw.** [Requote](../app/market_maker.cpp#L73) calls `CheckStanding`, which **throws** a `RiskViolation`. `Requote` catches it, and the first time only, calls [Halt](../app/market_maker.cpp#L144).
3. **The cancels.** `Halt` writes the decision-log note and calls [CancelAll](../app/execution/orders.cpp#L43). That cancels every live order, plus any enter or replace still in flight. So the two cancels go out *after* an exception has been thrown and caught.
4. **After the halt, every feed message and report still does full work**: decode, sequence check, book update, then a throw and catch in `Requote`. Six more messages go through this path.
5. **Timer ticks carry on** (volatility, P&L, reconciliation), but they never quote anyway.

**Why halt at all?** After a gap, the app's copy of the book may be wrong; here it never learned of p5's 100.03 ask. Any price computed from a wrong book could be wrong too, so pulling the quotes is the safe reaction.

---

## loss: losing money until the loss limit trips

The market steps down about 5 cents at a time. Our bid is filled five times:

| Fill | Price | How it happened |
|---|---|---|
| 2 ms | 99.99 | A seller's IOC swept through our bid |
| 3.015 ms | 99.96 | **Our own bid crossed the market.** At 3,005,000 the app saw p2's new 99.95 bid while p3's old 100.01 ask was still in its book. That gave a fair value of 99.98, so it bid 99.97. By the time the order reached the exchange, p3's new 99.96 ask was there, so we bought from it. The report says `REMOVED`: we were the aggressor |
| 5 ms | 99.94 | Swept again |
| 9 ms | 99.88 | **Stale quote hit.** The 8 ms sweep left no other bids, so the book was invalid and the app skipped requoting; the rule says resting orders stay. Our bid sat at 99.88 until p3's new 99.86 ask traded against it |
| 12 ms | 99.82 | Same pattern after the 11 ms sweep: p3's new 99.81 ask hit our 99.82 |

- **Position limit from 12,010,000.** The fifth fill takes the position to +500.
  - From then on, the bid's `CheckPosition` throws every time the app requotes, and the bid side stays empty.
  - The replace already in flight is rejected and, unlike in earlier rounds, is *not* followed by a new ENTER.
  - The ask keeps quoting.
- **Loss limit at 16 ms.** P&L is checked only on timer ticks, marked to the mid:
  - 15 ms: −$49,959 + 500 × 99.805 = **−$56.50**
  - 16 ms: −$49,959 + 500 × 99.705 = **−$106.50**, past the −$100 limit.

  [OnTimer](../app/market_maker.cpp#L110) latches the loss flag and calls `Halt` *directly*. No exception is involved on this path.
- **Why only one cancel?** `CancelAll` cancels whatever exists on each side. The bid side had nothing, because the position limit had blocked it, so only the ask (token 20) is cancelled.
- **After the halt**, the market keeps falling (18 and 21 ms). Every feed message and report throws in `Requote` and is caught: 10 messages in all.
- **The credit widens.** Each 5-cent drop is a big move for the volatility estimate. That's why our quotes sit far from fair value: at 9 ms, for example, the bid is 99.84 against a fair value of 99.88.

  | Timer | 1–2 ms | 4 ms | 7 ms | 10 ms | 13 ms | 16 ms |
  |---|---|---|---|---|---|---|
  | Credit | $0.0100 | $0.0245 | $0.0337 | $0.0400 | $0.0449 | $0.0638 |

  The 3, 6, 9 and 12 ms ticks skip the volatility sample, because the book is invalid at those moments.

---

## position: the limit blocks one side only

Five rounds, at 2, 5, 8, 11 and 14 ms, follow the same pattern:

1. A seller sweeps p2's 500 shares at 100.00 and our 100 at 99.99.
2. The app sees p2's fill first, reprices, and replaces both quotes. That includes our bid, which has *already* traded: the same race as at 5 ms in `basic`.
3. Our Executed report arrives, and the position rises by 100.
4. The bid's replace is rejected (reason D, unknown order). The bid side is now empty, so the app enters a new bid at 99.98.
5. p2 refills its 100.00 bid, and both our quotes move back.

After the fifth fill (14,010,000), the position is +500:

- **Step 4 changes.** The rejection at 14,025,000 is *not* followed by an ENTER, because a new buy would take the position to +600.
- **For the next 6 ms, every feed message and report goes through `CheckPosition` for the bid,** which throws and is caught. Then the ask is evaluated as normal. 12 messages take this path. On two of them (15,005,000 and 20,005,000) the ask then sends a replace, so the throw and catch happen *before* that order goes out.
- **At 20 ms a buyer fills our ask at 100.02.** The position drops to 400, and the bid comes straight back with an ENTER at 20,010,000.
- **The credit edges above $0.01 from 10 ms** (reaching about $0.012). The repeated sweeps and refills make the mid bounce between 100.005 and 99.995, and the volatility estimate picks that up. That's why the bid replace at 14 ms goes to 99.97, not 99.98.

---

## The three side by side

These counts come from going through each trace message by message. Confirm them in phase 5 with a counter in the code.

| | gap | loss | position |
|---|---|---|---|
| Feed messages + reports | 16 | 78 | 87 |
| Timer ticks | 20 | 40 | 30 |
| Orders sent | 4 | 21 | 30 |
| "Book invalid" throws | 2 | 10 | 2 |
| "Position limit" throws | 0 | 13 | 12 |
| Throws after a halt | 7 | 10 | 0 |
| Messages where an order went out after a throw | 1 (the cancels) | 3 | 2 |

---

## What you need to know

**1. The four risk rules: where each is checked, and how**

| Rule | Checked in | How it's done | Reaction |
|---|---|---|---|
| Book invalid | `Requote` → [CheckBook](../app/risk/risk.h#L58) | Throws; caught in `Requote` | Skip this requote; resting orders stay |
| Sequence gap | Flag latched in `OnMarketData`; checked by [CheckStanding](../app/risk/risk.h#L48) in `Requote` | Throws; caught in `Requote`, which calls `Halt` the first time | Cancel everything; stop quoting for good |
| Position limit | [QuoteSide](../app/market_maker.cpp#L95) → [CheckPosition](../app/risk/risk.h#L67) | Throws; caught in `QuoteSide` | Skip that side only |
| Loss limit | [OnTimer](../app/market_maker.cpp#L110) | Latches a flag and calls `Halt` directly; afterwards `CheckStanding` throws | Cancel everything; stop quoting for good |

**2. Risk checks run on every feed message and report**, not only when an order is about to go out. In `basic` they always passed; here they throw.

**3. `Halt` runs at most once per run.** But after a halt, every message still costs a decode, a book update and a throw.

**4. Races are normal, and the code handles them.** Replacing an order that has already filled gets rejected (reason D), and the app recovers by entering a fresh order, unless the position limit blocks that side.

**5. Stale quotes cost money.** In `loss`, our bid kept being filled while the market fell away beneath it.

---

## How this connects to the rest of the assignment

**Where we are: phases 2 and 3, understanding.** These scenarios are the rarer branches of the same flow traced in `basic`: `OnMarketData` or `OnExecutionReport` → `Requote` → `QuoteSide` → `SendQuote`. Every branch has now been seen running.

**Next: phase 4, judging the design decisions.** Two of the decisions to judge live on these paths, both in design doc §2.2.3:

- risk checks that throw exceptions;
- `Halt` marked `[[gnu::noinline]]`.

The doc argues that exceptions cost nothing when not thrown, and that "once they are thrown, we are no longer in the hotpath". These runs are the evidence for testing that claim. Questions to answer (the verdict is yours):

- How often does each kind of throw happen, compared with the number of messages?
- After each kind of throw, is the app still trading on that same message?
- What does one throw cost? Not measured yet.
- Is `Halt` on a path where speed matters?

**Then: phase 5, measuring.** These scenarios exercise any change to the risk code. `make verify` checks all 7 scenarios, so a change that alters a risk reaction even slightly fails here. To measure, add a counter or a timer around the risk checks; the brief allows changes to the app for collecting metrics.

**In the interview,** expect "what happens when…?" questions: a gap, a breached loss limit, a blocked side. Be ready to walk through one halt from detection to cancel, naming the functions involved.

**Why the firm cares about speed at all.** In this simulator, our speed can't change any outcome: simulated time freezes while our code runs, which is exactly what lets `make verify` demand identical orders. In a real market, the time between the market moving and our quote being updated is feed delay + our processing time + order delay. Only the middle part is ours to shrink. Every microsecond of it is a window in which our quotes can be traded against at prices the market has already left. `loss` shows what that costs, even though there the cause was the strategy's rules rather than slow code.
