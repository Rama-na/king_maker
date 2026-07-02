"""Ingest orchestration against a stubbed NSE client (sandbox has no NSE access)."""

from datetime import date

import pytest

from swing.adapters.http import CachedResponse, NotAvailable
from swing.pipeline.ingest import Ingestor, load_universe
from swing.pipeline.store import PITStore


class StubClient:
    """Serves fixture bytes for known URLs, 404s otherwise."""

    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str, cacheable: bool = True) -> CachedResponse:
        self.requested.append(url)
        if url not in self.responses:
            raise NotAvailable(url)
        return CachedResponse(self.responses[url], from_cache=False)

    def get_json(self, url: str, cacheable: bool = True):
        raise NotAvailable(url)


@pytest.fixture
def ingestor(tmp_path, udiff_cm_zip, udiff_fo_zip, index_csv):
    from swing.adapters.nse import cm_bhavcopy_url, fo_bhavcopy_url, index_close_url

    tue = date(2026, 6, 30)
    client = StubClient(
        {
            cm_bhavcopy_url(tue): udiff_cm_zip,
            index_close_url(tue): index_csv,
            fo_bhavcopy_url(tue): udiff_fo_zip,
        }
    )
    return Ingestor(PITStore(tmp_path), client)


def test_backfill_marks_trading_holidays_and_weekends(ingestor):
    # Mon 29th has no file (treated as holiday), Tue 30th trades, Sat/Sun skipped
    counts = ingestor.backfill(date(2026, 6, 27), date(2026, 6, 30), log=lambda *_: None)
    assert counts == {"trading": 1, "holiday": 3, "cached": 0}
    assert ingestor.store.day_status(date(2026, 6, 28)) == "holiday"
    assert ingestor.store.day_status(date(2026, 6, 30)) == "trading"


def test_backfill_is_resumable(ingestor):
    ingestor.backfill(date(2026, 6, 30), date(2026, 6, 30), log=lambda *_: None)
    counts = ingestor.backfill(date(2026, 6, 30), date(2026, 6, 30), log=lambda *_: None)
    assert counts["cached"] == 1


def test_ingested_day_readable_point_in_time(ingestor):
    ingestor.ingest_day(date(2026, 6, 30))
    df = ingestor.store.get_ohlcv(
        date(2026, 6, 30), date(2026, 6, 30), as_of=date(2026, 6, 30)
    )
    assert "RELIANCE" in set(df["symbol"])
    idx = ingestor.store.get_indices(
        date(2026, 6, 30), date(2026, 6, 30), as_of=date(2026, 6, 30), names=["Nifty 50"]
    )
    assert idx["close"].iloc[0] == 24285.95


def test_universe_snapshot_roundtrip(ingestor):
    ingestor.snapshot_universe(date(2026, 6, 30))
    assert load_universe(ingestor.store, as_of=date(2026, 7, 1)) == ["RELIANCE", "TCS"]
    # a snapshot taken later must not be visible earlier
    assert load_universe(ingestor.store, as_of=date(2026, 6, 29)) == []
