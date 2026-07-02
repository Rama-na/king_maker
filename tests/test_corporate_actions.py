from datetime import date

from swing.adapters.corporate_actions import parse_ca_records, parse_subject


def test_bonus_1_1():
    kind, factor = parse_subject("Bonus 1:1")
    assert kind == "bonus"
    assert factor == 0.5


def test_bonus_1_2():
    # 1 new share for every 2 held → 3 shares where 2 existed → price × 2/3
    kind, factor = parse_subject("Annual General Meeting/Bonus 1:2")
    assert kind == "bonus"
    assert abs(factor - 2 / 3) < 1e-12


def test_split_10_to_2():
    kind, factor = parse_subject(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
    )
    assert kind == "split"
    assert factor == 0.2


def test_split_to_re1():
    kind, factor = parse_subject("Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share")
    assert kind == "split"
    assert factor == 0.5


def test_dividend_no_adjustment():
    kind, factor = parse_subject("Interim Dividend - Rs 8 Per Share")
    assert kind == "dividend"
    assert factor is None


def test_rights_flagged_not_derived():
    kind, factor = parse_subject("Rights 1:4 @ Premium Rs 90 Per Share")
    assert kind == "rights"
    assert factor is None


def test_reverse_split_rejected():
    # FV consolidation (2 → 10) must not produce a shrinking factor silently
    kind, factor = parse_subject("Face Value Consolidation/Split From Rs 2 To Rs 10")
    assert factor is None


def test_parse_records_drops_dividends_keeps_rights_flag():
    records = [
        {"symbol": "ABC", "subject": "Bonus 1:1", "exDate": "15-May-2026"},
        {"symbol": "DEF", "subject": "Interim Dividend - Rs 5 Per Share", "exDate": "20-May-2026"},
        {"symbol": "GHI", "subject": "Rights 1:5 @ Rs 100", "exDate": "22-May-2026"},
        {"symbol": "ABC", "subject": "Bonus 1:1", "exDate": "15-May-2026"},  # duplicate
    ]
    df = parse_ca_records(records)
    assert len(df) == 2  # dividend dropped, duplicate deduped
    bonus = df[df["symbol"] == "ABC"].iloc[0]
    assert bonus["ex_date"] == date(2026, 5, 15)
    assert bonus["adjustable"]
    rights = df[df["symbol"] == "GHI"].iloc[0]
    assert not rights["adjustable"]
    assert rights["factor"] is None or rights["factor"] != rights["factor"]  # None/NaN
