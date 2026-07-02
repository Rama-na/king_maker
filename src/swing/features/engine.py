"""Feature engine: one structured feature record per symbol as of a date.

The record feeds three consumers with identical numbers: the rules screener
(Phase 1), the ML scorer (Phase 2), and the reasoning panel's evidence pack
(Phase 3).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..pipeline.store import PITStore
from .technical import compute_indicators

# calendar-day lookback that comfortably covers 250 trading bars + indicator warmup
LOOKBACK_CALENDAR_DAYS = 500
MIN_BARS = 210  # need sma200 + a margin before a symbol is scoreable

NIFTY = "Nifty 50"


def compute_symbol_frame(ohlcv: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """Full indicator frame for one symbol (used by backtests over windows)."""
    return compute_indicators(ohlcv.sort_values("trade_date"), atr_period=atr_period)


def market_regime(store: PITStore, as_of: date) -> dict:
    start = as_of - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    idx = store.get_indices(start, as_of, as_of=as_of, names=[NIFTY])
    if idx.empty or len(idx) < 200:
        return {"nifty_close": None, "nifty_ret63": None, "regime_bull": None}
    idx = idx.sort_values("trade_date")
    close = idx["close"]
    sma200 = close.rolling(200).mean()
    return {
        "nifty_close": float(close.iloc[-1]),
        "nifty_ret63": float(close.iloc[-1] / close.iloc[-64] - 1) if len(close) > 63 else None,
        "regime_bull": bool(close.iloc[-1] > sma200.iloc[-1]),
    }


def compute_features(
    store: PITStore,
    universe: list[str],
    as_of: date,
    atr_period: int = 14,
) -> tuple[pd.DataFrame, dict]:
    """Returns (features_df, regime). One row per scoreable symbol at as_of."""
    start = as_of - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    ohlcv = store.get_ohlcv(start, as_of, as_of=as_of, symbols=universe)
    regime = market_regime(store, as_of)

    records = []
    for _symbol, grp in ohlcv.groupby("symbol"):
        if len(grp) < MIN_BARS:
            continue
        frame = compute_symbol_frame(grp, atr_period=atr_period)
        last = frame.iloc[-1]
        if last["trade_date"] != as_of or pd.isna(last["atr14"]) or pd.isna(last["sma200"]):
            continue
        rec = last.to_dict()
        # relative strength vs the index over ~1 quarter
        if regime["nifty_ret63"] is not None and not pd.isna(last["ret63"]):
            rec["rs_vs_nifty63"] = float(last["ret63"] - regime["nifty_ret63"])
        else:
            rec["rs_vs_nifty63"] = None
        records.append(rec)

    if not records:
        return pd.DataFrame(), regime

    feats = pd.DataFrame(records)
    # cross-sectional RS percentile within today's universe
    feats["rs_rank"] = feats["rs_vs_nifty63"].rank(pct=True)
    return feats.reset_index(drop=True), regime
