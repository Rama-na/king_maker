"""Point-in-time guarantees of the store — the leakage gate for the data layer."""

from datetime import date

import pandas as pd
import pytest

from swing.pipeline.store import LookaheadError, PITStore


def day_df(d: date, symbol="ABC", close=100.0):
    return pd.DataFrame(
        {
            "trade_date": [d],
            "symbol": [symbol],
            "series": ["EQ"],
            "isin": ["INE000TEST01"],
            "open": [close * 0.99],
            "high": [close * 1.02],
            "low": [close * 0.98],
            "close": [close],
            "last": [close],
            "prev_close": [close * 0.995],
            "volume": [10000.0],
            "turnover": [close * 10000],
            "trades": [500],
        }
    )


@pytest.fixture
def store(tmp_path):
    s = PITStore(tmp_path)
    s.write_ohlcv(day_df(date(2026, 6, 29), close=100.0), date(2026, 6, 29))
    s.write_ohlcv(day_df(date(2026, 6, 30), close=104.0), date(2026, 6, 30))
    return s


def test_refuses_window_beyond_as_of(store):
    with pytest.raises(LookaheadError):
        store.get_ohlcv(date(2026, 6, 29), date(2026, 6, 30), as_of=date(2026, 6, 29))


def test_serves_only_known_data(store):
    df = store.get_ohlcv(date(2026, 6, 1), date(2026, 6, 29), as_of=date(2026, 6, 29))
    assert df["trade_date"].tolist() == [date(2026, 6, 29)]


def test_knowledge_date_filter_is_independent_of_window(store):
    # even if a future-dated row somehow lands in an old partition file, the
    # knowledge_date predicate must exclude it
    poisoned = day_df(date(2026, 6, 29), symbol="LEAK", close=999.0)
    poisoned["knowledge_date"] = date(2026, 7, 15)  # became public later
    existing = pd.read_parquet(store.ohlcv_dir / "2026-06-29.parquet")
    pd.concat([existing, poisoned], ignore_index=True).to_parquet(
        store.ohlcv_dir / "2026-06-29.parquet", index=False
    )
    df = store.get_ohlcv(date(2026, 6, 29), date(2026, 6, 29), as_of=date(2026, 6, 30))
    assert "LEAK" not in set(df["symbol"])


def test_adjusted_view_depends_on_as_of(store):
    cas = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "ex_date": date(2026, 6, 30),
                "kind": "bonus",
                "factor": 0.5,
                "subject": "Bonus 1:1",
                "adjustable": True,
            }
        ]
    )
    store.write_corporate_actions(cas)
    # viewed on 29th: bonus not effective yet → raw price
    before = store.get_ohlcv(date(2026, 6, 29), date(2026, 6, 29), as_of=date(2026, 6, 29))
    assert before["close"].iloc[0] == 100.0
    # viewed on 30th: history before ex-date is halved
    after = store.get_ohlcv(date(2026, 6, 29), date(2026, 6, 30), as_of=date(2026, 6, 30))
    assert after[after["trade_date"] == date(2026, 6, 29)]["close"].iloc[0] == 50.0
    assert after[after["trade_date"] == date(2026, 6, 30)]["close"].iloc[0] == 104.0


def test_calendar_and_coverage(store):
    store.mark_day(date(2026, 6, 28), "holiday")
    assert store.day_status(date(2026, 6, 28)) == "holiday"
    assert store.trading_days(date(2026, 6, 1), date(2026, 6, 30)) == [
        date(2026, 6, 29),
        date(2026, 6, 30),
    ]
    cov = store.coverage()
    assert cov["ohlcv_days"] == 2
    assert cov["first"] == "2026-06-29"


def test_write_is_idempotent(store):
    store.write_ohlcv(day_df(date(2026, 6, 30), close=104.0), date(2026, 6, 30))
    df = store.get_ohlcv(date(2026, 6, 30), date(2026, 6, 30), as_of=date(2026, 6, 30))
    assert len(df) == 1
