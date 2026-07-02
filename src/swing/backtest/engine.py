"""Event-driven, walk-forward backtester for the rules strategy.

Trade convention — identical to labeling/triple_barrier.py (the label IS the
trade): signal on close of T, enter at open of T+1, stop = 2×ATR(T) below
entry, target = 2R above, time exit horizon_days after entry, stop checked
before target on ambiguous bars, gaps fill at the open.

Point-in-time note: indicator frames are precomputed once over the fully
adjusted series. This is legitimate because (a) every indicator is causal —
enforced by the truncation test in tests/test_no_lookahead.py — and (b) a
corporate action with ex_date after day T rescales ALL bars visible on day T
by the same constant, so ratios, flags, and fill prices are unchanged.
Fundamental/ownership features (later phases) do NOT have this property and
must be joined by knowledge_date instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from ..config import Config
from ..features.engine import MIN_BARS, NIFTY, compute_symbol_frame
from ..pipeline.store import PITStore
from .costs import round_trip_costs

WARMUP_CALENDAR_DAYS = 500


@dataclass
class Position:
    symbol: str
    setup: str
    signal_date: date
    entry_date: date
    entry: float
    stop: float
    target: float
    shares: int
    bars_held: int = 0


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict = field(default_factory=dict)


class Backtester:
    def __init__(self, store: PITStore, cfg: Config):
        self.store = store
        self.cfg = cfg

    # ---------- data preparation ----------

    def _prepare(self, universe: list[str], start: date, end: date):
        warmup_start = start - timedelta(days=WARMUP_CALENDAR_DAYS)
        ohlcv = self.store.get_ohlcv(warmup_start, end, as_of=end, symbols=universe)
        frames: dict[str, pd.DataFrame] = {}
        pos_of: dict[str, dict[date, int]] = {}
        for symbol, grp in ohlcv.groupby("symbol"):
            if len(grp) < MIN_BARS:
                continue
            frame = compute_symbol_frame(grp, atr_period=self.cfg.swing.atr_period)
            frames[symbol] = frame
            pos_of[symbol] = {d: i for i, d in enumerate(frame["trade_date"])}

        idx = self.store.get_indices(warmup_start, end, as_of=end, names=[NIFTY])
        idx = idx.sort_values("trade_date").reset_index(drop=True)
        idx["sma200"] = idx["close"].rolling(200).mean()
        idx["ret63"] = idx["close"].pct_change(63)
        nifty = idx.set_index("trade_date")
        return frames, pos_of, nifty

    # ---------- signal generation (close of day T) ----------

    def _signals(self, frames, pos_of, nifty, d: date, exclude: set[str]) -> list[dict]:
        if d not in nifty.index:
            return []
        row = nifty.loc[d]
        if pd.isna(row["sma200"]) or row["close"] <= row["sma200"]:
            return []  # regime gate
        nifty63 = row["ret63"]

        min_turnover = self.cfg.universe.min_median_traded_value_cr * 1e7
        cands = []
        for symbol, frame in frames.items():
            if symbol in exclude:
                continue
            i = pos_of[symbol].get(d)
            if i is None or i + 1 >= len(frame):
                continue  # no next bar to enter on
            bar = frame.iloc[i]
            if not (bar["setup_breakout"] or bar["setup_pullback"]):
                continue
            if pd.isna(bar["atr14"]) or bar["atr14"] <= 0 or pd.isna(bar["sma200"]):
                continue
            if pd.isna(bar.get("median_turnover20")) or bar["median_turnover20"] < min_turnover:
                continue
            rs = (bar["ret63"] - nifty63) if not (pd.isna(bar["ret63"]) or pd.isna(nifty63)) else -9.9
            cands.append(
                {
                    "symbol": symbol,
                    "setup": "breakout" if bar["setup_breakout"] else "pullback",
                    "signal_date": d,
                    "atr": float(bar["atr14"]),
                    "close": float(bar["close"]),
                    "rs": float(rs),
                    "next_i": i + 1,
                }
            )
        return sorted(cands, key=lambda c: c["rs"], reverse=True)

    # ---------- main loop ----------

    def run(self, universe: list[str], start: date, end: date) -> BacktestResult:
        cfg = self.cfg
        frames, pos_of, nifty = self._prepare(universe, start, end)
        days = [d for d in self.store.trading_days(start, end)]

        cash = cfg.risk.capital
        open_pos: list[Position] = []
        pending: list[dict] = []
        trades: list[dict] = []
        equity_rows: list[dict] = []

        def bar_for(symbol: str, d: date):
            i = pos_of[symbol].get(d)
            return None if i is None else frames[symbol].iloc[i]

        def close_trade(p: Position, d: date, price: float, reason: str):
            nonlocal cash
            buy_value = p.shares * p.entry
            sell_value = p.shares * price
            costs = round_trip_costs(cfg.costs, buy_value, sell_value, p.entry_date, d)
            cash += sell_value - costs.total
            trades.append(
                {
                    "symbol": p.symbol,
                    "setup": p.setup,
                    "signal_date": p.signal_date,
                    "entry_date": p.entry_date,
                    "entry": round(p.entry, 2),
                    "exit_date": d,
                    "exit": round(price, 2),
                    "reason": reason,
                    "shares": p.shares,
                    "gross_pnl": round(sell_value - buy_value, 2),
                    "costs": costs.total,
                    "net_pnl": round(sell_value - buy_value - costs.total, 2),
                }
            )

        for d in days:
            # 1) exits (stop checked before target; gaps fill at open; then time)
            still_open = []
            for p in open_pos:
                bar = bar_for(p.symbol, d)
                if bar is None:  # halted/absent day — hold
                    still_open.append(p)
                    continue
                o, h, low_, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
                if o <= p.stop:
                    close_trade(p, d, o, "stop")
                elif o >= p.target:
                    close_trade(p, d, o, "target")
                elif low_ <= p.stop:
                    close_trade(p, d, p.stop, "stop")
                elif h >= p.target:
                    close_trade(p, d, p.target, "target")
                # bars_held is 0 on the first post-entry bar, so the time exit
                # fires at the close of the horizon-th bar after entry — the
                # same bar the labeler's vertical barrier uses
                elif p.bars_held >= cfg.swing.horizon_days - 1:
                    close_trade(p, d, c, "time")
                else:
                    p.bars_held += 1
                    still_open.append(p)
            open_pos = still_open

            # 2) entries from yesterday's signals, at today's open
            for sig in pending:
                frame = frames[sig["symbol"]]
                i = pos_of[sig["symbol"]].get(d)
                if i is None:
                    continue  # symbol didn't trade today; signal expires
                entry = float(frame["open"].iloc[i])
                stop_dist = cfg.swing.stop_atr_mult * sig["atr"]
                stop = entry - stop_dist
                target = entry + cfg.swing.target_r_mult * stop_dist
                risk_amount = cfg.risk.capital * cfg.risk.risk_pct_per_trade / 100
                shares = math.floor(risk_amount / stop_dist)
                shares = min(shares, math.floor(cash / entry)) if entry > 0 else 0
                if shares <= 0:
                    continue
                cash -= shares * entry
                p = Position(
                    symbol=sig["symbol"],
                    setup=sig["setup"],
                    signal_date=sig["signal_date"],
                    entry_date=d,
                    entry=entry,
                    stop=stop,
                    target=target,
                    shares=shares,
                )
                # the entry bar itself can hit a barrier after the open —
                # same convention as the labeler (stop before target)
                bar = frame.iloc[i]
                if float(bar["low"]) <= p.stop:
                    close_trade(p, d, p.stop, "stop")
                elif float(bar["high"]) >= p.target:
                    close_trade(p, d, p.target, "target")
                else:
                    open_pos.append(p)
            pending = []

            # 3) new signals at close of d, capped by capacity
            capacity = cfg.risk.max_positions - len(open_pos)
            if capacity > 0:
                held = {p.symbol for p in open_pos}
                pending = self._signals(frames, pos_of, nifty, d, exclude=held)[:capacity]

            # 4) mark to market
            invested = sum(
                p.shares * float(b["close"])
                for p in open_pos
                if (b := bar_for(p.symbol, d)) is not None
            )
            equity_rows.append({"date": d, "cash": cash, "invested": invested, "equity": cash + invested})

        # close anything still open at the last available price for reporting
        for p in open_pos:
            frame = frames[p.symbol]
            close_trade(p, days[-1], float(frame["close"].iloc[-1]), "open_at_end")

        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_rows)
        from .metrics import compute_metrics

        metrics = compute_metrics(trades_df, equity_df, cfg.risk.capital, nifty, start, end)
        return BacktestResult(trades=trades_df, equity=equity_df, metrics=metrics)
