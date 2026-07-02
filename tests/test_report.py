from datetime import date

from swing.decision.sizing import size_position
from swing.report.daily import DISCLAIMER, render_report
from swing.screener.rules import Idea

from .synth import make_ohlcv, weekdays


def make_idea(symbol="MOMO"):
    return Idea(
        symbol=symbol, as_of=date(2026, 6, 30), setup="breakout", close=104.5,
        atr14=1.5, entry_zone=(104.1, 105.25), stop=101.5, target=110.5,
        rs_rank=0.97, rel_volume=2.7, flags=["high_volatility"],
    )


def test_report_renders_ideas_and_disclaimer(tmp_path):
    idea = make_idea()
    bars = make_ohlcv("MOMO", weekdays(date(2026, 1, 5), 120))
    sizes = {"MOMO": size_position(104.6, 101.5, 1_000_000, 1.0)}
    out = render_report(
        date(2026, 6, 30), [idea], sizes, {"regime_bull": True}, {"MOMO": bars},
        tmp_path / "r.html",
    )
    html = out.read_text()
    assert "MOMO" in html and "candlestick" in html
    assert DISCLAIMER in html
    assert "110.5" in html  # target level drawn


def test_report_empty_day(tmp_path):
    out = render_report(date(2026, 6, 30), [], {}, {"regime_bull": False}, {}, tmp_path / "r.html")
    html = out.read_text()
    assert "No qualifying setups" in html
    assert DISCLAIMER in html
