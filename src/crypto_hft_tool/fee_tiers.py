"""
Fee tier presets for Binance and Kraken spot trading.

Sources (verify before any external report):
- Binance VIP schedule: https://www.binance.com/en/fee/schedule
- Kraken Pro fee schedule: https://www.kraken.com/features/fee-schedule

Fees here are decimals (0.001 = 0.10%).
"""
from dataclasses import dataclass
from typing import Dict, Literal

ExchangeName = Literal["binance", "kraken"]
FeeType = Literal["maker", "taker"]


@dataclass(frozen=True)
class TierFees:
    name: str
    binance_maker: float
    binance_taker: float
    kraken_maker: float
    kraken_taker: float
    monthly_volume_usd: float    # Approx volume needed to reach this tier
    note: str = ""

    def get(self, exchange: ExchangeName, side: FeeType) -> float:
        return getattr(self, f"{exchange}_{side}")


# ── Preset tiers ─────────────────────────────────────────────────────────────
# Numbers below are the publicly published retail schedules.
# Confirm the live schedule on each exchange before publishing any results.

PRESETS: Dict[str, TierFees] = {
    "retail": TierFees(
        name="Retail (VIP 0 / Kraken Tier 0)",
        binance_maker=0.0010, binance_taker=0.0010,
        kraken_maker=0.0025,  kraken_taker=0.0040,
        monthly_volume_usd=0,
        note="Default published fees, no discounts.",
    ),

    "retail_bnb": TierFees(
        name="Retail + BNB discount (25% off Binance)",
        binance_maker=0.00075, binance_taker=0.00075,
        kraken_maker=0.0025,   kraken_taker=0.0040,
        monthly_volume_usd=0,
        note="Holding BNB enables 25% Binance fee discount. No Kraken equivalent.",
    ),

    "vip3": TierFees(
        name="Binance VIP 3 / Kraken Pro Tier 3",
        binance_maker=0.00042, binance_taker=0.00060,
        kraken_maker=0.0012,   kraken_taker=0.0024,
        monthly_volume_usd=20_000_000,
        note="~$20M/month volume. Realistic for a serious prop shop.",
    ),

    "vip5": TierFees(
        name="Binance VIP 5 / Kraken Pro Tier 5",
        binance_maker=0.00036, binance_taker=0.00048,
        kraken_maker=0.0004,   kraken_taker=0.0020,
        monthly_volume_usd=150_000_000,
        note="~$150M/month. Mid-size institutional.",
    ),

    "vip9": TierFees(
        name="Binance VIP 9 / Kraken Pro Tier 10",
        binance_maker=0.00012, binance_taker=0.00024,
        kraken_maker=0.0000,   kraken_taker=0.0010,
        monthly_volume_usd=5_000_000_000,
        note="Top published tier. Effectively maker-rebate territory.",
    ),

    "market_maker": TierFees(
        name="Registered Market Maker (negative maker fees)",
        binance_maker=-0.00005, binance_taker=0.00020,
        kraken_maker=-0.0001,   kraken_taker=0.0010,
        monthly_volume_usd=100_000_000,
        note="Exchanges pay you to provide liquidity. Requires application + obligations.",
    ),

    "dekabank_proxy": TierFees(
        name="DekaBank-scale proxy (assumed institutional tier)",
        binance_maker=0.00030, binance_taker=0.00040,
        kraken_maker=0.0002,   kraken_taker=0.0014,
        monthly_volume_usd=100_000_000,
        note=(
            "DekaBank does not trade on Binance/Kraken directly — it routes through "
            "Boerse Stuttgart Digital. This preset is a *proxy* approximating the "
            "fees a Deka-scale player would face if running this strategy on a "
            "regulated venue with negotiated institutional rates. Treat as illustrative."
        ),
    ),

    "zero_fee": TierFees(
        name="Zero fees (illustrative only — do NOT report as a real scenario)",
        binance_maker=0.0, binance_taker=0.0,
        kraken_maker=0.0,  kraken_taker=0.0,
        monthly_volume_usd=0,
        note=(
            "Included to show gross PnL before any fee drag. "
            "Label clearly in any output — no real venue charges zero fees."
        ),
    ),
}


def get_preset(name: str) -> TierFees:
    if name not in PRESETS:
        raise KeyError(
            f"Unknown fee tier preset '{name}'. "
            f"Available: {list(PRESETS.keys())}"
        )
    return PRESETS[name]


def list_presets() -> list:
    return list(PRESETS.keys())
