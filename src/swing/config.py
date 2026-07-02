"""Typed configuration loaded from config/config.yaml (+ .env for secrets)."""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class UniverseConfig(BaseModel):
    source: str = "nse_fno"
    static_list: list[str] = Field(default_factory=list)
    min_median_traded_value_cr: float = 5.0


class SwingConfig(BaseModel):
    atr_period: int = 14
    stop_atr_mult: float = 2.0
    target_r_mult: float = 2.0
    horizon_days: int = 10


class RiskConfig(BaseModel):
    capital: float = 1_000_000
    risk_pct_per_trade: float = 1.0
    max_positions: int = 5


class ShortlistConfig(BaseModel):
    size: int = 10


class SttRate(BaseModel):
    effective: date
    buy_pct: float
    sell_pct: float


class CostsConfig(BaseModel):
    stt: list[SttRate]
    exchange_txn_pct: float
    sebi_fee_pct: float
    stamp_duty_buy_pct: float
    gst_pct: float
    brokerage_per_order: float = 0.0
    dp_charge_per_sell: float = 15.93
    slippage_bps: float = 5.0

    def stt_for(self, trade_date: date) -> SttRate:
        applicable = [r for r in sorted(self.stt, key=lambda r: r.effective) if r.effective <= trade_date]
        if not applicable:
            raise ValueError(f"No STT rate effective on {trade_date}")
        return applicable[-1]


class DataConfig(BaseModel):
    dir: str = "data"
    backfill_years: int = 6
    request_gap_seconds: float = 1.0
    max_retries: int = 4

    @property
    def data_dir(self) -> Path:
        return Path(os.environ.get("SWING_DATA_DIR", self.dir)).expanduser()


class Config(BaseModel):
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    swing: SwingConfig = Field(default_factory=SwingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    shortlist: ShortlistConfig = Field(default_factory=ShortlistConfig)
    costs: CostsConfig
    data: DataConfig = Field(default_factory=DataConfig)


def _repo_root() -> Path:
    # src/swing/config.py -> repo root is three levels up
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> Config:
    load_dotenv()
    cfg_path = Path(path) if path else _repo_root() / "config" / "config.yaml"
    with open(cfg_path) as f:
        raw = yaml.safe_load(f)
    return Config.model_validate(raw)
