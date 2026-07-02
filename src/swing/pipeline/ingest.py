"""Daily ingest and historical backfill orchestration."""

from __future__ import annotations

import contextlib
import json
from datetime import date, timedelta

from ..adapters.corporate_actions import NSECorporateActionsProvider
from ..adapters.http import NotAvailable, NSEClient
from ..adapters.nse import NSEArchiveProvider
from .store import PITStore


class Ingestor:
    def __init__(self, store: PITStore, client: NSEClient):
        self.store = store
        self.provider = NSEArchiveProvider(client)
        self.ca_provider = NSECorporateActionsProvider(client)

    def ingest_day(self, d: date) -> str:
        """Fetch and store one day. Returns 'trading', 'holiday', or 'cached'."""
        if self.store.has_ohlcv(d):
            return "cached"
        if d.weekday() >= 5:
            self.store.mark_day(d, "holiday")
            return "holiday"
        try:
            ohlcv = self.provider.fetch_cm_bhavcopy(d)
        except NotAvailable:
            self.store.mark_day(d, "holiday")
            return "holiday"
        self.store.write_ohlcv(ohlcv, d)
        # index file occasionally lags the bhavcopy; not fatal for the day
        with contextlib.suppress(NotAvailable):
            self.store.write_indices(self.provider.fetch_index_close(d), d)
        return "trading"

    def backfill(self, start: date, end: date, log=print) -> dict:
        """Resumable: already-ingested days are skipped via the disk cache/partitions."""
        counts = {"trading": 0, "holiday": 0, "cached": 0}
        d = start
        while d <= end:
            status = self.ingest_day(d)
            counts[status] += 1
            if status == "trading" and counts["trading"] % 50 == 0:
                log(f"  … {d}: {counts}")
            d += timedelta(days=1)
        return counts

    def refresh_corporate_actions(self, start: date, end: date) -> int:
        """Fetch CAs in ≤90-day chunks (the NSE API rejects long ranges)."""
        total = 0
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=89), end)
            cas = self.ca_provider.fetch(chunk_start, chunk_end)
            if not cas.empty:
                self.store.write_corporate_actions(cas)
                total += len(cas)
            chunk_start = chunk_end + timedelta(days=1)
        return total

    def snapshot_universe(self, d: date) -> list[str]:
        """Store the F&O stock universe as seen on date d."""
        symbols = self.provider.fetch_fno_universe(d)
        out_dir = self.store.meta_dir / "universe"
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{d.isoformat()}.json").write_text(json.dumps(symbols, indent=0))
        return symbols


def load_universe(store: PITStore, as_of: date) -> list[str]:
    """Most recent stored F&O universe snapshot with snapshot_date <= as_of."""
    out_dir = store.meta_dir / "universe"
    if not out_dir.exists():
        return []
    snaps = sorted(p.stem for p in out_dir.glob("*.json") if p.stem <= as_of.isoformat())
    if not snaps:
        return []
    return json.loads((out_dir / f"{snaps[-1]}.json").read_text())
