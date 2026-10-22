# EURC live test: results and final decision

- **Source file:** `eurc_20261022_194754.xlsx`
- **Session:** 22 Oct 2026 (Thursday), 19:48:34 to 22:25:00 UTC, which is **2 h 36 min**. The test
  was stopped early; 4 h were planned.
- **Capital:** EUR 40,000 per market-making instance. The cash benchmark is 2.5 %/yr, which is
  **EUR 0.30 for this session** and EUR 1,000 for a year.

## 1. Data quality

- **Feeds.** All three venues streamed over WebSocket for the whole session.
  - Kraken dropped once (20:31:59 UTC) and recovered.
  - Bitvavo's book went up to 404 s without a change. The book was quiet, not broken.
- **Fixed bug: trade-through fills were not capped.** The simulator filled a whole resting order
  whenever any trade printed through its price. Two of the three Bitvavo fills were inflated:
  - A **0.000001 EURC** print at 1.00099 "filled" a 2,499 EURC sell.
  - A 203.5 EURC sell sweep "filled" a 1,890 EURC bid.
  
  The numbers below are corrected from the trade tape. The script now caps fills at the printed
  size, and crossed-book fills are capped and counted once. Regression tests were added.
- **Bitvavo mid is not a fair value.** The spread was 50-130 bps, and the ask sat frozen at 1.00099
  from about 20:10 to the end. Kraken (1-3 bps spread) is the honest reference. The
  `inventory_drift_eur` of -43 is mostly this artefact: the start mid of 1.0007 was inflated by an
  ask at 1.0017.

## 2. What the market looked like

| | Bitvavo | Kraken | Bitstamp |
|---|---|---|---|
| Median spread | 60.1 bps | **2.0 bps** | 74.1 bps |
| Median size at best bid | 220 EURC | 2,182 EURC | 215 EURC |
| Trades in session | 31, all before 20:10 | 68 | **0** |
| Traded volume | EUR 8,047 | EUR 30,234 | EUR 0 |
| Taker flow | 95 % sells | 75 % buys | n/a |
| Median daily volume, last 366 days | **6,454 EURC** | 333,818 EURC | 1,041 EURC |
| Days in the last year with low < 0.9925 | 28 | 20 | 23 |
| Fee (maker/taker) | 0.00 / 0.01 % | 0.20 / 0.20 % | 0.30 / 0.40 % (unverified) |

Kraken's mid sat a median **17 bps** above Bitvavo's (p10 13, p90 31). On Bitvavo, holders sell
EURC into a thin book, mostly in bursts. One seller swept **7,481 EURC from 0.99975 down to
0.98710** at 19:48:57.

## 3. Results, comparable across strategies

All figures are in EUR for this session on the stated capital. "Net" deducts every fee, the exit
cost and the 2.5 % opportunity cost.

| # | Strategy | Session result | vs bank (+0.30) | Verdict |
|---|---|---|---|---|
| 1 | Market making at the touch, Bitvavo | **-2.48** (marked at mid, ex-drift); **about -29** after liquidating the extra 2,704 EURC; 0 completed round trips | worse | Fails. Bought into a sweep: 60 s markout **-54 bps** and -13 bps |
| 2 | Market making, Kraken (0.20 % maker) | 0 fills | -0.30 | The fee is 10x the 2 bps spread; the fee-aware rule correctly never quoted |
| 3 | Market making, Bitstamp (0.30 % maker) | 0 fills, 0 venue trades | -0.30 | Dead market |
| 4 | Cross-venue taker arbitrage, 6 pairs | 0 trades. Best net edge at EUR 10 k: **-39 bps**. At top-of-book size: one second at +1.5 bps (EUR 0.03) in 9,387 s | -0.30 | Does not exist after fees |
| 5 | Deep bid on Bitvavo, sell on Kraken 300 ms later (from the tape) | 0.9925 bid: **+12.2** (+7.0 if one EUR 6 transfer is paid); 0.995: +5.7 / +0.5; 0.999: -5.2 | better, on one event | The only positive result. It rests on **one seller sweep**, roughly 2.5 k EURC of capacity |
| 6 | Perpetual cash-and-carry (Phase 1, not live-tested) | Per year, unhedged USD: about 2.4 % (365-day funding) to about 4.3 % (94-day) on EUR 40 k = EUR 960-1,720, before the EUR/USD hedge | marginal | Hedge cost (USD-EUR rate gap, not verified) eats most of the excess. Exchange and ESMA risk on 100 % of capital |
| - | Bank deposit 2.5 % | +0.30 | - | Benchmark |

Notes on row 5:
- **Fill model.** Fills use only volume that printed strictly below the bid, which is conservative.
  The exit is at Kraken's best bid with the 0.20 % taker fee.
- **Transfer cost.** Either pro-rata (EUR 6 per EUR 20 k moved) or one full EUR 6 transfer.
- **Annual estimate.** With about 28 qualifying days a year and about EUR 10 net per event, it comes
  to **EUR 100-300/yr on a EUR 5 k sleeve** (bid cash on Bitvavo plus EURC on Kraken to sell
  into). This is an assumption chain, not a measurement.

## 4. Pre-registered pass/fail test (from `docs/eurc_live_test.md`)

| Criterion | Result | |
|---|---|---|
| 1. Queue model `net_eur > 0` (liquidation basis) | about -29 | **FAIL** |
| 2. Through model `mm_pnl_mid_eur >= 0` | -2.48 | **FAIL** |
| 3. Median 60 s markout >= -1 bp | -34 bps (fills at -54 and -13) | **FAIL** |
| 4. Our fills < 20 % of venue volume | 2,704 of 7,724 EURC sold = 35 % | **FAIL** |
| 5. At least 3 sessions including a weekend | 1 session, 2.6 h | not met |

## 5. Final decision

**Deploy neither strategy. Keep the EUR 40 k in the 2.5 % deposit.**

1. **EURC market making fails on structure, not luck.** Bitvavo, the only zero-fee venue, trades a
   median of about EUR 6.5 k a day. The flow is one-way (sellers), so a market maker only
   accumulates EURC that must be exited elsewhere at a 0.20 % fee. Even taking 100 % of Bitvavo's
   volume at half the median spread would earn at most about EUR 19/day, and this session showed
   the realistic version loses money to adverse selection. More 4-hour sessions would not change
   the binding facts: volume, fees and flow direction come from 366 days of history.
2. **Cross-venue EURC arbitrage does not exist after fees.** It found one cent of opportunity in
   2.6 hours.
3. **Carry is the only scalable strategy, but at EU retail fee tiers and current funding it does
   not beat 2.5 % EUR by enough** to justify full counterparty and regulatory risk.
4. **The one real edge is too small to matter.** Deep bids absorbing EURC sell sweeps on Bitvavo
   are worth roughly EUR 100-300/yr. That doesn't move a EUR 40 k book and costs real operating
   effort: Ethereum transfers and two venues.

### What would change the decision

| Trigger | Then |
|---|---|
| Kraken BTC 90-day funding above about 7 % annualized for a sustained period, **and** ESMA/BaFin/AFM clarify the retail status of perps | Live-test carry on OKX EEA (spot as collateral, maker legs, EUR/USD hedged) |
| Circle direct redemption at par confirmed free and practical for your account (MiCA Art. 49) | Re-test the row 5 deep bid with a par exit instead of Kraken. The edge at 0.9925 rises from about 50 to about 75 bps with no 0.20 % fee |
| Bitvavo EURC/EUR volume above EUR 100 k/day for a month | Re-run this test with the fixed simulator (3 sessions incl. weekend) |

### Remaining uncertainty

- **One session.** A single Thursday evening of 2.6 h. Daytime EU hours may be busier; the
  366-day volume figures are what keep the conclusion robust.
- **Placeholder costs.** The Bitstamp fee and the EUR 5 EURC withdrawal fees are unverified
  placeholders. Neither changes the ranking.
- **Row 5 is approximate.** Kraken's exit liquidity comes from 1-second top-of-book samples, and
  Bitvavo's EURC withdrawal network compatibility with Kraken (Ethereum only) was not verified.
- **Carry hedge cost.** The carry figures come from funding history, not a live carry test, and
  the EUR/USD hedge cost was not verified.
