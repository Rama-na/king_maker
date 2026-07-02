"""Triple-barrier labeling (López de Prado) with the project's trade convention.

Convention shared with the backtester — the label IS the trade:
- Signal computed on close of day T.
- Entry at the OPEN of day T+1 (the first bar after the information existed).
- Stop  = entry − stop_atr_mult × ATR(T)        (lower barrier)
- Target= entry + target_r_mult × stop distance (upper barrier)
- Vertical barrier: horizon_days trading days after entry, exit at that close.
- Same-bar ambiguity: if a bar's low breaches the stop AND its high reaches the
  target, the STOP is assumed to hit first (conservative).
- Entry bar itself can hit barriers (after the open).

Label 1 = target first, 0 = stop or time first.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BarrierOutcome:
    label: int            # 1 target-first, 0 otherwise
    exit_reason: str      # "target" | "stop" | "time" | "open"
    entry_price: float
    exit_price: float
    entry_idx: int        # positional index of entry bar in the frame
    exit_idx: int
    ret: float            # gross return, pre-cost


def triple_barrier(
    frame: pd.DataFrame,
    signal_idx: int,
    stop_atr_mult: float = 2.0,
    target_r_mult: float = 2.0,
    horizon_days: int = 10,
) -> BarrierOutcome | None:
    """Resolve barriers for a signal at positional index signal_idx.

    frame: one symbol's date-sorted OHLCV+atr14 frame (needs open/high/low/close/atr14).
    Returns None if there is no next bar to enter on, or ATR is unavailable.
    Outcome with exit_reason="open" means the position is still open at the end
    of available data (usable for live tracking, excluded from training).
    """
    if signal_idx + 1 >= len(frame):
        return None
    atr_val = frame["atr14"].iloc[signal_idx]
    if pd.isna(atr_val) or atr_val <= 0:
        return None

    entry_idx = signal_idx + 1
    entry = float(frame["open"].iloc[entry_idx])
    stop_dist = stop_atr_mult * float(atr_val)
    stop = entry - stop_dist
    target = entry + target_r_mult * stop_dist
    last_idx = min(entry_idx + horizon_days, len(frame) - 1)

    for i in range(entry_idx, last_idx + 1):
        bar_open = float(frame["open"].iloc[i])
        bar_high = float(frame["high"].iloc[i])
        bar_low = float(frame["low"].iloc[i])
        # gap through a barrier at the open fills at the open, not the barrier
        if bar_open <= stop:
            return BarrierOutcome(0, "stop", entry, bar_open, entry_idx, i, bar_open / entry - 1)
        if bar_open >= target:
            return BarrierOutcome(1, "target", entry, bar_open, entry_idx, i, bar_open / entry - 1)
        if bar_low <= stop:  # conservative: stop checked before target intrabar
            return BarrierOutcome(0, "stop", entry, stop, entry_idx, i, stop / entry - 1)
        if bar_high >= target:
            return BarrierOutcome(1, "target", entry, target, entry_idx, i, target / entry - 1)

    exit_price = float(frame["close"].iloc[last_idx])
    if last_idx < entry_idx + horizon_days:
        # ran out of data before the vertical barrier — still open
        return BarrierOutcome(0, "open", entry, exit_price, entry_idx, last_idx, exit_price / entry - 1)
    return BarrierOutcome(0, "time", entry, exit_price, entry_idx, last_idx, exit_price / entry - 1)
