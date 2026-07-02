"""NSE data adapters: daily bhavcopy (equity + derivatives), index closes, F&O universe.

All downloads come from NSE's public archive host. Two bhavcopy generations exist:
- UDiFF format (from 2024-07-08): BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
- Legacy format (before):        content/historical/EQUITIES/YYYY/MMM/cmDDMMMYYYYbhav.csv.zip

Both are normalized to one schema:
    trade_date, symbol, series, isin, open, high, low, close, last, prev_close,
    volume, turnover, trades

Endpoint URLs are known to change over the years — verify against live NSE at
deploy time (this module was written against recorded payload formats).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd

from .http import NSEClient

ARCHIVES = "https://nsearchives.nseindia.com"

# First trading date the CM segment published UDiFF-format bhavcopies.
UDIFF_CUTOVER = date(2024, 7, 8)

# Equity series kept in the store. EQ = normal, BE = trade-for-trade (kept so
# universe/liquidity logic can see them; screeners filter to EQ).
EQUITY_SERIES = ("EQ", "BE")

OHLCV_COLUMNS = [
    "trade_date", "symbol", "series", "isin", "open", "high", "low", "close",
    "last", "prev_close", "volume", "turnover", "trades",
]


def cm_bhavcopy_url(d: date) -> str:
    if d >= UDIFF_CUTOVER:
        return f"{ARCHIVES}/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    mon = f"{d:%b}".upper()
    return f"{ARCHIVES}/content/historical/EQUITIES/{d:%Y}/{mon}/cm{d:%d}{mon}{d:%Y}bhav.csv.zip"


def fo_bhavcopy_url(d: date) -> str:
    return f"{ARCHIVES}/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def index_close_url(d: date) -> str:
    return f"{ARCHIVES}/content/indices/ind_close_all_{d:%d%m%Y}.csv"


def _read_zipped_csv(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as f:
            return pd.read_csv(f)


def parse_cm_bhavcopy(content: bytes, d: date) -> pd.DataFrame:
    """Parse either bhavcopy generation into the normalized OHLCV schema."""
    df = _read_zipped_csv(content)
    if "TckrSymb" in df.columns:
        out = pd.DataFrame(
            {
                "symbol": df["TckrSymb"].str.strip(),
                "series": df["SctySrs"].astype(str).str.strip(),
                "isin": df["ISIN"].astype(str).str.strip(),
                "open": df["OpnPric"],
                "high": df["HghPric"],
                "low": df["LwPric"],
                "close": df["ClsPric"],
                "last": df["LastPric"],
                "prev_close": df["PrvsClsgPric"],
                "volume": df["TtlTradgVol"],
                "turnover": df["TtlTrfVal"],
                "trades": df["TtlNbOfTxsExctd"],
            }
        )
    elif "SYMBOL" in df.columns:
        df.columns = [c.strip() for c in df.columns]
        out = pd.DataFrame(
            {
                "symbol": df["SYMBOL"].str.strip(),
                "series": df["SERIES"].astype(str).str.strip(),
                "isin": df.get("ISIN", pd.Series("", index=df.index)).astype(str).str.strip(),
                "open": df["OPEN"],
                "high": df["HIGH"],
                "low": df["LOW"],
                "close": df["CLOSE"],
                "last": df["LAST"],
                "prev_close": df["PREVCLOSE"],
                "volume": df["TOTTRDQTY"],
                "turnover": df["TOTTRDVAL"],
                "trades": df.get("TOTALTRADES", pd.Series(0, index=df.index)),
            }
        )
    else:
        raise ValueError(f"Unrecognized bhavcopy columns: {list(df.columns)[:8]}")

    out = out[out["series"].isin(EQUITY_SERIES)].copy()
    out.insert(0, "trade_date", pd.Timestamp(d).date())
    for col in ("open", "high", "low", "close", "last", "prev_close", "volume", "turnover", "trades"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[OHLCV_COLUMNS].reset_index(drop=True)


def parse_index_close(content: bytes, d: date) -> pd.DataFrame:
    """Parse ind_close_all_DDMMYYYY.csv → normalized index OHLC."""
    df = pd.read_csv(io.BytesIO(content))
    df.columns = [c.strip() for c in df.columns]
    out = pd.DataFrame(
        {
            "index_name": df["Index Name"].str.strip(),
            "open": pd.to_numeric(df["Open Index Value"], errors="coerce"),
            "high": pd.to_numeric(df["High Index Value"], errors="coerce"),
            "low": pd.to_numeric(df["Low Index Value"], errors="coerce"),
            "close": pd.to_numeric(df["Closing Index Value"], errors="coerce"),
            "pe": pd.to_numeric(df.get("P/E"), errors="coerce"),
            "pb": pd.to_numeric(df.get("P/B"), errors="coerce"),
            "div_yield": pd.to_numeric(df.get("Div Yield"), errors="coerce"),
        }
    )
    out.insert(0, "trade_date", pd.Timestamp(d).date())
    return out


def parse_fo_universe(content: bytes) -> list[str]:
    """Distinct underlying symbols with stock futures/options in an FO bhavcopy."""
    df = _read_zipped_csv(content)
    if "FinInstrmTp" not in df.columns or "TckrSymb" not in df.columns:
        raise ValueError(f"Unrecognized FO bhavcopy columns: {list(df.columns)[:8]}")
    stock_derivs = df[df["FinInstrmTp"].isin(["STF", "STO"])]
    return sorted(stock_derivs["TckrSymb"].str.strip().unique().tolist())


class NSEArchiveProvider:
    """MarketDataProvider backed by NSE's free public archives."""

    def __init__(self, client: NSEClient):
        self.client = client

    def fetch_cm_bhavcopy(self, d: date) -> pd.DataFrame:
        """Raises http.NotAvailable when d is a holiday/weekend (no file)."""
        content = self.client.get(cm_bhavcopy_url(d)).content
        return parse_cm_bhavcopy(content, d)

    def fetch_index_close(self, d: date) -> pd.DataFrame:
        content = self.client.get(index_close_url(d)).content
        return parse_index_close(content, d)

    def fetch_fno_universe(self, d: date) -> list[str]:
        content = self.client.get(fo_bhavcopy_url(d)).content
        return parse_fo_universe(content)
