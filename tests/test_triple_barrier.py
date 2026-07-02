from datetime import date

import pandas as pd

from swing.labeling.triple_barrier import triple_barrier

from .synth import weekdays


def frame(bars: list[dict]) -> pd.DataFrame:
    days = weekdays(date(2026, 1, 5), len(bars))
    df = pd.DataFrame(bars)
    df["trade_date"] = days
    df["atr14"] = 2.0  # constant ATR: stop dist = 4, target dist = 8 (2R)
    return df


BASE = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}


def test_target_first():
    bars = [BASE, BASE, {"open": 101, "high": 109, "low": 100, "close": 108}, BASE]
    out = triple_barrier(frame(bars), signal_idx=0, stop_atr_mult=2, target_r_mult=2, horizon_days=10)
    assert out.label == 1 and out.exit_reason == "target"
    assert out.entry_price == 100.0 and out.exit_price == 108.0  # entry+8
    assert out.entry_idx == 1 and out.exit_idx == 2


def test_stop_first():
    bars = [BASE, BASE, {"open": 99, "high": 100, "low": 95, "close": 96}, BASE]
    out = triple_barrier(frame(bars), 0, 2, 2, 10)
    assert out.label == 0 and out.exit_reason == "stop"
    assert out.exit_price == 96.0  # entry-4


def test_same_bar_ambiguity_resolves_to_stop():
    bars = [BASE, BASE, {"open": 100, "high": 112, "low": 94, "close": 110}, BASE]
    out = triple_barrier(frame(bars), 0, 2, 2, 10)
    assert out.exit_reason == "stop"


def test_gap_through_stop_fills_at_open():
    bars = [BASE, BASE, {"open": 90, "high": 92, "low": 89, "close": 91}, BASE]
    out = triple_barrier(frame(bars), 0, 2, 2, 10)
    assert out.exit_reason == "stop" and out.exit_price == 90.0  # worse than the stop level


def test_time_exit_at_horizon_close():
    quiet = {"open": 100.0, "high": 101.5, "low": 99.0, "close": 100.5}
    bars = [BASE] + [quiet] * 6
    out = triple_barrier(frame(bars), 0, 2, 2, horizon_days=3)
    assert out.label == 0 and out.exit_reason == "time"
    assert out.exit_idx == 4  # entry at idx 1 + 3 bars
    assert out.exit_price == 100.5


def test_no_next_bar_returns_none():
    assert triple_barrier(frame([BASE, BASE]), signal_idx=1) is None


def test_still_open_when_data_ends():
    quiet = {"open": 100.0, "high": 101.5, "low": 99.0, "close": 100.5}
    out = triple_barrier(frame([BASE, quiet, quiet]), 0, 2, 2, horizon_days=10)
    assert out.exit_reason == "open"
