"""`swing` — command-line entrypoint.

Phase 0 commands: backfill, ingest, universe, validate, status.
Later phases add: run, backtest, train, report, serve, outcomes.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import typer
from rich.console import Console

from .config import load_config

app = typer.Typer(no_args_is_help=True, help=__doc__)
console = Console()


def _make_ingestor():
    from .adapters.http import NSEClient
    from .pipeline.ingest import Ingestor
    from .pipeline.store import PITStore

    cfg = load_config()
    data_dir = cfg.data.data_dir
    store = PITStore(data_dir)
    client = NSEClient(
        cache_dir=data_dir / "cache" / "http",
        request_gap_seconds=cfg.data.request_gap_seconds,
        max_retries=cfg.data.max_retries,
    )
    return cfg, store, Ingestor(store, client)


@app.command()
def backfill(
    years: int = typer.Option(None, help="Years of history (default: config data.backfill_years)"),
    start: str = typer.Option(None, help="Start date YYYY-MM-DD (overrides --years)"),
    end: str = typer.Option(None, help="End date YYYY-MM-DD (default: today)"),
):
    """Download historical bhavcopies, index closes, and corporate actions."""
    cfg, store, ingestor = _make_ingestor()
    end_d = date.fromisoformat(end) if end else date.today()
    if start:
        start_d = date.fromisoformat(start)
    else:
        start_d = end_d - timedelta(days=365 * (years or cfg.data.backfill_years))

    console.print(f"[bold]Backfilling OHLCV {start_d} → {end_d}[/bold]")
    counts = ingestor.backfill(start_d, end_d, log=console.print)
    console.print(f"OHLCV done: {counts}")

    console.print("Fetching corporate actions…")
    n = ingestor.refresh_corporate_actions(start_d, end_d)
    console.print(f"Corporate actions stored: {n}")

    days = store.trading_days(start_d, end_d)
    if days:
        console.print("Snapshotting F&O universe…")
        symbols = ingestor.snapshot_universe(days[-1])
        console.print(f"Universe: {len(symbols)} symbols as of {days[-1]}")


@app.command()
def ingest(day: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)")):
    """Ingest a single day (the nightly job's data step)."""
    _, _, ingestor = _make_ingestor()
    d = date.fromisoformat(day) if day else date.today()
    status = ingestor.ingest_day(d)
    console.print(f"{d}: {status}")


@app.command()
def universe(day: str = typer.Option(None, "--date", help="YYYY-MM-DD trading day")):
    """Snapshot the F&O stock universe from that day's FO bhavcopy."""
    _, store, ingestor = _make_ingestor()
    d = date.fromisoformat(day) if day else date.today()
    symbols = ingestor.snapshot_universe(d)
    console.print(f"{len(symbols)} F&O symbols as of {d}")


@app.command()
def validate(
    start: str = typer.Argument(..., help="YYYY-MM-DD"),
    end: str = typer.Argument(..., help="YYYY-MM-DD"),
):
    """Run data-quality checks over the stored window."""
    from .pipeline.validate import validate_store

    _, store, _ = _make_ingestor()
    report = validate_store(store, date.fromisoformat(start), date.fromisoformat(end))
    console.print_json(json.dumps(report))
    raise typer.Exit(0 if report.get("ok") else 1)


@app.command()
def status():
    """Show store coverage."""
    _, store, _ = _make_ingestor()
    console.print_json(json.dumps(store.coverage()))


@app.command()
def run(day: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)")):
    """Nightly research run: ingest → features → screen → size → HTML report."""
    from datetime import timedelta

    from .decision.sizing import size_position
    from .features.engine import compute_features
    from .pipeline.ingest import load_universe
    from .screener.rules import screen

    cfg, store, ingestor = _make_ingestor()
    d = date.fromisoformat(day) if day else date.today()

    status = ingestor.ingest_day(d)
    if status == "holiday":
        console.print(f"[yellow]{d} is not a trading day — nothing to do.[/yellow]")
        raise typer.Exit(0)
    ingestor.refresh_corporate_actions(d - timedelta(days=30), d)

    symbols = load_universe(store, as_of=d)
    if not symbols:
        console.print("Universe snapshot missing — fetching…")
        symbols = ingestor.snapshot_universe(d)

    console.print(f"Computing features for {len(symbols)} symbols as of {d}…")
    features, regime = compute_features(store, symbols, d, atr_period=cfg.swing.atr_period)
    ideas = screen(features, regime, cfg, d)

    sizes = {}
    for idea in ideas:
        ref_entry = sum(idea.entry_zone) / 2
        sizes[idea.symbol] = size_position(
            ref_entry, idea.stop, cfg.risk.capital, cfg.risk.risk_pct_per_trade
        )

    from .features.engine import LOOKBACK_CALENDAR_DAYS
    from .report.daily import render_report

    bars = {}
    if ideas:
        window = store.get_ohlcv(
            d - timedelta(days=LOOKBACK_CALENDAR_DAYS), d, as_of=d,
            symbols=[i.symbol for i in ideas],
        )
        bars = {s: g.sort_values("trade_date") for s, g in window.groupby("symbol")}

    out = cfg.data.data_dir / "reports" / f"{d}.html"
    render_report(d, ideas, sizes, regime, bars, out)
    console.print(f"[green]{len(ideas)} idea(s).[/green] Report: {out}")


@app.command()
def backtest(
    start: str = typer.Argument(..., help="YYYY-MM-DD"),
    end: str = typer.Argument(..., help="YYYY-MM-DD"),
):
    """Historical rules-only backtest with the Indian cost model."""
    from .backtest.engine import Backtester
    from .pipeline.ingest import load_universe

    cfg, store, _ = _make_ingestor()
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    universe = load_universe(store, as_of=end_d)
    if not universe:
        console.print("[red]No universe snapshot — run `swing backfill` first.[/red]")
        raise typer.Exit(1)

    result = Backtester(store, cfg).run(universe, start_d, end_d)
    console.print_json(json.dumps(result.metrics, default=str))

    out_dir = cfg.data.data_dir / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{start}_{end}"
    result.trades.to_csv(out_dir / f"trades_{tag}.csv", index=False)
    result.equity.to_csv(out_dir / f"equity_{tag}.csv", index=False)
    console.print(f"Trades + equity curves written to {out_dir}")


if __name__ == "__main__":
    app()
