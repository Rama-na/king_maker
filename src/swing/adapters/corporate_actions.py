"""Corporate-actions adapter: fetch NSE CA announcements and extract price-adjustment factors.

NSE does not adjust historical bhavcopy prices, so we must. Regular cash
dividends are NOT adjusted (standard Indian charting convention); splits and
bonuses are. Rights issues and other complex actions are flagged but not
auto-adjusted — symbols with un-adjustable actions get a data-quality flag so
downstream features can exclude the affected window.

Adjustment factor convention: for an action effective on ex_date with factor f,
every raw price strictly BEFORE ex_date is multiplied by f (f < 1 for
splits/bonuses). Volumes are divided by f.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from fractions import Fraction

import pandas as pd

from .http import NSEClient

CA_API = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities&from_date={frm}&to_date={to}"
)

BONUS_RE = re.compile(r"bonus[^0-9]*(\d+)\s*:\s*(\d+)", re.IGNORECASE)
# e.g. "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
SPLIT_RE = re.compile(
    r"spl?i?t.*?(?:from|frm)\s*(?:rs\.?|re\.?)?\s*(\d+(?:\.\d+)?).*?"
    r"(?:to)\s*(?:rs\.?|re\.?)?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE | re.DOTALL,
)
DIVIDEND_RE = re.compile(r"dividend", re.IGNORECASE)
RIGHTS_RE = re.compile(r"rights", re.IGNORECASE)

CA_COLUMNS = ["symbol", "ex_date", "kind", "factor", "subject", "adjustable"]


def parse_subject(subject: str) -> tuple[str, float | None]:
    """Classify a CA subject line and return (kind, price_adjustment_factor).

    factor is None when no price adjustment applies (dividend) or when it
    cannot be derived automatically (rights/other).
    """
    subject = subject.strip()

    m = BONUS_RE.search(subject)
    if m:
        new, held = int(m.group(1)), int(m.group(2))
        # a:b bonus → (a+b) shares where b existed → price scales by b/(a+b)
        return "bonus", float(Fraction(held, new + held))

    m = SPLIT_RE.search(subject)
    if m:
        old_fv, new_fv = float(m.group(1)), float(m.group(2))
        if new_fv <= 0 or old_fv <= 0 or new_fv >= old_fv:
            return "other", None
        # FV 10 → 2 means 5x shares → price scales by new/old
        return "split", new_fv / old_fv

    if RIGHTS_RE.search(subject):
        return "rights", None
    if DIVIDEND_RE.search(subject):
        return "dividend", None
    return "other", None


def parse_ca_records(records: list[dict]) -> pd.DataFrame:
    """Normalize NSE corporate-action API records into the CA schema."""
    rows = []
    for rec in records:
        subject = str(rec.get("subject", ""))
        ex_raw = rec.get("exDate") or rec.get("exdate")
        if not ex_raw:
            continue
        ex_date = datetime.strptime(str(ex_raw).strip(), "%d-%b-%Y").date()
        kind, factor = parse_subject(subject)
        if kind == "dividend":
            continue  # no price adjustment for regular dividends
        rows.append(
            {
                "symbol": str(rec.get("symbol", "")).strip(),
                "ex_date": ex_date,
                "kind": kind,
                "factor": factor,
                "subject": subject,
                "adjustable": factor is not None,
            }
        )
    if not rows:
        return pd.DataFrame(columns=CA_COLUMNS)
    df = pd.DataFrame(rows)[CA_COLUMNS]
    # A single ex-date can carry both a split and a bonus (rare but real);
    # keep both rows — factors compound multiplicatively in the adjuster.
    return df.drop_duplicates(subset=["symbol", "ex_date", "kind", "subject"]).reset_index(drop=True)


class NSECorporateActionsProvider:
    def __init__(self, client: NSEClient):
        self.client = client

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        url = CA_API.format(frm=f"{start:%d-%m-%Y}", to=f"{end:%d-%m-%Y}")
        data = self.client.get_json(url, cacheable=end < date.today())
        if not isinstance(data, list):
            raise ValueError(f"Unexpected CA API payload type: {type(data)}")
        return parse_ca_records(data)
