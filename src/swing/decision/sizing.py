"""Position sizing — pure code, fixed fractional risk (spec §13)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PositionSize:
    shares: int
    risk_amount: float
    risk_pct_of_capital: float
    notional: float


def size_position(
    entry: float,
    stop: float,
    capital: float,
    risk_pct_per_trade: float,
    max_notional_pct: float = 25.0,
) -> PositionSize:
    """shares = risk budget / per-share risk, capped so no single position
    exceeds max_notional_pct of capital."""
    per_share_risk = entry - stop
    if per_share_risk <= 0:
        raise ValueError(f"stop {stop} must be below entry {entry}")
    risk_amount = capital * risk_pct_per_trade / 100
    shares = math.floor(risk_amount / per_share_risk)
    max_shares = math.floor(capital * max_notional_pct / 100 / entry)
    shares = max(0, min(shares, max_shares))
    return PositionSize(
        shares=shares,
        risk_amount=round(shares * per_share_risk, 2),
        risk_pct_of_capital=round(shares * per_share_risk / capital * 100, 3),
        notional=round(shares * entry, 2),
    )
