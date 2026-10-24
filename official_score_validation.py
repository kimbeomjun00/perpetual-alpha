"""Offline score-aware validation for the fixed pair strategy.

This file never connects to Hyperliquid and never submits orders.  It recreates
the hourly mark-to-market return stream already validated in
pair_overlap_analysis.py, then samples equity at 12:00 UTC and applies the
competition's published PnL/volatility/Q formula.
"""
from __future__ import annotations

import contextlib
import io
import json
import runpy
from pathlib import Path

import numpy as np
import pandas as pd

INITIAL_EQUITY = 100_000.0
LAMBDA = 1.5
EPSILON = 0.005
CONSTANT = 0.05


with contextlib.redirect_stdout(io.StringIO()):
    research = runpy.run_path(str(Path(__file__).with_name("pair_overlap_analysis.py")))

INDEX = research["idx"]
CUTS = research["cuts"]
PAIR_RETURNS_PP = research["allret"]  # hourly percentage-point return at 50% gross


def official_metrics(start: int, end: int, ewy_weight: float, gross: float) -> dict:
    """Return competition-style metrics for one chronological segment."""
    hourly_pp = (
        ewy_weight * PAIR_RETURNS_PP["EWY"][start:end]
        + (1.0 - ewy_weight) * PAIR_RETURNS_PP["ETH"][start:end]
    ) * (gross / 0.50)
    equity = pd.Series(INITIAL_EQUITY + np.cumsum(hourly_pp) * 1000.0, index=INDEX[start:end])
    snapshots = equity[equity.index.hour == 12]
    daily = snapshots.pct_change().dropna()
    n = len(daily)
    if n < 2:
        return {"days": int(n), "R_pct": None, "sigma_pct": None, "Q": None, "score_pre_jury": None}

    r_total = float(np.prod(1.0 + daily.to_numpy()) - 1.0)
    sigma = float(daily.std(ddof=1) * np.sqrt(n))
    q = (max(r_total, 0.0) + EPSILON) / (abs(r_total) + LAMBDA * sigma + CONSTANT)
    return {
        "days": int(n),
        "R_pct": round(r_total * 100.0, 5),
        "sigma_pct": round(sigma * 100.0, 5),
        "Q": round(q, 7),
        "score_pre_jury": round(0.8 * q, 7),
        "max_drawdown_pct": round(float((1.0 - equity / equity.cummax()).max()) * 100.0, 5),
    }


def run() -> None:
    candidates = []
    for ewy_weight in (0.75, 0.80, 0.85):
        for gross in (0.35, 0.50, 0.65):
            parts = [official_metrics(CUTS[i], CUTS[i + 1], ewy_weight, gross) for i in range(3)]
            candidates.append({"ewy_weight": ewy_weight, "gross": gross, "parts": parts})

    # Select only from the first (training) segment.  Validation and test stay untouched.
    eligible = [x for x in candidates if x["parts"][0]["Q"] is not None]
    selected = max(eligible, key=lambda x: x["parts"][0]["Q"])
    current = next(x for x in candidates if x["ewy_weight"] == 0.80 and x["gross"] == 0.50)
    print(json.dumps({
        "method": "12:00 UTC daily snapshots; official Q; no jury score; historical proxy only",
        "current": current,
        "train_selected": selected,
        "comparison": candidates,
        "interpretation": "Only change live settings if the train-selected configuration also improves both untouched validation and test score."
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
