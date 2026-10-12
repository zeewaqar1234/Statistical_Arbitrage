import numpy as np
import pytest

from src.crypto_hft_tool.bsdex_historical_bt import _simulate, _rolling_zscore
from src.crypto_hft_tool.config import BT_EXEC_COSTS


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("persists", [False, True])
def test_signal_commits_before_next_bar(direction, persists):
    a = 100.0 + np.sin(np.arange(200)) * .001
    b = np.full(200, 100.0)
    for i in (65, 105, 145):
        a[i] += direction * 3
        a[i + 1] += direction * (3 if persists else -3)
    spreads = (a - b) / b * 100
    trades, _ = _simulate(
        [1_790_000_000_000 + i * 60_000 for i in range(len(a))],
        a, b, spreads, _rolling_zscore(spreads, 60),
        .001, .001, 1000, True, BT_EXEC_COSTS,
    )
    assert len(trades) == 3
    assert all(t["signal_spread_pct"] > 0 for t in trades)
    assert all((t["pnl_eur"] > 0) == persists for t in trades)
    assert all(t["fill_ts"] - t["signal_ts"] == 60_000 for t in trades)


def test_fx_cost_is_in_signal_gate():
    trades, _ = _simulate(
        [1_790_000_000_000, 1_790_000_060_000], [100.005, 200], [100, 100],
        np.array([.005, 100]), np.array([2., 2.]), 0, 0, 1000, False, BT_EXEC_COSTS,
    )
    assert trades == []
