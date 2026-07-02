# Swing Trading Research Assistant — Project Specification

> **Build target:** an AI-assisted, research-and-decision-support system for swing trading Indian equities (NSE).
> **Intended executor:** Claude Code running Claude Fable 5.
> **Status:** greenfield. Nothing is built yet. This document is the source of truth for scope, architecture, and build order.

---

## 0. How to use this document (read first)

You are Claude Fable 5, operating in Claude Code. This is a long-horizon build. Work in the phase order defined in **§16 Build Plan**. Each phase has explicit **acceptance criteria** — do not advance until the current phase's criteria pass. After each phase, write and run the verification steps listed, and summarize what passed/failed before continuing.

Before writing code:
1. Ask the human any blocking clarifying questions from **§18 Open Decisions** that would change architecture.
2. Confirm the tech stack in **§4** against what is actually installed; propose swaps if something is unavailable.
3. Build **Phase 1 (rules-only, backtested) end to end before adding any ML or agents.** This ordering is non-negotiable — see **§2**.

Treat the deterministic components as the ground truth and the LLM components as an interpretation layer on top. If you ever find yourself letting an LLM compute a number that code could compute exactly, stop and move it to code.

---

## 1. Purpose

Build a tool that, once per trading session (after 15:30 IST market close), screens a universe of liquid NSE stocks, scores each candidate for a defined swing setup, runs a structured multi-perspective analysis on the shortlist, and produces a ranked, human-reviewable list of trade ideas — each with entry zone, stop, target, position size, conviction score, and a written thesis plus its strongest counter-argument.

It is **decision support**. A human makes every trade decision. The system does not place orders.

---

## 2. Core philosophy (non-negotiable principles)

1. **Numbers from code, judgment from the model.** All prices, indicators, levels, risk parameters, and probabilities are computed deterministically and are reproducible. LLMs never compute arithmetic that code can compute. LLMs interpret, contextualize, and argue — they do not calculate.
2. **Not a price predictor.** The system estimates the *probability of a defined outcome* (hitting a target before a stop within a time window). It never claims to predict a future price.
3. **Backtest before belief.** No signal, model, or agent output is trusted until it survives a leak-free, cost-aware backtest and a period of paper trading. The backtest harness is the most important component, not the LLM layer.
4. **Deterministic anchor.** The ML score and computed features are the anchor. The reasoning/agent layer interprets them; it never overrides them.
5. **Additive complexity.** Rules first, then ML as a refinement, then agents as the final layer. Each layer must demonstrably improve the paper-traded baseline or it gets removed.
6. **Research use only.** No auto-execution in scope. See **§17 Compliance**.

---

## 3. Scope and non-goals

**In scope**
- Daily batch research over a liquid NSE universe.
- Deterministic technical + fundamental + ownership feature engineering.
- Triple-barrier labeling and an ML setup scorer.
- A structured multi-agent reasoning panel over the shortlist.
- A leak-free, cost-aware backtest harness.
- Ranked decision-support output for human review.
- Local-first deployment, with a path to scheduled cloud execution.

**Non-goals (explicitly out of scope)**
- Automated order placement / live execution.
- Intraday / high-frequency trading.
- Options or F&O strategies (equity swing only for v1).
- Portfolio-level optimization beyond simple per-trade position sizing.
- Any claim, output, or UI copy that implies guaranteed returns.

---

## 4. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Data / compute | pandas, numpy, `pandas-ta` (or TA-Lib) | indicators |
| ML | LightGBM / XGBoost, scikit-learn | gradient-boosted trees + CV |
| Backtest | custom event-driven harness (or `vectorbt` for speed) | must model Indian frictions |
| LLM routing | LiteLLM | tiered model access |
| LLM (deep) | Claude Fable 5 via Anthropic API (or Microsoft Foundry) | bear challenge + judge |
| LLM (cheap) | Claude Haiku (or small local model) | specialists, first-pass |
| DB | PostgreSQL + `pgvector` | results + memory store |
| Object store | local FS (dev) → Azure Blob (prod) | cached filings, charts |
| Secrets | `.env` + direnv (dev) → Key Vault / Keychain | never commit keys |
| Scheduler | `launchd` (macOS dev) → Azure Container Apps Job (prod) | batch, scale-to-zero |
| Orchestration | plain Python + a task runner; consider Prefect if it grows | |

Confirm broker-API and data-vendor pricing/availability at build time — these change.

---

## 5. Repository structure (target)

```
swing-research/
├─ README.md
├─ SPEC.md                      # this document
├─ pyproject.toml / requirements.txt
├─ .env.example
├─ config/
│  └─ config.yaml               # universe, target %, stop %, horizon, thresholds
├─ src/
│  ├─ adapters/                 # pluggable data providers
│  │  ├─ base.py                # MarketDataProvider, FilingsProvider interfaces
│  │  ├─ broker_api.py          # Kite/Upstox/Angel/Dhan impl
│  │  └─ fundamentals.py        # screener.in / NSE-BSE filings impl
│  ├─ pipeline/                 # ingest → clean → point-in-time store
│  ├─ features/                 # deterministic signal engine
│  │  ├─ technical.py
│  │  ├─ ownership.py           # shareholding-pattern features
│  │  ├─ fundamentals.py
│  │  └─ relative_strength.py
│  ├─ labeling/                 # triple-barrier
│  ├─ model/                    # scorer + purged walk-forward CV
│  ├─ reasoning/                # multi-agent panel
│  │  ├─ specialists.py
│  │  ├─ debate.py              # bull vs bear
│  │  └─ judge.py
│  ├─ decision/                 # ranked output assembly
│  ├─ memory/                   # pgvector read/write
│  ├─ backtest/                 # event-driven harness + cost model
│  └─ run_daily.py              # entrypoint for the batch job
├─ tests/
├─ notebooks/                   # research + backtest analysis
└─ deploy/
   ├─ launchd/                  # macOS plist
   └─ azure/                    # Container Apps Job config
```

---

## 6. System architecture

Pipeline stages, in order:

1. **Data adapters** — pluggable providers behind interfaces. Retail feeds now, premium later, no downstream rewrite.
2. **Data pipeline + cache** — ingest, clean, enforce **point-in-time correctness**, cache immutable artifacts (filings, transcripts).
3. **Deterministic signal engine** — compute all indicators, levels, and feature families in code.
4. **Labeling** — triple-barrier labels for training.
5. **ML scorer** — gradient-boosted trees output P(target before stop). Gates the universe down to a shortlist.
6. **Tiered reasoning panel** — specialists (cheap model) → bull/bear debate → judge (Fable). Anchored to the ML score.
7. **Decision support** — ranked ideas with levels, sizing, thesis + counter-thesis, conviction.
8. **Memory** — store every idea and its realized outcome; feed relevant history back into reasoning.

Two hard rules that cut cost and error:
- The ML scorer runs on the **whole universe cheaply**; Fable only touches the **shortlist**.
- Inside the panel, cheap model does specialists + first drafts; Fable does only the **bear challenge** and **judge synthesis**.

---

## 7. Market context (India / NSE)

- **Session:** 09:15–15:30 IST. Batch runs after close.
- **Universe:** liquid names only — F&O universe or top-N by average traded value. This filter removes both illiquidity and circuit-freeze risk.
- **Circuit limits:** stocks can lock at upper/lower circuits; you cannot exit a lower-circuit stock. Exclude circuit-prone illiquid names from the universe entirely.
- **Frictions to model in backtests:** STT (raised April 2026), brokerage, exchange fees, slippage, and short-term capital gains tax on realized gains.
- **Data vendors:** broker APIs (Zerodha Kite Connect is the de-facto standard; Upstox, Angel One SmartAPI, Dhan, Fyers as alternatives) for OHLCV/history; screener.in or NSE/BSE filings for fundamentals and shareholding.

---

## 8. Data layer

### 8.1 Adapter interfaces
Define thin interfaces so vendor choice is swappable:

```python
class MarketDataProvider(Protocol):
    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    def get_universe(self) -> list[str]: ...

class FilingsProvider(Protocol):
    def get_fundamentals(self, symbol: str, as_of: date) -> dict: ...
    def get_shareholding_history(self, symbol: str) -> pd.DataFrame: ...
```

### 8.2 Point-in-time correctness (critical)
Every datum must be associated with the date it *became public*, not the date it describes. A quarterly filing dated 31-Mar is only usable from its actual publication date (~within 21 days of quarter-end). Any feature that uses future-relative information invalidates the entire backtest. Enforce this in the pipeline and test for it.

### 8.3 Caching
Filings, transcripts, and rendered charts are immutable once published. Cache them keyed by `(symbol, doc_id)`. Cache LLM analyses keyed by `(symbol, filing_hash, prompt_version)` so re-runs never re-pay for identical work. Use Anthropic prompt caching for the static portion of long prompts.

---

## 9. Labeling — triple-barrier method

For each candidate on each date, place three barriers and label by which is hit first:

- **Upper barrier:** profit target, `+X%` (from `config.target_pct`).
- **Lower barrier:** stop, `−Y%` (from `config.stop_pct`, ideally ATR-derived).
- **Vertical barrier:** time limit, `N` trading days (`config.horizon_days`).

Label = `1` if upper hit first, `0` if lower or vertical hit first (or use 3-class if useful). The target percentage is therefore both the **selection criterion** and the **ML training label** — they are the same object.

Reference: López de Prado, *Advances in Financial Machine Learning* (Wiley, 2018) — labeling and cross-validation methods.

---

## 10. Feature engineering (deterministic signal engine)

All computed in code, per symbol, point-in-time correct. Four families:

**Technical**
- Trend: SMA/EMA (20/50/200), MACD, ADX.
- Momentum: RSI, stochastics, rate-of-change.
- Volatility: ATR (also drives stop distance + sizing), Bollinger Bands.
- Volume: relative/average volume, OBV, unusual-volume flags.
- Levels: swing highs/lows, pivots, prior gaps, support/resistance.
- Setup flags (boolean): e.g. breakout above N-day high on ≥2× volume, pullback to rising 50-day MA.

**Ownership / flows** (from quarterly shareholding pattern — slow context feature, not a trigger)
- Holding levels: promoter, FII/FPI, DII, public/retail.
- Quarter-over-quarter change in each (often more informative than level).
- Promoter pledging level and trend (**strong risk flag**).
- Retail-concentration score (sentiment sensitivity proxy).

**Fundamentals**
- Standard quality/valuation/growth metrics as available point-in-time.

**Relative strength**
- Performance vs Nifty and vs sector index.
- Market regime flag (e.g. index above/below its 200-day MA) — gates or down-weights everything in weak regimes.

Output per symbol: a single structured feature record consumed by both the scorer and the reasoning layer.

---

## 11. ML scorer + validation

- **Model:** LightGBM/XGBoost classifier predicting P(upper barrier first).
- **Target:** triple-barrier label from **§9**.
- **Output:** calibrated probability per candidate; used to rank and to gate the shortlist.
- **Validation — mandatory:** purged, embargoed, walk-forward cross-validation. Never naive k-fold (it leaks future into past). Embargo a gap between train and test to prevent label overlap leakage.
- **Guard against:** overfitting, multiple-testing (trying many features until one looks good), and regime decay. Track live vs backtest performance and retrain on a schedule.
- **Acceptance:** the scorer must improve the rules-only paper-traded baseline out-of-sample, after costs, or it is not included.

---

## 12. Reasoning layer — multi-agent panel

Runs only on the ML-selected shortlist. Structured panel, not open-ended chat.

**Roles**
- **Specialist analysts (cheap model):** Technical, Ownership & Flows, Fundamentals & News — each argues from one lens over the same evidence pack.
- **Bull composer (cheap model draft):** strongest case for the trade.
- **Bear challenger (Fable):** independent adversarial attempt to break the thesis. Uses Fable's independent-verifier strength to avoid self-critique bias.
- **PM judge (Fable):** weighs the debate against the anchor, produces the verdict and conviction.

**Hard rules**
- The **evidence pack (features + ML score) is the anchor**. The judge is instructed to weight the number over the narrative. Agents interpret; they never override the statistics.
- Keep the panel small. Every agent is model calls; a large panel per candidate is expensive and adds confident noise.
- Tiering: specialists + first drafts on the cheap model; Fable only for bear challenge + judge.

**Cost note:** multi-agent debate can manufacture confident-but-wrong consensus. The anchor + the backtest are the defense. Treat the panel as the final 10%, not the foundation.

---

## 13. Decision support output

Per idea, emit a structured record (also render human-readable):

```json
{
  "symbol": "TICKER",
  "as_of": "YYYY-MM-DD",
  "ml_probability": 0.0,
  "conviction": 0.0,
  "entry_zone": [low, high],
  "stop": 0.0,
  "target": 0.0,
  "position_size": { "shares": 0, "risk_pct_of_capital": 0.0 },
  "ownership_context": "retail-heavy | FII-heavy | DII-heavy | promoter note",
  "thesis": "bull case (paraphrased, concise)",
  "counter_thesis": "bear case",
  "flags": ["promoter_pledge", "earnings_within_horizon", "..."]
}
```

Position size is code-computed from ATR and a fixed risk-per-trade rule. The output is ranked by a blend of ML probability and conviction (define and tune the blend; document it).

---

## 14. Memory

- PostgreSQL + pgvector. Store every idea and, later, its realized outcome (which barrier hit, actual return).
- Feed relevant past cases into the reasoning context ("similar setups previously resolved thus").
- Reuse the episodic-memory pattern: embed the setup + context, retrieve nearest neighbors at reasoning time.

---

## 15. Backtest harness (the most important component)

- Event-driven, walk-forward, point-in-time correct.
- **Model Indian frictions explicitly:** STT (post-April-2026 rates), brokerage, exchange charges, realistic slippage, and circuit constraints (cannot exit at lower circuit).
- Report: net (after-cost) returns, hit rate vs triple-barrier labels, drawdown, exposure, turnover, and per-regime breakdown.
- Compare every added layer (ML, then agents) against the rules-only baseline. Keep a layer only if it improves after-cost, out-of-sample results.
- Follow with paper trading before any real capital.

---

## 16. Build plan (phased — respect the gates)

**Phase 1 — Rules-only, backtested (foundation)**
- Adapters, pipeline with point-in-time store, deterministic signal engine, triple-barrier labeling, rules-based setup selection, and the full backtest harness with Indian costs.
- *Done when:* a rules-only strategy runs end to end on historical data, produces ranked ideas, and the backtest reports after-cost metrics with no look-ahead leakage (add a leakage test that fails if any feature uses future data).

**Phase 2 — ML scorer**
- Train the gradient-boosted scorer on triple-barrier labels; wire purged walk-forward CV; gate the shortlist by probability.
- *Done when:* the scorer is validated with purged walk-forward CV and demonstrably improves the Phase-1 baseline out-of-sample after costs. If it does not, document why and keep Phase 1 as the baseline.

**Phase 3 — Reasoning panel**
- Specialists → bull/bear debate → judge, with LiteLLM tiering (cheap for specialists, Fable for bear + judge), anchored to the ML score. Emit the decision-support schema.
- *Done when:* the panel runs on the shortlist within a defined per-run token budget, the judge provably weights the anchor, and outputs validate against the schema.

**Phase 4 — Memory + deployment**
- pgvector memory with outcome write-back; local `launchd` schedule; then Azure Container Apps Job.
- *Done when:* the daily job runs unattended on schedule, writes results + outcomes to Postgres, and stays within the cost budget.

**Throughout:** tests for point-in-time correctness, cost accounting, and schema validation. Paper-trade before real capital at every stage.

---

## 17. Compliance (India / SEBI)

- This is a **research/decision-support** tool with **no auto-execution** — it sits outside SEBI's retail algo framework, which governs automated *order placement*.
- If execution is ever added: individual traders using transparent "white box" logic for personal use, under 10 orders/second, are treated as regular API users and do not need separate SEBI/exchange registration; the broker handles strategy-ID tagging. API access requires a **static whitelisted IP** (register the VPS's static IP if run from cloud). Personal use extends to immediate family only.
- Never emit guaranteed-return claims anywhere (UI, logs, output). Prohibited.

---

## 18. Open decisions (ask the human before/early)

1. Default `target_pct`, `stop_pct`, and `horizon_days` for the swing definition.
2. Universe definition: F&O list vs top-N by traded value, and N.
3. Broker/data vendor choice (drives the adapter implementation).
4. Risk-per-trade rule and max concurrent positions.
5. Personal-only tool vs future multi-user (changes DB tier + whether an API layer is needed).
6. Cheap-model choice for specialists: hosted Haiku vs a local model (local doesn't fit cloud serverless).

---

## 19. Deployment & cost (summary)

- **Dev:** everything local on the MacBook — Postgres in Docker, `.env` secrets, `launchd` schedule. Near-zero infra cost.
- **Prod:** Azure Container Apps Job (scheduled, scale-to-zero), Postgres Flexible Server (B1ms) + pgvector, Blob Storage, Key Vault, Fable via Anthropic API or Foundry.
- **Cost drivers:** LLM usage dominates; infra is ~$15–65/month at personal scale. Control LLM cost via shortlist gating, model tiering, caching, and prompt caching.

---

## 20. Guardrails — what NOT to do

- Do not let an LLM compute indicators, prices, or probabilities.
- Do not use naive k-fold CV. Purged, embargoed, walk-forward only.
- Do not add ML or agents before Phase 1 is backtested and passing.
- Do not let the reasoning panel override the deterministic anchor.
- Do not include any feature that could use future information (test for it).
- Do not implement auto-execution in v1.
- Do not present output as advice or as guaranteed; it is research for human review.

---

## 21. Glossary

- **Triple-barrier labeling:** label a sample by whether price hits a profit target, a stop, or a time limit first.
- **Purged/embargoed walk-forward CV:** time-series cross-validation that removes overlapping-label leakage and enforces a train/test gap.
- **Point-in-time correctness:** using only information that was public as of the decision date.
- **Shareholding pattern:** SEBI-mandated quarterly disclosure splitting ownership into promoter, FII, DII, and public/retail.
- **Anchor:** the deterministic features + ML score that the reasoning layer may interpret but not override.

---

*This system improves research quality and process discipline. It does not guarantee returns, and the base rate for retail trading in India is unfavorable. Build the backtest first; trust it before you trust anything else.*
