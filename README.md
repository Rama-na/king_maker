# Swing Trading Research Assistant

AI-assisted, research-and-decision-support system for swing trading Indian (NSE) equities.
Runs locally on a Mac mini as a nightly after-close batch job.

**Research tool only.** A human makes every trade decision. No order execution, no
investment advice, no guarantee of returns. See `SPEC.md` for the full design.

## What it does (when complete)

Every trading day after market close it will:
1. Ingest official NSE end-of-day data (bhavcopy, indices, corporate actions) — free, no broker API.
2. Compute indicators, levels, and risk parameters deterministically in code.
3. Score each F&O-universe stock for a defined swing setup: P(hit +2R target before 2×ATR stop within 10 days).
4. Run a tiered LLM analysis panel on the shortlist only (numbers from code, judgment from the model).
5. Emit a ranked HTML report of trade ideas: entry zone, stop, target, position size, thesis + counter-thesis.

## Status

| Phase | Contents | State |
|---|---|---|
| 0 | Scaffold, NSE adapters, corporate-action adjustment, point-in-time store, backfill | **built** (live NSE verification pending — see below) |
| 1 | Feature engine, triple-barrier labels, rules screener, Indian-cost backtester, daily report | not started |
| 2 | LightGBM scorer + purged walk-forward CV | not started |
| 3 | LLM reasoning panel (Anthropic API, tiered) | not started |
| 4 | Outcome memory, web dashboard, launchd automation | not started |

## Setup (Mac mini)

```bash
# install uv if needed: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev
cp .env.example .env          # fill in later phases' keys

uv run pytest                 # all green before touching data

uv run swing backfill --years 6    # ~1.5k trading days; resumable, throttled (~1 req/s)
uv run swing status
uv run swing validate 2020-07-01 2026-06-30
```

> **Note:** the NSE adapters were built against recorded payload formats in a
> sandboxed environment without NSE network access. The first `swing backfill`
> run on a real network is the live verification step — endpoint URLs
> occasionally change, and any mismatch will surface immediately there.

## Data & design guarantees

- **Point-in-time correctness:** every stored row carries a `knowledge_date`; reads
  take an explicit `as_of` and refuse windows beyond it (`LookaheadError`). Tested in
  `tests/test_store_pit.py`.
- **Raw prices stored forever, adjustment at read time:** split/bonus factors are applied
  only for actions with `ex_date <= as_of`, so a backtest on date T sees exactly what a
  trader saw on date T.
- **All data local:** `data/` (gitignored) holds Parquet partitions, the HTTP cache,
  and reports. Back up by copying the folder.

## Layout

```
config/config.yaml      strategy + cost parameters (single source of truth)
src/swing/adapters/     NSE HTTP client, bhavcopy/index/F&O/corporate-action parsers
src/swing/pipeline/     point-in-time store, adjustment engine, ingest, validation
src/swing/cli.py        `swing` command
tests/                  incl. point-in-time leakage gate
```
