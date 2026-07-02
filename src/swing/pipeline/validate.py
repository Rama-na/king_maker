"""Data-quality checks over the point-in-time store."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .store import PITStore


def validate_store(store: PITStore, start: date, end: date) -> dict:
    """Run integrity checks; returns a report dict (empty problem lists = healthy)."""
    report: dict = {"start": str(start), "end": str(end), "problems": {}}

    # 1) every weekday is accounted for: either a trading day or a marked holiday
    unaccounted = []
    d = start
    while d <= end:
        if d.weekday() < 5 and store.day_status(d) is None:
            unaccounted.append(str(d))
        d += timedelta(days=1)
    report["problems"]["unaccounted_weekdays"] = unaccounted

    trading = store.trading_days(start, end)
    report["trading_days"] = len(trading)
    if not trading:
        return report

    df = store.get_ohlcv(start, end, as_of=end, adjusted=False, series=())
    report["rows"] = len(df)

    bad_prices = df[(df["close"] <= 0) | (df["high"] < df["low"])]
    report["problems"]["bad_price_rows"] = len(bad_prices)

    dupes = df.duplicated(subset=["trade_date", "symbol", "series"]).sum()
    report["problems"]["duplicate_rows"] = int(dupes)

    # symbols disappearing mid-window (delisting/suspension is legitimate but
    # worth surfacing before features are computed over them)
    if len(trading) >= 20:
        recent = pd.Timestamp(trading[-1]).date()
        by_symbol = df.groupby("symbol")["trade_date"].max()
        stale = by_symbol[by_symbol < recent - timedelta(days=30)]
        report["problems"]["symbols_gone_30d"] = len(stale)

    report["ok"] = (
        not unaccounted and len(bad_prices) == 0 and dupes == 0
    )
    return report
