"""End-to-end backtest on an engineered synthetic market."""

from datetime import date

import pytest

from swing.backtest.engine import Backtester
from swing.config import load_config
from swing.pipeline.store import PITStore

from .synth import make_index, make_ohlcv, populate_store, weekdays

N_BARS = 320
BREAKOUT_AT = 270


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    """Two symbols: MOMO breaks out at bar 270 on 3× volume then trends up;
    DULL drifts quietly. Nifty rises so the regime is bull once sma200 exists."""
    store = PITStore(tmp_path_factory.mktemp("bt"))
    days = weekdays(date(2025, 1, 6), N_BARS)
    # noise=0 keeps the engineered pattern deterministic: steady drift → bull
    # MA stack, then a clean 3% close above the 55-day high on 3× volume
    momo = make_ohlcv("MOMO", days, noise=0.0, breakout_at=BREAKOUT_AT)
    # negative drift → sma50 < sma200 → no long setup can ever fire
    dull = make_ohlcv("DULL", days, seed=2, drift=-0.0005)
    populate_store(store, [momo, dull], make_index(days))
    return store, days


def test_breakout_is_traded_to_target(market):
    store, days = market
    cfg = load_config()
    result = Backtester(store, cfg).run(["MOMO", "DULL"], days[260], days[-1])

    trades = result.trades
    assert not trades.empty, "engineered breakout produced no trades"
    momo_trades = trades[trades["symbol"] == "MOMO"]
    assert len(momo_trades) >= 1
    first = momo_trades.iloc[0]
    # signal on the breakout bar, entry the NEXT day — never same-day fills
    assert first["signal_date"] == days[BREAKOUT_AT]
    assert first["entry_date"] == days[BREAKOUT_AT + 1]
    assert first["setup"] == "breakout"
    # steady 1.5%/day run-up must reach the 2R target
    assert first["reason"] == "target"
    assert first["net_pnl"] > 0
    # costs are charged: net strictly below gross
    assert first["net_pnl"] < first["gross_pnl"]
    # the dull symbol never fires a setup
    assert trades[trades["symbol"] == "DULL"].empty


def test_metrics_shape(market):
    store, days = market
    cfg = load_config()
    m = Backtester(store, cfg).run(["MOMO", "DULL"], days[260], days[-1]).metrics
    for key in ("net_return_pct", "max_drawdown_pct", "exposure_pct", "n_trades", "hit_rate_pct", "total_costs"):
        assert key in m, f"missing metric {key}"
    assert m["n_trades"] >= 1
    assert m["total_costs"] > 0


def test_weak_regime_blocks_all_entries(tmp_path):
    """Same breakout, but the index is falling → regime gate stops everything."""
    store = PITStore(tmp_path)
    days = weekdays(date(2025, 1, 6), N_BARS)
    momo = make_ohlcv("MOMO", days, noise=0.0, breakout_at=BREAKOUT_AT)
    bear_index = make_index(days, drift=-0.0005)
    populate_store(store, [momo], bear_index)
    cfg = load_config()
    result = Backtester(store, cfg).run(["MOMO"], days[260], days[-1])
    assert result.trades.empty
    assert result.metrics.get("n_trades", 0) == 0
