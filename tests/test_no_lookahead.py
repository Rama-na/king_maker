"""THE leakage gate for the feature engine (spec §16 Phase 1 acceptance).

Every indicator must be causal: the value at bar T computed from history
truncated at T must equal the value at bar T computed from the full series.
If any feature ever peeks forward — a negative shift, a centered window, a
full-series normalization — this test fails.
"""

from datetime import date

import numpy as np
import pandas as pd

from swing.features.technical import compute_indicators

from .synth import make_ohlcv, weekdays


def test_features_identical_under_truncation():
    days = weekdays(date(2024, 1, 1), 300)
    df = make_ohlcv("TESTSYM", days, seed=42, noise=0.01)
    full = compute_indicators(df)

    numeric_cols = [c for c in full.columns if pd.api.types.is_numeric_dtype(full[c])]
    bool_cols = [c for c in full.columns if pd.api.types.is_bool_dtype(full[c])]

    for k in (220, 261, 299):
        trunc = compute_indicators(df.iloc[: k + 1])
        full_row, trunc_row = full.iloc[k], trunc.iloc[-1]
        for col in numeric_cols:
            a, b = full_row[col], trunc_row[col]
            both_nan = pd.isna(a) and pd.isna(b)
            assert both_nan or np.isclose(a, b, rtol=1e-9, equal_nan=True), (
                f"lookahead in column {col!r} at bar {k}: full={a} truncated={b}"
            )
        for col in bool_cols:
            assert full_row[col] == trunc_row[col], f"lookahead in flag {col!r} at bar {k}"


def test_canary_future_data_changes_nothing_before_it():
    """Corrupting the future must not move any past feature value."""
    days = weekdays(date(2024, 1, 1), 300)
    df = make_ohlcv("TESTSYM", days, seed=42)
    base = compute_indicators(df)

    poisoned = df.copy()
    poisoned.loc[poisoned.index[-30:], ["open", "high", "low", "close"]] *= 5.0
    poisoned_feats = compute_indicators(poisoned)

    checkpoint = 260  # before the corruption starts at bar 270
    for col in base.columns:
        a, b = base.iloc[checkpoint][col], poisoned_feats.iloc[checkpoint][col]
        if isinstance(a, float) and pd.isna(a) and pd.isna(b):
            continue
        assert a == b or np.isclose(a, b, rtol=1e-9), f"future leaked into {col!r}"
