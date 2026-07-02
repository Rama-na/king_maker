"""Synthetic market data for Phase 1+ tests (sandbox has no NSE access)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from swing.pipeline.store import PITStore


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_ohlcv(
    symbol: str,
    days: list[date],
    base: float = 100.0,
    drift: float = 0.0005,
    noise: float = 0.004,
    volume: float = 1_000_000,
    seed: int = 7,
    breakout_at: int | None = None,
    breakout_jump: float = 0.03,
    breakout_run: float = 0.015,
) -> pd.DataFrame:
    """Gently drifting series; optionally an engineered volume breakout at bar
    `breakout_at` followed by a steady run-up."""
    rng = np.random.default_rng(seed)
    n = len(days)
    closes, vols = [], []
    c = base
    for i in range(n):
        if breakout_at is not None and i == breakout_at:
            c *= 1 + breakout_jump
            vols.append(volume * 3)
        elif breakout_at is not None and i > breakout_at:
            c *= 1 + breakout_run
            vols.append(volume)
        else:
            c *= 1 + drift + rng.normal(0, noise)
            vols.append(volume)
        closes.append(c)
    closes = np.array(closes)
    opens = np.concatenate([[base], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.005
    lows = np.minimum(opens, closes) * 0.995
    return pd.DataFrame(
        {
            "trade_date": days,
            "symbol": symbol,
            "series": "EQ",
            "isin": f"INE{symbol[:6]:<6}01",
            "open": opens.round(2),
            "high": highs.round(2),
            "low": lows.round(2),
            "close": closes.round(2),
            "last": closes.round(2),
            "prev_close": opens.round(2),
            "volume": vols,
            "turnover": (closes * np.array(vols)).round(2),
            "trades": 10_000,
        }
    )


def make_index(days: list[date], base: float = 20_000.0, drift: float = 0.0005) -> pd.DataFrame:
    closes = base * np.cumprod(np.full(len(days), 1 + drift))
    return pd.DataFrame(
        {
            "trade_date": days,
            "index_name": "Nifty 50",
            "open": closes * 0.999,
            "high": closes * 1.004,
            "low": closes * 0.996,
            "close": closes,
            "pe": 22.0,
            "pb": 3.5,
            "div_yield": 1.2,
        }
    )


def populate_store(
    store: PITStore, symbol_frames: list[pd.DataFrame], index_df: pd.DataFrame
) -> None:
    days = index_df["trade_date"].tolist()
    by_day = pd.concat(symbol_frames, ignore_index=True).groupby("trade_date")
    for d in days:
        store.write_ohlcv(by_day.get_group(d).reset_index(drop=True), d)
        store.write_indices(index_df[index_df["trade_date"] == d].reset_index(drop=True), d)
