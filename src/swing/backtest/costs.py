"""Indian delivery-trade cost model — the single source of truth for frictions.

Every rate lives in config/config.yaml (with effective dates for STT) so the
backtester applies the rate in force on each trade's date. Slippage is charged
on both legs as bps of traded value.

Short-term capital gains tax is intentionally NOT charged per trade here; it
applies to net realized gains at the account level. Report it separately when
summarizing annual results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..config import CostsConfig


@dataclass
class TradeCosts:
    buy_value: float
    sell_value: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float
    brokerage: float
    dp: float
    slippage: float

    @property
    def total(self) -> float:
        return round(
            self.stt + self.exchange + self.sebi + self.stamp + self.gst
            + self.brokerage + self.dp + self.slippage,
            2,
        )


def round_trip_costs(
    cfg: CostsConfig,
    buy_value: float,
    sell_value: float,
    buy_date: date,
    sell_date: date,
) -> TradeCosts:
    stt_buy_rate = cfg.stt_for(buy_date).buy_pct / 100
    stt_sell_rate = cfg.stt_for(sell_date).sell_pct / 100
    stt = buy_value * stt_buy_rate + sell_value * stt_sell_rate

    turnover = buy_value + sell_value
    exchange = turnover * cfg.exchange_txn_pct / 100
    sebi = turnover * cfg.sebi_fee_pct / 100
    stamp = buy_value * cfg.stamp_duty_buy_pct / 100
    brokerage = 2 * cfg.brokerage_per_order
    gst = (brokerage + exchange + sebi) * cfg.gst_pct / 100
    dp = cfg.dp_charge_per_sell
    slippage = turnover * cfg.slippage_bps / 10_000

    return TradeCosts(
        buy_value=buy_value,
        sell_value=sell_value,
        stt=round(stt, 2),
        exchange=round(exchange, 2),
        sebi=round(sebi, 2),
        stamp=round(stamp, 2),
        gst=round(gst, 2),
        brokerage=round(brokerage, 2),
        dp=round(dp, 2),
        slippage=round(slippage, 2),
    )
