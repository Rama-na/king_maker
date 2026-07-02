"""Self-contained daily HTML report: ranked ideas + candlestick per idea.

Rendered with plotly.js from CDN (the Mac mini is online; the HTML file itself
carries all data inline). Colors follow the validated reference palette:
status green/red for up/down candles (polarity), categorical blue for the
entry zone, with direct labels on every level line so no meaning is
color-alone.
"""

from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd

from ..decision.sizing import PositionSize
from ..screener.rules import Idea

# reference palette (light surface) — see dataviz reference instance
C = {
    "surface": "#fcfcfb",
    "page": "#f9f9f7",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "up": "#0ca30c",       # status good
    "down": "#d03b3b",     # status critical
    "entry": "#2a78d6",    # categorical slot 1
}

DISCLAIMER = (
    "Research output for human review only. Not investment advice. "
    "No outcome is guaranteed; historical behaviour does not predict returns."
)


def _chart_js(div_id: str, bars: pd.DataFrame, idea: Idea) -> str:
    data = {
        "x": [str(d) for d in bars["trade_date"]],
        "open": bars["open"].round(2).tolist(),
        "high": bars["high"].round(2).tolist(),
        "low": bars["low"].round(2).tolist(),
        "close": bars["close"].round(2).tolist(),
    }
    lines = [
        {"y": idea.target, "label": f"target {idea.target}", "color": C["up"], "dash": "dash"},
        {"y": idea.stop, "label": f"stop {idea.stop}", "color": C["down"], "dash": "dash"},
    ]
    shapes = [
        {
            "type": "rect", "xref": "paper", "x0": 0, "x1": 1,
            "y0": idea.entry_zone[0], "y1": idea.entry_zone[1],
            "fillcolor": C["entry"], "opacity": 0.12, "line": {"width": 0},
        }
    ] + [
        {
            "type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": ln["y"], "y1": ln["y"],
            "line": {"color": ln["color"], "width": 2, "dash": ln["dash"]},
        }
        for ln in lines
    ]
    annotations = [
        {
            "xref": "paper", "x": 1.0, "xanchor": "left", "y": ln["y"],
            "text": ln["label"], "showarrow": False,
            "font": {"color": ln["color"], "size": 12},
        }
        for ln in lines
    ] + [
        {
            "xref": "paper", "x": 1.0, "xanchor": "left", "y": idea.entry_zone[1],
            "text": "entry zone", "showarrow": False,
            "font": {"color": C["entry"], "size": 12},
        }
    ]
    layout = {
        "margin": {"l": 48, "r": 110, "t": 8, "b": 32},
        "height": 340,
        "paper_bgcolor": C["surface"],
        "plot_bgcolor": C["surface"],
        "font": {"color": C["ink2"], "family": "system-ui, -apple-system, 'Segoe UI', sans-serif"},
        "xaxis": {"rangeslider": {"visible": False}, "gridcolor": C["grid"], "type": "category",
                   "tickfont": {"size": 10, "color": C["muted"]}, "nticks": 8},
        "yaxis": {"gridcolor": C["grid"], "tickfont": {"size": 11, "color": C["muted"]}},
        "shapes": shapes,
        "annotations": annotations,
        "showlegend": False,
    }
    trace = {
        **data,
        "type": "candlestick",
        "increasing": {"line": {"color": C["up"], "width": 1}},
        "decreasing": {"line": {"color": C["down"], "width": 1}},
    }
    return (
        f"Plotly.newPlot({json.dumps(div_id)}, [{json.dumps(trace)}], "
        f"{json.dumps(layout)}, {{displayModeBar: false, responsive: true}});"
    )


def render_report(
    as_of: date,
    ideas: list[Idea],
    sizes: dict[str, PositionSize],
    regime: dict,
    bars_by_symbol: dict[str, pd.DataFrame],
    out_path: Path,
) -> Path:
    rows, charts = [], []
    for i, idea in enumerate(ideas):
        size = sizes.get(idea.symbol)
        div_id = f"chart{i}"
        rows.append(f"""
        <tr>
          <td class="sym"><a href="#{div_id}">{escape(idea.symbol)}</a></td>
          <td>{escape(idea.setup)}</td>
          <td class="num">{idea.close:,.2f}</td>
          <td class="num">{idea.entry_zone[0]:,.2f}–{idea.entry_zone[1]:,.2f}</td>
          <td class="num">{idea.stop:,.2f}</td>
          <td class="num">{idea.target:,.2f}</td>
          <td class="num">{size.shares if size else "–"}</td>
          <td class="num">{f"{size.risk_pct_of_capital:.2f}%" if size else "–"}</td>
          <td class="num">{idea.rs_rank:.2f}</td>
          <td>{escape(", ".join(idea.flags)) or "–"}</td>
        </tr>""")
        bars = bars_by_symbol.get(idea.symbol)
        if bars is not None and not bars.empty:
            charts.append(
                f'<section id="{div_id}"><h3>{escape(idea.symbol)} '
                f'<span class="setup">{escape(idea.setup)}</span></h3>'
                f'<div class="plot" id="{div_id}_plot"></div>'
                f"<script>{_chart_js(div_id + '_plot', bars.tail(90), idea)}</script></section>"
            )

    regime_txt = "bull (Nifty above 200-DMA)" if regime.get("regime_bull") else "weak (Nifty below 200-DMA)"
    body_when_empty = (
        f"<p class='empty'>No qualifying setups today. Market regime: {regime_txt}.</p>"
        if not ideas
        else ""
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swing research — {as_of}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0;
         background: {C["page"]}; color: {C["ink"]}; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 64px; }}
  h1 {{ font-size: 22px; margin-bottom: 2px; }}
  h3 {{ margin: 28px 0 6px; }} .setup {{ color: {C["ink2"]}; font-weight: normal; font-size: 14px; }}
  .meta {{ color: {C["ink2"]}; margin-bottom: 20px; }}
  table {{ border-collapse: collapse; width: 100%; background: {C["surface"]};
           border: 1px solid rgba(11,11,11,0.10); border-radius: 6px; }}
  th, td {{ padding: 7px 10px; text-align: left; font-size: 13.5px;
            border-bottom: 1px solid {C["grid"]}; }}
  th {{ color: {C["muted"]}; font-weight: 600; }}
  td.num {{ font-variant-numeric: tabular-nums; text-align: right; }}
  td.sym a {{ color: {C["entry"]}; text-decoration: none; font-weight: 600; }}
  .plot {{ background: {C["surface"]}; border: 1px solid rgba(11,11,11,0.10); border-radius: 6px; }}
  .empty {{ color: {C["ink2"]}; padding: 24px; background: {C["surface"]};
            border: 1px solid rgba(11,11,11,0.10); border-radius: 6px; }}
  footer {{ margin-top: 40px; color: {C["muted"]}; font-size: 12px; }}
</style></head><body><main>
<h1>Swing research — {as_of}</h1>
<p class="meta">Market regime: {regime_txt} · {len(ideas)} idea(s) · rules-only baseline (Phase 1)</p>
{body_when_empty}
{f'''<table>
<thead><tr><th>Symbol</th><th>Setup</th><th>Close</th><th>Entry zone</th><th>Stop</th>
<th>Target</th><th>Shares</th><th>Risk</th><th>RS rank</th><th>Flags</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>''' if ideas else ""}
{"".join(charts)}
<footer>{DISCLAIMER}</footer>
</main></body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path
