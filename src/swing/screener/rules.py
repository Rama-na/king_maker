"""Rules-based setup selection (Phase 1 strategy — the baseline every later
layer must beat).

Pipeline: liquidity gate → regime gate → setup flags → rank by relative
strength → top-N with code-computed levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ..config import Config


@dataclass
class Idea:
    symbol: str
    as_of: date
    setup: str                    # "breakout" | "pullback"
    close: float
    atr14: float
    entry_zone: tuple[float, float]
    stop: float                   # relative to reference entry (zone mid)
    target: float
    rs_rank: float
    rel_volume: float
    ml_probability: float | None = None   # filled in Phase 2
    flags: list[str] = field(default_factory=list)


def screen(features: pd.DataFrame, regime: dict, cfg: Config, as_of: date) -> list[Idea]:
    if features.empty:
        return []

    liquid = features[
        features["median_turnover20"] >= cfg.universe.min_median_traded_value_cr * 1e7
    ]
    if not regime.get("regime_bull", False):
        # weak regime: long setups are gated off entirely in Phase 1
        # (Phase 2+ may down-weight instead — revisit with backtest evidence)
        return []

    candidates = liquid[liquid["setup_breakout"] | liquid["setup_pullback"]].copy()
    if candidates.empty:
        return []

    candidates = candidates.sort_values("rs_rank", ascending=False).head(cfg.shortlist.size)

    ideas = []
    for _, row in candidates.iterrows():
        setup = "breakout" if row["setup_breakout"] else "pullback"
        close, atr14 = float(row["close"]), float(row["atr14"])
        stop_dist = cfg.swing.stop_atr_mult * atr14
        # entry zone brackets tomorrow's likely open; ref = today's close
        zone = (round(close - 0.25 * atr14, 2), round(close + 0.5 * atr14, 2))
        flags = []
        if row.get("gap_pct", 0) and abs(row["gap_pct"]) > 0.03:
            flags.append("gapped_today")
        if row.get("atr_pct", 0) > 0.05:
            flags.append("high_volatility")
        ideas.append(
            Idea(
                symbol=row["symbol"],
                as_of=as_of,
                setup=setup,
                close=close,
                atr14=round(atr14, 2),
                entry_zone=zone,
                stop=round(close - stop_dist, 2),
                target=round(close + cfg.swing.target_r_mult * stop_dist, 2),
                rs_rank=round(float(row["rs_rank"]), 3),
                rel_volume=round(float(row["rel_volume"]), 2),
                flags=flags,
            )
        )
    return ideas
