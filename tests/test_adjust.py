from datetime import date

import pandas as pd

from swing.pipeline.adjust import apply_adjustments


def make_prices(symbol="ABC", closes=(100.0, 102.0, 51.5, 52.0), start=date(2026, 5, 13)):
    dates = [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15), date(2026, 5, 16)]
    return pd.DataFrame(
        {
            "trade_date": dates,
            "symbol": symbol,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000.0] * 4,
        }
    )


def cas_df(rows):
    return pd.DataFrame(rows, columns=["symbol", "ex_date", "kind", "factor", "subject", "adjustable"])


def test_bonus_halves_history_before_ex_date():
    prices = make_prices()
    cas = cas_df([("ABC", date(2026, 5, 15), "bonus", 0.5, "Bonus 1:1", True)])
    adj = apply_adjustments(prices, cas, as_of=date(2026, 5, 16))
    # before ex-date: halved; on/after ex-date: untouched
    assert adj["close"].tolist() == [50.0, 51.0, 51.5, 52.0]
    assert adj["volume"].tolist() == [2000.0, 2000.0, 1000.0, 1000.0]


def test_as_of_gates_the_adjustment():
    """The same bars viewed BEFORE the ex-date must be unadjusted — this is the
    point-in-time property that keeps backtests honest."""
    prices = make_prices().iloc[:2]
    cas = cas_df([("ABC", date(2026, 5, 15), "bonus", 0.5, "Bonus 1:1", True)])
    adj = apply_adjustments(prices, cas, as_of=date(2026, 5, 14))
    assert adj["close"].tolist() == [100.0, 102.0]


def test_multiple_actions_compound():
    prices = make_prices()
    cas = cas_df(
        [
            ("ABC", date(2026, 5, 14), "split", 0.5, "FV 10 to 5", True),
            ("ABC", date(2026, 5, 16), "bonus", 0.5, "Bonus 1:1", True),
        ]
    )
    adj = apply_adjustments(prices, cas, as_of=date(2026, 5, 16))
    # day 1: both actions after it → × 0.25; days 2-3: only bonus → × 0.5; day 4: none
    assert adj["close"].tolist() == [25.0, 51.0, 25.75, 52.0]


def test_non_adjustable_actions_ignored():
    prices = make_prices()
    cas = cas_df([("ABC", date(2026, 5, 15), "rights", None, "Rights 1:4", False)])
    adj = apply_adjustments(prices, cas, as_of=date(2026, 5, 16))
    assert adj["close"].tolist() == prices["close"].tolist()


def test_other_symbols_untouched():
    prices = pd.concat([make_prices("ABC"), make_prices("XYZ")], ignore_index=True)
    cas = cas_df([("ABC", date(2026, 5, 15), "bonus", 0.5, "Bonus 1:1", True)])
    adj = apply_adjustments(prices, cas, as_of=date(2026, 5, 16))
    assert adj[adj["symbol"] == "XYZ"]["close"].tolist() == [100.0, 102.0, 51.5, 52.0]
