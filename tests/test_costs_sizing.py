from datetime import date

import pytest

from swing.backtest.costs import round_trip_costs
from swing.config import load_config
from swing.decision.sizing import size_position


def test_round_trip_cost_components():
    cfg = load_config().costs
    tc = round_trip_costs(cfg, buy_value=100_000, sell_value=105_000, buy_date=date(2025, 6, 2), sell_date=date(2025, 6, 12))
    # STT 0.1% each side (pre-Apr-2026 era)
    assert tc.stt == pytest.approx(100.0 + 105.0)
    assert tc.exchange == pytest.approx(205_000 * 0.00297 / 100, abs=0.01)
    assert tc.stamp == pytest.approx(15.0)
    assert tc.dp == cfg.dp_charge_per_sell
    assert tc.slippage == pytest.approx(205_000 * 5.0 / 10_000)
    assert tc.total > 300  # frictions are material — never model zero-cost trades


def test_stt_era_switch_changes_cost():
    cfg = load_config().costs
    old = round_trip_costs(cfg, 100_000, 100_000, date(2026, 3, 1), date(2026, 3, 10))
    new = round_trip_costs(cfg, 100_000, 100_000, date(2026, 5, 1), date(2026, 5, 10))
    assert new.stt > old.stt


def test_sizing_risk_math():
    # entry 200, stop 192 → ₹8 risk/share; 1% of 10L = 10,000 → 1250 shares,
    # but notional cap (25% of 10L = 2.5L → 1250 shares) binds equally here
    ps = size_position(entry=200, stop=192, capital=1_000_000, risk_pct_per_trade=1.0)
    assert ps.shares == 1250
    assert ps.risk_pct_of_capital == pytest.approx(1.0)


def test_sizing_notional_cap_binds():
    # wide stop far away → risk math alone would buy more than 25% of capital
    ps = size_position(entry=100, stop=99, capital=1_000_000, risk_pct_per_trade=1.0)
    assert ps.notional <= 250_000
    assert ps.shares == 2500


def test_sizing_rejects_inverted_stop():
    with pytest.raises(ValueError):
        size_position(entry=100, stop=105, capital=1_000_000, risk_pct_per_trade=1.0)
