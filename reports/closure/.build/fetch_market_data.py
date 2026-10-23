"""Download the public market history behind the closure charts.

Writes raw CSVs to reports/closure/data/ with the pull time in meta.json.
Sources (public, no keys): Kraken spot OHLC, Bitstamp OHLC, Kraken Futures funding,
OKX funding history, Deribit funding history. Binance and Bitvavo are not reachable
from the build machine, so they are not used here.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "closure-charts/1.0"
NOW = datetime.now(timezone.utc)


def get(url, **params):
    for attempt in range(4):
        try:
            r = S.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


# EURC/EUR daily candles -------------------------------------------------------
k = get("https://api.kraken.com/0/public/OHLC", pair="EURCEUR", interval=1440)["result"]
rows = next(v for key, v in k.items() if key != "last")
kr = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vwap", "volume", "count"])
kr["venue"] = "kraken"
b = get("https://www.bitstamp.net/api/v2/ohlc/eurceur/", step=86400, limit=1000)["data"]["ohlc"]
bs = pd.DataFrame(b)
bs["venue"] = "bitstamp"
eurc = pd.concat([kr[["venue", "ts", "open", "high", "low", "close", "volume"]],
                  bs[["venue", "timestamp", "open", "high", "low", "close", "volume"]].rename(columns={"timestamp": "ts"})])
eurc["ts"] = eurc["ts"].astype(int)
eurc["date"] = pd.to_datetime(eurc["ts"], unit="s", utc=True).dt.date.astype(str)
for c in ["open", "high", "low", "close", "volume"]:
    eurc[c] = eurc[c].astype(float)
eurc.drop(columns="ts").to_csv(OUT / "eurc_daily.csv", index=False)

# Perpetual funding --------------------------------------------------------------
fund = []
for sym, asset in (("PF_XBTUSD", "BTC"), ("PF_ETHUSD", "ETH")):
    rates = get("https://futures.kraken.com/derivatives/api/v4/historicalfundingrates", symbol=sym)["rates"]
    for r in rates:
        fund.append({"venue": "Kraken", "asset": asset, "ts": r["timestamp"],
                     "rate": float(r["relativeFundingRate"]), "periods_per_year": 24 * 365})

for inst, asset in (("BTC-USDT-SWAP", "BTC"), ("ETH-USDT-SWAP", "ETH")):
    after, seen = None, 0
    while seen < 1200:
        params = {"instId": inst, "limit": 100}
        if after:
            params["after"] = after
        data = get("https://www.okx.com/api/v5/public/funding-rate-history", **params)["data"]
        if not data:
            break
        for r in data:
            fund.append({"venue": "OKX", "asset": asset,
                         "ts": datetime.fromtimestamp(int(r["fundingTime"]) / 1000, timezone.utc).isoformat(),
                         "rate": float(r["realizedRate"] or r["fundingRate"]),
                         "periods_per_year": 3 * 365})
        after = data[-1]["fundingTime"]
        seen += len(data)
        time.sleep(0.25)

end = int(NOW.timestamp() * 1000)
for inst, asset in (("BTC-PERPETUAL", "BTC"), ("ETH-PERPETUAL", "ETH")):
    t1 = end
    t0_floor = end - 366 * 86400 * 1000
    while t1 > t0_floor:
        t0 = max(t0_floor, t1 - 30 * 86400 * 1000)
        res = get("https://www.deribit.com/api/v2/public/get_funding_rate_history",
                  instrument_name=inst, start_timestamp=t0, end_timestamp=t1)["result"]
        for r in res:
            fund.append({"venue": "Deribit", "asset": asset,
                         "ts": datetime.fromtimestamp(r["timestamp"] / 1000, timezone.utc).isoformat(),
                         "rate": float(r["interest_1h"]), "periods_per_year": 24 * 365})
        t1 = t0
        time.sleep(0.25)

f = pd.DataFrame(fund).drop_duplicates(["venue", "asset", "ts"])
f.to_csv(OUT / "perp_funding.csv", index=False)

meta = {"pulled_at_utc": NOW.isoformat(timespec="seconds"),
        "eurc_rows": {k: int(v) for k, v in eurc.groupby("venue").size().items()},
        "eurc_range": {v: [g["date"].min(), g["date"].max()] for v, g in eurc.groupby("venue")},
        "funding_rows": {f"{v}/{a}": int(n) for (v, a), n in f.groupby(["venue", "asset"]).size().items()},
        "funding_range": {f"{v}/{a}": [g["ts"].min(), g["ts"].max()] for (v, a), g in f.groupby(["venue", "asset"])}}
(OUT / "meta.json").write_text(json.dumps(meta, indent=2))
print(json.dumps(meta, indent=2))
