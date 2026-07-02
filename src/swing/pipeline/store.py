"""Point-in-time Parquet store.

Layout under <data_dir>/parquet:
    ohlcv/<YYYY-MM-DD>.parquet      one file per trading day (raw, unadjusted)
    indices/<YYYY-MM-DD>.parquet    all-index closes per day
    corporate_actions.parquet       one growing table (deduped)
Plus <data_dir>/meta/calendar.json  {"YYYY-MM-DD": "trading" | "holiday"}

Every read takes an explicit `as_of` and refuses to serve anything the caller
could not have known on that date:
- rows with knowledge_date > as_of are never returned, and
- asking for a window that extends past as_of raises LookaheadError outright.

Prices are stored raw; split/bonus adjustment happens at read time using only
corporate actions with ex_date <= as_of (see adjust.py).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from .adjust import apply_adjustments


class LookaheadError(Exception):
    """A read requested data beyond its declared knowledge date."""


def _iso(d: date) -> str:
    return d.isoformat()


class PITStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.ohlcv_dir = self.root / "parquet" / "ohlcv"
        self.indices_dir = self.root / "parquet" / "indices"
        self.ca_path = self.root / "parquet" / "corporate_actions.parquet"
        self.meta_dir = self.root / "meta"
        for p in (self.ohlcv_dir, self.indices_dir, self.meta_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._calendar_path = self.meta_dir / "calendar.json"

    # ---------- calendar ----------

    def _load_calendar(self) -> dict[str, str]:
        if self._calendar_path.exists():
            return json.loads(self._calendar_path.read_text())
        return {}

    def mark_day(self, d: date, status: str) -> None:
        assert status in ("trading", "holiday")
        cal = self._load_calendar()
        cal[_iso(d)] = status
        self._calendar_path.write_text(json.dumps(cal, indent=0, sort_keys=True))

    def day_status(self, d: date) -> str | None:
        return self._load_calendar().get(_iso(d))

    def trading_days(self, start: date, end: date) -> list[date]:
        cal = self._load_calendar()
        return [
            date.fromisoformat(k)
            for k, v in sorted(cal.items())
            if v == "trading" and start <= date.fromisoformat(k) <= end
        ]

    # ---------- writes ----------

    def write_ohlcv(self, df: pd.DataFrame, trade_date: date) -> None:
        """Idempotent: rewrites the day's file. knowledge_date = trade_date
        (bhavcopy is published the same evening)."""
        out = df.copy()
        out["knowledge_date"] = pd.Timestamp(trade_date).date()
        out.to_parquet(self.ohlcv_dir / f"{_iso(trade_date)}.parquet", index=False)
        self.mark_day(trade_date, "trading")

    def write_indices(self, df: pd.DataFrame, trade_date: date) -> None:
        out = df.copy()
        out["knowledge_date"] = pd.Timestamp(trade_date).date()
        out.to_parquet(self.indices_dir / f"{_iso(trade_date)}.parquet", index=False)

    def write_corporate_actions(self, df: pd.DataFrame) -> None:
        """Append + dedupe. knowledge_date = ex_date: the factor is only ever
        applied to views with as_of >= ex_date, matching when the adjusted
        price series actually changed on the exchange."""
        new = df.copy()
        new["knowledge_date"] = new["ex_date"]
        if self.ca_path.exists():
            existing = pd.read_parquet(self.ca_path)
            new = pd.concat([existing, new], ignore_index=True)
        new = new.drop_duplicates(subset=["symbol", "ex_date", "kind", "subject"])
        new.to_parquet(self.ca_path, index=False)

    # ---------- reads (all as_of-gated) ----------

    def _check_window(self, end: date, as_of: date) -> None:
        if end > as_of:
            raise LookaheadError(f"Requested data through {end} with as_of={as_of}")

    def _read_daily_dir(self, directory: Path, start: date, end: date, as_of: date) -> pd.DataFrame:
        self._check_window(end, as_of)
        files = [
            p
            for p in sorted(directory.glob("*.parquet"))
            if start <= date.fromisoformat(p.stem) <= end
        ]
        if not files:
            return pd.DataFrame()
        con = duckdb.connect()
        df = con.execute(
            "SELECT * FROM read_parquet(?) WHERE knowledge_date <= ?",
            [[str(p) for p in files], as_of],
        ).df()
        con.close()
        for col in ("trade_date", "knowledge_date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col]).dt.date
        return df

    def get_ohlcv(
        self,
        start: date,
        end: date,
        as_of: date,
        symbols: list[str] | None = None,
        series: tuple[str, ...] = ("EQ",),
        adjusted: bool = True,
    ) -> pd.DataFrame:
        df = self._read_daily_dir(self.ohlcv_dir, start, end, as_of)
        if df.empty:
            return df
        if series:
            df = df[df["series"].isin(series)]
        if symbols is not None:
            df = df[df["symbol"].isin(symbols)]
        df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
        if adjusted:
            cas = self.get_corporate_actions(as_of=as_of, symbols=symbols)
            df = apply_adjustments(df, cas, as_of=as_of)
        return df

    def get_indices(
        self, start: date, end: date, as_of: date, names: list[str] | None = None
    ) -> pd.DataFrame:
        df = self._read_daily_dir(self.indices_dir, start, end, as_of)
        if df.empty:
            return df
        if names is not None:
            df = df[df["index_name"].isin(names)]
        return df.sort_values(["index_name", "trade_date"]).reset_index(drop=True)

    def get_corporate_actions(self, as_of: date, symbols: list[str] | None = None) -> pd.DataFrame:
        if not self.ca_path.exists():
            return pd.DataFrame(
                columns=["symbol", "ex_date", "kind", "factor", "subject", "adjustable", "knowledge_date"]
            )
        df = pd.read_parquet(self.ca_path)
        for col in ("ex_date", "knowledge_date"):
            df[col] = pd.to_datetime(df[col]).dt.date
        df = df[df["knowledge_date"] <= as_of]
        if symbols is not None:
            df = df[df["symbol"].isin(symbols)]
        return df.reset_index(drop=True)

    # ---------- status ----------

    def has_ohlcv(self, d: date) -> bool:
        return (self.ohlcv_dir / f"{_iso(d)}.parquet").exists()

    def coverage(self) -> dict:
        days = sorted(p.stem for p in self.ohlcv_dir.glob("*.parquet"))
        return {
            "ohlcv_days": len(days),
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "index_days": len(list(self.indices_dir.glob("*.parquet"))),
            "corporate_actions": int(len(pd.read_parquet(self.ca_path))) if self.ca_path.exists() else 0,
        }
