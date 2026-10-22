# EURC vs perpetual carry: strategy selection and the 4-hour live test

Prepared 2026-10-22. Market data below was pulled live on that date from public exchange APIs.
Fee and regulatory facts come from official exchange and regulator pages, read through search
extracts because the pages could not be fetched directly. Check each fee in the app before
trading. Nothing here is investment, legal or tax advice.

## 1. Data behind the decision

### Perpetual funding: the yield that cash-and-carry earns

These are annualized mean funding rates for a short position, from the public funding-history
endpoints.

| Contract | 30 d | ~90 d | 180 d | 365 d | Share of positive periods (365 d) |
|---|---|---|---|---|---|
| Kraken PF_XBTUSD (hourly) | 7.71 % | 6.57 % | 4.06 % | 3.33 % | 69 % |
| Kraken PF_ETHUSD | 6.76 % | 7.44 % | 5.65 % | 3.55 % | 69 % |
| OKX BTC-USDT-SWAP (8 h) | 4.02 % | 5.35 % (94 d) | n/a | n/a | 90 % (94 d) |
| OKX ETH-USDT-SWAP | 3.73 % | 4.41 % (94 d) | n/a | n/a | 85 % (94 d) |

These rates are in USD. A EUR investor is long USD on the whole position. That exposure is
either left open (EURUSD volatility is far larger than the edge) or hedged at roughly the
USD-minus-EUR short-rate differential. The differential was not verified today, so set it
yourself.

### Fees at the entry tier for an EU account

| Venue | Spot maker / taker | Perp maker / taker | EU perp access |
|---|---|---|---|
| OKX EEA, with an X-Perps account | 0.08 / 0.10 % | 0.02 / 0.05 % | Yes: MiFID, MFSA Malta, max 10x |
| Kraken Pro (since 9 Jul 2026) | 0.40 / 0.80 % | 0.02 / 0.05 % | Yes: MiFID, CySEC; spot and futures wallets are separate |
| Coinbase Advanced EU | 0.25 / 0.50 % | "as low as 0.02 %" | Yes: CySEC |
| Binance | 0.10 / 0.10 % | 0.02 / 0.05 % | **No.** Stopped serving the EU on 1 Jul 2026 |
| Bybit | 0.10 / 0.10 % | 0.02 / 0.055 % | **No** EU perps (MiFID application pending) |
| Bitvavo EURC/EUR | **0.00 / 0.01 %** | n/a | spot |
| Kraken EURC/EUR | 0.20 / 0.20 % (stablecoin schedule) | n/a | spot |
| Bitstamp EURC/EUR | unverified (0.30 / 0.40 % assumed) | n/a | spot, limit orders only |

On 24 Feb 2026 ESMA said perpetual futures are "likely" CFDs. If national regulators follow
that, EU retail leverage on crypto could be capped at 2:1. This is a live regulatory risk for
every EU perp venue.

### EURC/EUR books, live on 2026-10-22

- **Kraken.** Bid 0.9965, ask 0.9985 (about 20 bps wide). 24 h volume was about 1.28 M EURC; the
  2026 median is about 324 k EURC/day. The 24 h low was 0.9775. The top 25 bid levels hold only
  about 72 k EURC.
- **Bitstamp.** Bid 0.9918, ask 1.0020 (102 bps wide). 24 h volume was about 9 k EURC; the 2026
  median is about 833 EURC/day.
- **No crossed books.** Bitstamp's bid was below Kraken's ask, and Kraken's bid was below
  Bitstamp's ask. The "20-30 bps gaps" seen between venues are last prices or mids on thin
  books, not executable arbitrage.
- **Bitvavo.** Its API was unreachable from the analysis machine. Its volume is measured by the
  test.

## 2. Verdict

**Winner: Strategy 1, re-engineered.** Not cross-venue taker arbitrage, but passive EURC/EUR
market making on Bitvavo (0 % maker), with a fee-aware dip-buy rule. Bids are only posted when
the exit covers fees; with `--exit-ref par` that exit is anchored to par.

Why the carry trade loses at this size and in this jurisdiction:

1. **The realistic setup is marginal.** OKX EEA with selected-margin collateral at about 0.9x
   efficiency, maker on both legs, two round trips a year and EUR to USDC conversion gives an
   unhedged USD return of about 2.4 % on the 365-day funding regime and about 4.3 % on the
   94-day regime. FX hedging then subtracts the rate differential. Against 2.5 % EUR the excess
   is between negative and about +1-2 %, and it depends on a funding regime you cannot forecast.
2. **The cheap venues are closed to EU residents** (Binance, Bybit). Kraken's 0.40 % spot maker
   fee alone costs 0.80 % per round trip.
3. **Several risks sit on top of a thin edge:** exchange counterparty risk on 100 % of capital,
   negative-funding regimes (31 % of hours on Kraken were negative over 365 d), and the ESMA CFD
   question.
4. **A 4-hour test cannot validate it.** Carry PnL is funding accrued over months. Four hours only
   measures entry and exit cost.

Why the EURC market maker wins, with conditions:

- **No structural costs to overcome.** 0 % maker fee; no FX (EUR against EUR); no leverage or
  liquidation; no gas while staying on one venue; MiCA-compliant e-money token. Under MiCA
  Art. 49, Circle's policy is redemption at par for all holders, including retail, which
  anchors the price.
- **PnL is realised intraday,** so a live session measures what matters: fill rate, adverse
  selection (markouts), and inventory drift.
- **Capacity is small.** Roughly EUR 25-100 k before you are the market. At EUR 40 k, beating
  2.5 % means about EUR 1,000/yr, or about EUR 2.75/day.
- **It is unproven.** Simulated passive fills are the most common source of fake backtest
  profit. The test brackets the truth with two fill models and records markouts.

When to switch to carry: capital in the millions (VIP fees), sustained 90-day funding above
about 7 % annualized, and clarity on the ESMA question.

## 3. Pre-registered pass/fail criteria for the test

The Bitvavo strategy goes to a small real-money pilot only if **all** of these hold, on
**at least 3 sessions** (one of them at a weekend):

1. Under the queue fill model, `net_eur > 0`, which is after the 2.5 % opportunity cost, using
   the conservative `mm_pnl_liq_eur`.
2. Under the through fill model (pessimistic), `mm_pnl_mid_eur >= 0`.
3. The median `markout_60s_bps` on fills is at least -1 bp. Anything worse means you are being
   picked off.
4. Our simulated fill volume is under 20 % of the venue's traded volume (Venues sheet).
   Anything higher means the simulation assumes liquidity that is not there.

## 4. Running the test

```bash
git fetch origin claude/trading-tool-docs-4684tx
git checkout claude/trading-tool-docs-4684tx
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt && pip install -U ccxt

python scripts/eurc_live_test.py --check            # 30 s: every venue should say OK
python scripts/eurc_live_test.py --minutes 5        # smoke test, then open the .xlsx
python scripts/eurc_live_test.py --hours 4          # the real run
```

- **Output.** `reports/eurc_<UTC>/eurc_<UTC>.xlsx`, plus CSVs written while the test runs. Send
  back the `.xlsx`.
- **Interrupting.** Ctrl+C stops early and still writes the workbook. If the machine sleeps or
  the run crashes:
  `python scripts/eurc_live_test.py --rebuild reports/eurc_<UTC>`
- **Keep the machine awake.** Disable sleep for the 4 hours (on macOS, `caffeinate -i python ...`).

Useful options:

- `--exit-ref par` trusts redemption at par, so the quoter keeps bidding below par even when the
  ask is low.
- `--fee venue:maker:taker` overrides a fee, for example after checking your own tier in the app.
- `--transfer-override venue:eurc_fee:sepa_fee` sets the real EURC withdrawal fee once known.
  The default is a EUR 5 placeholder.
- `--capital-eur` (default EUR 40 k), `--quote-eur` (default EUR 2.5 k per quote) and `--latency-ms`
  (default 300 ms, +/- 100 ms jitter) set size and speed.
- `--min-eurc-frac` / `--max-eurc-frac` (default 25-75 %) bound the inventory. Quote size shrinks
  as inventory moves away from 50/50.

## 5. What the workbook contains

| Sheet | Content |
|---|---|
| Summary | One row per strategy instance: fills, volume, realised PnL, fees, drift, PnL marked at mid and at liquidation, opportunity cost, `net_eur`, `beats_hurdle` |
| Venues | Spread distribution, top-of-book size, traded volume per hour, buy/sell split |
| MM_Fills | Every simulated fill: queue position at go-live, time to fill, fill reason, 5 s and 60 s markouts |
| Arb_Trades | Every cross-venue trade: decision edge vs realised edge after latency, fees, transfer cost |
| Equity | Per-minute snapshots of every instance |
| Ladder_Backtest / History_Daily | Daily candles and a resting dip-buy ladder backtest |
| Fees / TransferCosts / Parameters | Every cost assumption, with source and verification status |
| FeedHealth / Errors | WebSocket or REST mode, gaps, errors (check these before trusting results) |
| Tape / Market_1s / Quotes | Raw data for re-analysis, e.g. different fees offline |

Known simplifications:

- Simulated orders are not in the real book. They never move the market, and real traders never
  queue behind them.
- The queue model assumes cancellations at our price came from orders ahead of us.
- Arbitrage inventory is assumed to be restored by transfers whose cost is charged pro-rata.
- Daily-candle wicks show that a price printed, not that size was available at it.
