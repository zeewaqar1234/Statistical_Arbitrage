"""
Run the backtester at every fee tier preset and produce a side-by-side comparison.

This is the key demo artifact for managers: it shows how the same strategy and the
same market data produce very different outcomes depending on the fee tier — proving
that fee structure is the dominant driver of profitability for stat-arb at this scale.

Usage:
    python scripts/compare_fee_tiers.py [--output-dir reports] [--trade-amount 0.001]

Output:
    reports/fee_tier_comparison_{timestamp}.csv
    reports/fee_tier_comparison_{timestamp}.txt
"""

import argparse
import csv
import os
import sys
from datetime import datetime

# Allow running from the project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crypto_hft_tool.backtest import Backtester
from src.crypto_hft_tool.fee_tiers import list_presets, get_preset


def run_comparison(out_dir: str, trade_amount: float) -> None:
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    rows = []
    for tier_name in list_presets():
        print(f"\n{'=' * 70}")
        print(f"Running backtest with tier: {tier_name}")
        print(f"{'=' * 70}")

        bt = Backtester(trade_amount=trade_amount, fee_tier=tier_name)
        bt.run_all()
        bt.save_artifacts(out_dir)

        m = bt.metrics
        tier = get_preset(tier_name)
        total_trades = sum(m["trades_per_symbol"].values())
        total_pnl    = round(m.get("total_pnl", 0.0), 4)
        total_fees   = round(m.get("total_fees", 0.0), 4)
        net_pnl      = round(total_pnl - total_fees, 4)

        rows.append({
            "tier":                         tier_name,
            "tier_label":                   tier.name,
            "monthly_volume_required_usd":  tier.monthly_volume_usd,
            "total_trades":                 total_trades,
            "total_pnl_usd":               total_pnl,
            "total_fees_usd":              total_fees,
            "net_pnl_usd":                 net_pnl,
            "win_rate_pct":                round(m.get("win_rate", 0.0), 2),
            "sharpe_ratio":                round(m.get("sharpe_ratio", 0.0), 3),
            "max_drawdown_usd":            round(m.get("max_drawdown", 0.0), 4),
        })

    if not rows:
        print("No results — did any data files load?")
        return

    # ── CSV ──────────────────────────────────────────────────────────────────
    csv_path = os.path.join(out_dir, f"fee_tier_comparison_{ts}.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote CSV  → {csv_path}")

    # ── Plain text (manager-readable) ────────────────────────────────────────
    txt_path = os.path.join(out_dir, f"fee_tier_comparison_{ts}.txt")
    with open(txt_path, "w") as f:
        f.write("FEE TIER COMPARISON — same strategy, same data, different fee tiers\n")
        f.write("=" * 70 + "\n\n")
        f.write(
            f"{'Tier':<22} {'Net PnL':>10} {'Gross PnL':>10} "
            f"{'Fees':>10} {'Trades':>7} {'Win%':>7} {'Sharpe':>7}\n"
        )
        f.write("-" * 70 + "\n")
        for r in rows:
            f.write(
                f"{r['tier']:<22} "
                f"${r['net_pnl_usd']:>9,.4f} "
                f"${r['total_pnl_usd']:>9,.4f} "
                f"${r['total_fees_usd']:>9,.4f} "
                f"{r['total_trades']:>7} "
                f"{r['win_rate_pct']:>6.2f}% "
                f"{r['sharpe_ratio']:>7.3f}\n"
            )
        f.write("\n\nDetailed notes\n" + "-" * 70 + "\n")
        for r in rows:
            tier = get_preset(r["tier"])
            f.write(f"\n{tier.name}\n")
            f.write(f"  Required 30d volume : ${r['monthly_volume_required_usd']:,.0f}\n")
            f.write(f"  Note                : {tier.note}\n")
    print(f"Wrote text → {txt_path}")
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--trade-amount", type=float, default=0.001)
    args = parser.parse_args()
    run_comparison(args.output_dir, args.trade_amount)


if __name__ == "__main__":
    main()
