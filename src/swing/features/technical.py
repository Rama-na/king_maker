"""Deterministic technical indicators, hand-rolled on pandas.

Hand-rolled on purpose: every indicator here uses only rolling/expanding
operations over PAST bars, which makes the no-lookahead property provable by
the truncation test in tests/test_no_lookahead.py. Nothing in this module may
ever reference a future row (no negative shifts, no centered windows).

Input: one symbol's OHLCV frame sorted by trade_date with columns
    trade_date, open, high, low, close, volume
Output of compute_indicators(): the same frame + indicator columns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder_ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return _wilder_ema(tr, period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _wilder_ema(delta.clip(lower=0), period)
    loss = _wilder_ema((-delta).clip(lower=0), period)
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = atr(df, period)
    plus_di = 100 * _wilder_ema(plus_dm, period) / tr
    minus_di = 100 * _wilder_ema(minus_dm, period) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _wilder_ema(dx, period)


def compute_indicators(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """All indicator columns for one symbol. df must be one symbol, date-sorted."""
    out = df.copy().reset_index(drop=True)
    c, h, low, v = out["close"], out["high"], out["low"], out["volume"]

    out["sma20"] = c.rolling(20).mean()
    out["sma50"] = c.rolling(50).mean()
    out["sma200"] = c.rolling(200).mean()
    out["ema20"] = c.ewm(span=20, min_periods=20, adjust=False).mean()

    ema12 = c.ewm(span=12, min_periods=12, adjust=False).mean()
    ema26 = c.ewm(span=26, min_periods=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, min_periods=9, adjust=False).mean()
    out["macd_hist"] = macd - signal

    out["rsi14"] = rsi(c, 14)
    out["adx14"] = adx(out, 14)
    out["roc20"] = c.pct_change(20)

    lowest14, highest14 = low.rolling(14).min(), h.rolling(14).max()
    out["stoch_k"] = 100 * (c - lowest14) / (highest14 - lowest14).replace(0, np.nan)

    out["atr14"] = atr(out, atr_period)
    out["atr_pct"] = out["atr14"] / c

    mid = out["sma20"]
    std = c.rolling(20).std()
    out["bb_width"] = (4 * std) / mid
    out["bb_pos"] = (c - (mid - 2 * std)) / (4 * std).replace(0, np.nan)

    out["vol_avg20"] = v.rolling(20).mean()
    if "turnover" in out.columns:
        out["median_turnover20"] = out["turnover"].rolling(20).median()
    out["rel_volume"] = v / out["vol_avg20"].replace(0, np.nan)
    obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
    out["obv_slope20"] = obv.diff(20) / out["vol_avg20"].replace(0, np.nan)

    # levels: prior N-day extremes EXCLUDING today (shift(1)) so a breakout
    # compares today's close against yesterday's lookback window
    out["high55_prior"] = h.shift(1).rolling(55).max()
    out["low20_prior"] = low.shift(1).rolling(20).min()
    out["dist_52w_high"] = c / h.shift(1).rolling(250, min_periods=100).max() - 1
    out["gap_pct"] = out["open"] / c.shift(1) - 1

    out["ret5"] = c.pct_change(5)
    out["ret20"] = c.pct_change(20)
    out["ret63"] = c.pct_change(63)

    out["sma50_rising"] = out["sma50"] > out["sma50"].shift(5)
    out["ma_stack_bull"] = (c > out["sma50"]) & (out["sma50"] > out["sma200"])

    # --- setup flags (booleans; the rules screener trades these) ---
    out["setup_breakout"] = (
        (c > out["high55_prior"])
        & (out["rel_volume"] >= 2.0)
        & out["ma_stack_bull"]
    )
    out["setup_pullback"] = (
        out["ma_stack_bull"]
        & out["sma50_rising"]
        & (low <= out["sma50"] * 1.01)   # touched the rising 50-DMA
        & (c > out["open"])              # reversal bar closing up
        & (out["rsi14"] > 40)
    )
    return out
