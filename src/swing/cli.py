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
def run(day: str = typer.Option(None, "--date")):
    """Nightly research run (Phase 1)."""
    console.print("[yellow]Not built yet — arrives in Phase 1 (rules + backtest).[/yellow]")
    raise typer.Exit(2)


@app.command()
def backtest():
    """Historical backtest with Indian cost model (Phase 1)."""
    console.print("[yellow]Not built yet — arrives in Phase 1 (rules + backtest).[/yellow]")
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
