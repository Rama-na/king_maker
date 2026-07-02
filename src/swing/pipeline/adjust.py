"""Corporate-action price adjustment, applied AT READ TIME as-of a given date.

Raw bhavcopy prices are stored unadjusted forever. When a caller asks for a
series "as of" date A, only corporate actions with ex_date <= A are applied.
This is what makes the store leak-free: the same historical bar can have
different adjusted values depending on the knowledge date, exactly as a trader
on that date would have seen it.

Convention (see adapters/corporate_actions.py): a price at trade_date t is
multiplied by the product of factors of all actions with t < ex_date <= as_of.
Volume is divided by the same product.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

PRICE_COLS = ("open", "high", "low", "close", "last", "prev_close")


def apply_adjustments(prices: pd.DataFrame, cas: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Return a copy of `prices` with OHLC adjusted for splits/bonuses known by as_of.

    prices: normalized OHLCV rows (multiple symbols/dates ok).
    cas: corporate-action rows (symbol, ex_date, factor, adjustable).
    """
    out = prices.copy()
    if cas.empty:
        return out

    usable = cas[(cas["adjustable"]) & (cas["factor"].notna()) & (cas["ex_date"] <= as_of)]
    if usable.empty:
        return out

    for symbol, events in usable.groupby("symbol"):
        mask = out["symbol"] == symbol
        if not mask.any():
            continue
        events = events.sort_values("ex_date")
        ex_dates = np.array(events["ex_date"].tolist())
        factors = events["factor"].to_numpy(dtype=float)
        # suffix[i] = product of factors[i:]; suffix[n] = 1.0
        suffix = np.concatenate([np.cumprod(factors[::-1])[::-1], [1.0]])
        trade_dates = np.array(out.loc[mask, "trade_date"].tolist())
        # actions strictly after t apply to the price at t
        idx = np.searchsorted(ex_dates, trade_dates, side="right")
        row_factor = suffix[idx]
        for col in PRICE_COLS:
            if col in out.columns:
                out.loc[mask, col] = out.loc[mask, col].to_numpy(dtype=float) * row_factor
        if "volume" in out.columns:
            out.loc[mask, "volume"] = out.loc[mask, "volume"].to_numpy(dtype=float) / row_factor
    return out
