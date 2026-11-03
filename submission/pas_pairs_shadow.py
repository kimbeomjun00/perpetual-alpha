"""PAS pair-reversion monitor.  It can never submit, sign, cancel, or modify an order.

This file is intentionally a shadow-only implementation of the final research model.
It fetches only public PAS hourly candles, calculates candidate signals, and can optionally
record a *virtual* position in a local JSON status file for observational testing.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "pas_pairs_config.json"
DEFAULT_STATE = HERE / "runtime" / "pas_pairs_shadow_state.json"
INFO_URL = "https://api.hyperliquid-testnet.xyz/info"


@dataclass
class PairSignal:
    pair: str
    timestamp_utc: str
    correlation: float
    beta: float
    gap: float
    btc_hourly_volatility: float
    btc_side: str
    other_side: str
    gross_notional_usd: float
    per_leg_notional_usd: float
    high_volatility_size_adjustment: bool


def read_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("mode") != "shadow_only" or cfg.get("execution", {}).get("live_order_submission") is not False:
        raise ValueError("Safety invariant: this runner must remain shadow_only with live_order_submission=false.")
    pairs = cfg.get("pairs", [])
    if {p.get("symbol") for p in pairs} != {"ETH", "EWY"}:
        raise ValueError("The research model requires exactly BTC-ETH and BTC-EWY.")
    if not math.isclose(sum(float(p["weight"]) for p in pairs), 1.0, abs_tol=1e-9):
        raise ValueError("Pair weights must sum to 1.0.")
    if not 0 < float(cfg["risk"]["gross_exposure_fraction"]) <= 1:
        raise ValueError("gross_exposure_fraction must be in (0, 1].")
    if cfg["execution"].get("equal_usd_legs") is not True:
        raise ValueError("Research model requires equal USD legs.")


def public_post(payload: dict[str, Any]) -> Any:
    """Public /info query only; no signing material or trading endpoint is present."""
    request = urllib.request.Request(
        INFO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_hourly_candles(symbol: str, hours: int = 240) -> pd.DataFrame:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - hours * 3_600_000
    rows = public_post({"type": "candleSnapshot", "req": {"coin": f"pas:{symbol}", "interval": "1h", "startTime": start_ms, "endTime": now_ms}})
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError(f"No PAS hourly candles returned for {symbol}.")
    out = pd.DataFrame({
        "time": pd.to_datetime(frame["t"], unit="ms", utc=True),
        "open": pd.to_numeric(frame["o"]),
        "close": pd.to_numeric(frame["c"]),
        "bar_end_ms": pd.to_numeric(frame["T"]),
    }).drop_duplicates("time").sort_values("time")
    # The still-forming candle is not a valid signal input.
    out = out[out["bar_end_ms"] <= now_ms].drop(columns="bar_end_ms").set_index("time")
    if len(out) < 100:
        raise RuntimeError(f"Only {len(out)} completed hourly candles returned for {symbol}; need at least 100.")
    return out


def aligned_hourly(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    joined = None
    for symbol, frame in frames.items():
        piece = frame[["open", "close"]].rename(columns={"open": f"{symbol}_open", "close": f"{symbol}_close"})
        joined = piece if joined is None else joined.join(piece, how="inner")
    assert joined is not None
    return joined.dropna().sort_index()


def calc_signal(data: pd.DataFrame, pair: dict[str, Any], cfg: dict[str, Any]) -> PairSignal | None:
    """Calculate the final-bar candidate exactly from the research definition."""
    other = pair["symbol"]
    base_close = data["BTC_close"]
    other_close = data[f"{other}_close"]
    returns_btc = np.log(base_close).diff()
    returns_other = np.log(other_close).diff()
    window = int(pair["corr_window_hours"])
    corr = returns_btc.rolling(window, min_periods=window).corr(returns_other)
    beta = returns_btc.rolling(window, min_periods=window).cov(returns_other) / returns_btc.rolling(window, min_periods=window).var()
    lag = int(pair["lag_hours"])
    gap = np.log(other_close / other_close.shift(lag)) - beta * np.log(base_close / base_close.shift(lag))
    btc_vol = returns_btc.rolling(int(cfg["signal"]["btc_vol_window_hours"]), min_periods=int(cfg["signal"]["btc_vol_window_hours"])).std()
    t = data.index[-1]
    c, b, g, vol = (float(corr.iloc[-1]), float(beta.iloc[-1]), float(gap.iloc[-1]), float(btc_vol.iloc[-1]))
    if not np.isfinite([c, b, g, vol]).all():
        return None
    if c < float(cfg["signal"]["correlation_min"]) or abs(g) < float(cfg["signal"]["gap_min"]):
        return None
    sign = 1 if g > 0 else -1
    btc_direction = sign * (1 if b > 0 else -1)
    other_direction = -sign
    high_vol = vol >= float(cfg["signal"]["high_vol_threshold"])
    multiplier = float(cfg["signal"]["high_vol_size_multiplier"]) if high_vol else 1.0
    gross = float(cfg["account_equity_usd"]) * float(cfg["risk"]["gross_exposure_fraction"]) * float(pair["weight"]) * multiplier
    return PairSignal(
        pair=f"BTC-{other}", timestamp_utc=t.isoformat(), correlation=c, beta=b, gap=g,
        btc_hourly_volatility=vol, btc_side="buy" if btc_direction > 0 else "sell",
        other_side="buy" if other_direction > 0 else "sell", gross_notional_usd=gross,
        per_leg_notional_usd=gross / 2, high_volatility_size_adjustment=high_vol,
    )


def exit_recovery(entry_gap: float, beta: float, btc_entry: float, other_entry: float, btc_now: float, other_now: float) -> float:
    """Positive values mean the relative move has reverted toward the entry gap."""
    move = math.log(other_now / other_entry) - beta * math.log(btc_now / btc_entry)
    return -math.copysign(1.0, entry_gap) * move / abs(entry_gap)


def evaluate_exits(position: dict[str, Any], btc_now: float, other_now: float, at: pd.Timestamp) -> str | None:
    recovery = exit_recovery(position["entry_gap"], position["beta"], position["btc_entry"], position["other_entry"], btc_now, other_now)
    if recovery >= position["take_recovery_fraction"]:
        return "recovery"
    if recovery <= -position["widen_fraction"]:
        return "widen"
    opened = pd.Timestamp(position["opened_at"])
    if at - opened >= pd.Timedelta(hours=position["max_hold_hours"]):
        return "time"
    return None


def current_circuit_breaker(state: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    equity = float(state.get("virtual_equity_usd", cfg["account_equity_usd"]))
    daily_start = float(state.get("daily_start_equity_usd", cfg["account_equity_usd"]))
    high_water = float(state.get("high_water_equity_usd", cfg["account_equity_usd"]))
    if equity <= daily_start * (1 - float(cfg["risk"]["daily_loss_fraction"])):
        return "daily_loss_limit"
    if equity <= high_water * (1 - float(cfg["risk"]["peak_drawdown_fraction"])):
        return "peak_drawdown_manual_review"
    return None


def observe_once(cfg: dict[str, Any]) -> dict[str, Any]:
    frames = {s: fetch_hourly_candles(s) for s in ("BTC", "ETH", "EWY")}
    data = aligned_hourly(frames)
    if len(data) < 100:
        raise RuntimeError(f"Only {len(data)} aligned candles across BTC/ETH/EWY.")
    signals = [calc_signal(data, pair, cfg) for pair in cfg["pairs"]]
    return {
        "mode": "shadow_only",
        "orders_submitted": 0,
        "as_of_utc": data.index[-1].isoformat(),
        "aligned_hourly_bars": len(data),
        "signals": [asdict(s) for s in signals if s is not None],
        "message": "Read-only observation completed. No wallet, signature, or order endpoint was used.",
    }


def record_virtual_observation(result: dict[str, Any], state_path: Path) -> None:
    """Optional local audit record; it intentionally cannot place a real or simulated exchange order."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {"observations": []}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("observations", []).append(result)
    state["observations"] = state["observations"][-500:]
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="PAS pair model: public-data shadow monitor only")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--once", action="store_true", help="Fetch public completed hourly candles and print candidate signals.")
    parser.add_argument("--record-observation", action="store_true", help="Write the read-only result to a local audit log.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    if not args.once:
        parser.error("Only --once is implemented. Persistent or live trading is deliberately unavailable.")
    cfg = read_config(args.config)
    result = observe_once(cfg)
    if args.record_observation:
        record_virtual_observation(result, args.state)
        result["local_audit_file"] = str(args.state)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
