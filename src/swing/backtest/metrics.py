"""After-cost performance metrics for a backtest run."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def compute_metrics(
    trades: pd.DataFrame,
    equity: pd.DataFrame,
    capital: float,
    nifty: pd.DataFrame,
    start: date,
    end: date,
) -> dict:
    m: dict = {"start": str(start), "end": str(end), "capital": capital}
    if equity.empty:
        m["error"] = "no trading days in window"
        return m

    eq = equity["equity"].to_numpy()
    years = max(len(equity) / 250, 1e-9)
    m["final_equity"] = round(float(eq[-1]), 2)
    m["net_return_pct"] = round((eq[-1] / capital - 1) * 100, 2)
    m["cagr_pct"] = round(((eq[-1] / capital) ** (1 / years) - 1) * 100, 2)

    peak = np.maximum.accumulate(eq)
    m["max_drawdown_pct"] = round(float(((eq - peak) / peak).min()) * 100, 2)
    m["exposure_pct"] = round(float((equity["invested"] / equity["equity"]).mean()) * 100, 1)

    # benchmark over the same window
    bench = nifty[(nifty.index >= start) & (nifty.index <= end)]["close"]
    if len(bench) > 1:
        m["nifty_return_pct"] = round((bench.iloc[-1] / bench.iloc[0] - 1) * 100, 2)

    if trades.empty:
        m["n_trades"] = 0
        return m

    closed = trades[trades["reason"] != "open_at_end"]
    m["n_trades"] = int(len(closed))
    m["open_at_end"] = int((trades["reason"] == "open_at_end").sum())
    if not closed.empty:
        m["hit_rate_pct"] = round((closed["reason"] == "target").mean() * 100, 1)
        m["win_rate_net_pct"] = round((closed["net_pnl"] > 0).mean() * 100, 1)
        wins, losses = closed[closed["net_pnl"] > 0], closed[closed["net_pnl"] <= 0]
        m["avg_win"] = round(float(wins["net_pnl"].mean()), 2) if not wins.empty else 0.0
        m["avg_loss"] = round(float(losses["net_pnl"].mean()), 2) if not losses.empty else 0.0
        m["total_costs"] = round(float(closed["costs"].sum()), 2)
        m["gross_pnl"] = round(float(closed["gross_pnl"].sum()), 2)
        m["net_pnl"] = round(float(closed["net_pnl"].sum()), 2)
        m["exit_breakdown"] = closed["reason"].value_counts().to_dict()
        m["by_setup"] = {
            setup: {
                "n": int(len(g)),
                "hit_rate_pct": round((g["reason"] == "target").mean() * 100, 1),
                "net_pnl": round(float(g["net_pnl"].sum()), 2),
            }
            for setup, g in closed.groupby("setup")
        }
        # buy-and-hold trades held ~horizon days; annualized turnover
        buy_value = (closed["entry"] * closed["shares"]).sum()
        m["turnover_x_capital_per_year"] = round(float(buy_value / capital / max(len(equity) / 250, 1e-9)), 2)
    return m
