from datetime import date

from swing.adapters.nse import (
    UDIFF_CUTOVER,
    cm_bhavcopy_url,
    fo_bhavcopy_url,
    index_close_url,
    parse_cm_bhavcopy,
    parse_fo_universe,
    parse_index_close,
)


def test_udiff_url():
    assert (
        cm_bhavcopy_url(date(2026, 6, 30))
        == "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260630_F_0000.csv.zip"
    )


def test_legacy_url():
    assert (
        cm_bhavcopy_url(date(2023, 6, 28))
        == "https://nsearchives.nseindia.com/content/historical/EQUITIES/2023/JUN/cm28JUN2023bhav.csv.zip"
    )


def test_cutover_boundary():
    assert "BhavCopy_NSE_CM" in cm_bhavcopy_url(UDIFF_CUTOVER)
    assert "historical/EQUITIES" in cm_bhavcopy_url(date(2024, 7, 5))


def test_index_and_fo_urls():
    assert index_close_url(date(2026, 6, 30)).endswith("ind_close_all_30062026.csv")
    assert fo_bhavcopy_url(date(2026, 6, 30)).endswith("BhavCopy_NSE_FO_0_0_0_20260630_F_0000.csv.zip")


def test_parse_udiff_cm(udiff_cm_zip):
    df = parse_cm_bhavcopy(udiff_cm_zip, date(2026, 6, 30))
    # GB (bond) series dropped; EQ and BE kept
    assert set(df["series"]) == {"EQ", "BE"}
    assert len(df) == 4
    rel = df[df["symbol"] == "RELIANCE"].iloc[0]
    assert rel["close"] == 2985.35
    assert rel["volume"] == 7421563
    assert rel["isin"] == "INE002A01018"
    assert rel["trade_date"] == date(2026, 6, 30)


def test_parse_legacy_cm(legacy_cm_zip):
    df = parse_cm_bhavcopy(legacy_cm_zip, date(2023, 6, 28))
    # BZ series dropped
    assert set(df["series"]) == {"EQ"}
    assert len(df) == 3
    tcs = df[df["symbol"] == "TCS"].iloc[0]
    assert tcs["close"] == 3338.45
    assert tcs["prev_close"] == 3300.60


def test_udiff_and_legacy_share_schema(udiff_cm_zip, legacy_cm_zip):
    new = parse_cm_bhavcopy(udiff_cm_zip, date(2026, 6, 30))
    old = parse_cm_bhavcopy(legacy_cm_zip, date(2023, 6, 28))
    assert list(new.columns) == list(old.columns)


def test_parse_index_close(index_csv):
    df = parse_index_close(index_csv, date(2026, 6, 30))
    assert len(df) == 4
    nifty = df[df["index_name"] == "Nifty 50"].iloc[0]
    assert nifty["close"] == 24285.95
    assert nifty["trade_date"] == date(2026, 6, 30)


def test_parse_fo_universe(udiff_fo_zip):
    # index futures/options (IDF/IDO) excluded; stock F&O deduped
    assert parse_fo_universe(udiff_fo_zip) == ["RELIANCE", "TCS"]
