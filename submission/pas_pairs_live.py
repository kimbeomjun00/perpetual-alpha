"""PAS pair-reversion execution runner for the competition TESTNET only.

This is intentionally separate from the shadow monitor.  It requires both
--live-testnet and --arm before a signed order path can run.  It has no
mainnet URL, no withdrawal code, and no credentials in source control.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from dotenv import load_dotenv  # noqa: E402
from eth_account import Account  # noqa: E402
from hyperliquid.exchange import Exchange  # noqa: E402
from hyperliquid.info import Info  # noqa: E402

from pas_pairs_shadow import aligned_hourly, calc_signal, fetch_hourly_candles, read_config, exit_recovery


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def append_log(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item) + "\n")


def now_text() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def round_size(notional: float, price: float, decimals: int) -> float:
    step = Decimal(10) ** -decimals
    value = (Decimal(str(notional)) / Decimal(str(price))).quantize(step, rounding=ROUND_DOWN)
    return float(value)


def load_client(config: dict[str, Any]) -> tuple[Exchange, Info, str, str]:
    load_dotenv(ROOT / ".env")
    wallet = os.environ["TEAM_WALLET_ADDRESS"].lower()
    private_key = os.environ["API_WALLET_PRIVATE_KEY"]
    agent = os.environ["API_WALLET_ADDRESS"].lower()
    exchange_cfg = config["exchange"]
    info = Info(exchange_cfg["base_url"], skip_ws=True, perp_dexs=[exchange_cfg["dex"]])
    exchange = Exchange(Account.from_key(private_key), exchange_cfg["base_url"], account_address=wallet, perp_dexs=[exchange_cfg["dex"]])
    return exchange, info, wallet, agent


def live_positions(info: Info, wallet: str, dex: str) -> dict[str, dict[str, Any]]:
    return {p["coin"]: p for row in info.user_state(wallet, dex).get("assetPositions", []) if float((p := row["position"]).get("szi", 0))}


def control(control_file: Path) -> str:
    if not control_file.exists():
        return "RUN"
    return control_file.read_text(encoding="utf-8").strip().upper() or "RUN"


def mids(info: Info, dex: str) -> dict[str, float]:
    return {coin: float(px) for coin, px in info.all_mids(dex).items()}


def close_coin(exchange: Exchange, info: Info, wallet: str, dex: str, coin: str, slippage: float) -> dict[str, Any] | None:
    if coin not in live_positions(info, wallet, dex):
        return None
    return exchange.market_close(coin, slippage=slippage)


def signed_size(position: dict[str, dict[str, Any]], coin: str) -> float:
    return float(position.get(coin, {}).get("szi", 0.0))


def wait_for_delta(info: Info, wallet: str, dex: str, before: dict[str, dict[str, Any]], expected: dict[str, float], seconds: int) -> tuple[bool, dict[str, dict[str, Any]], dict[str, float]]:
    """Wait briefly for IOC fills; compare only the newly requested inventory change."""
    deadline = time.monotonic() + seconds
    latest: dict[str, dict[str, Any]] = {}
    deltas: dict[str, float] = {}
    while True:
        latest = live_positions(info, wallet, dex)
        deltas = {coin: signed_size(latest, coin) - signed_size(before, coin) for coin in expected}
        ok = all(abs(deltas[coin] - target) <= max(abs(target) * 0.05, 1e-9) for coin, target in expected.items())
        if ok or time.monotonic() >= deadline:
            return ok, latest, deltas
        time.sleep(1)


def submit_delta(exchange: Exchange, coin: str, delta_size: float, slippage: float) -> dict[str, Any] | None:
    if abs(delta_size) < 1e-12:
        return None
    return exchange.market_open(coin, delta_size > 0, abs(delta_size), slippage=slippage)


def flatten_known_positions(exchange: Exchange, info: Info, wallet: str, dex: str, slippage: float, state: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    known = set()
    for p in state.get("open_pairs", {}).values():
        known.update((p["btc_coin"], p["other_coin"]))
    for coin in live_positions(info, wallet, dex):
        if coin not in known:
            raise RuntimeError(f"Refusing to touch unknown position {coin}.")
        result = close_coin(exchange, info, wallet, dex, coin, slippage)
        if result is not None:
            results.append({"coin": coin, "result": result})
    state["open_pairs"] = {}
    return results


def update_daily_guard(state: dict[str, Any], strategy: dict[str, Any], mark_pnl: float = 0.0) -> str | None:
    reset_hour = int(strategy["risk"]["daily_reset_hour_utc"])
    now = pd.Timestamp.now(tz="UTC")
    key = (now - pd.Timedelta(hours=reset_hour)).date().isoformat()
    if state.get("risk_day") != key:
        state["risk_day"] = key
        state["daily_realized_pnl_usd"] = 0.0
    equity = float(strategy["account_equity_usd"]) + float(state.get("daily_realized_pnl_usd", 0.0)) + mark_pnl
    state["high_water_equity_usd"] = max(float(state.get("high_water_equity_usd", strategy["account_equity_usd"])), equity)
    if equity <= float(strategy["account_equity_usd"]) * (1 - float(strategy["risk"]["daily_loss_fraction"])):
        return "DAILY_LOSS_LIMIT"
    if equity <= float(state["high_water_equity_usd"]) * (1 - float(strategy["risk"]["peak_drawdown_fraction"])):
        return "PEAK_DRAWDOWN_REVIEW"
    return None


def pair_mark_pnl(pair: dict[str, Any], market_mids: dict[str, float]) -> float:
    btc_sign = 1 if pair["btc_side"] == "buy" else -1
    other_sign = 1 if pair["other_side"] == "buy" else -1
    return pair["btc_leg_usd"] * btc_sign * (market_mids[pair["btc_coin"]] / pair["btc_entry"] - 1) + pair["other_leg_usd"] * other_sign * (market_mids[pair["other_coin"]] / pair["other_entry"] - 1)


def manage_open_pairs(exchange: Exchange, info: Info, wallet: str, live_cfg: dict[str, Any], strategy: dict[str, Any], state: dict[str, Any], data: pd.DataFrame) -> list[dict[str, Any]]:
    dex, slip = live_cfg["exchange"]["dex"], float(live_cfg["exchange"]["max_slippage"])
    actual = live_positions(info, wallet, dex)
    events = []
    for name, pair in list(state.get("open_pairs", {}).items()):
        if pair["other_coin"] not in actual:
            raise RuntimeError(f"Pair {name} has a missing non-BTC leg; manual review required before continuing.")
        other = pair["symbol"]
        reason = None
        recovery = exit_recovery(pair["entry_gap"], pair["beta"], pair["btc_entry"], pair["other_entry"], float(data["BTC_close"].iloc[-1]), float(data[f"{other}_close"].iloc[-1]))
        if recovery >= pair["take_recovery_fraction"]:
            reason = "recovery"
        elif recovery <= -pair["widen_fraction"]:
            reason = "widen"
        elif pd.Timestamp(data.index[-1]) - pd.Timestamp(pair["opened_at"]) >= pd.Timedelta(hours=pair["max_hold_hours"]):
            reason = "time"
        if reason:
            before = live_positions(info, wallet, dex)
            expected = {pair["btc_coin"]: -float(pair["btc_qty_signed"]), pair["other_coin"]: -float(pair["other_qty_signed"])}
            exit_mids = mids(info, dex)
            realized_estimate = pair_mark_pnl(pair, exit_mids)
            results = [submit_delta(exchange, coin, delta, slip) for coin, delta in expected.items()]
            ok, _, deltas = wait_for_delta(info, wallet, dex, before, expected, int(strategy["risk"]["fill_timeout_seconds"]))
            if not ok:
                flatten_known_positions(exchange, info, wallet, dex, slip, state)
                raise RuntimeError(f"Exit fill mismatch for {name}; flattened tracked inventory. Deltas: {deltas}")
            del state["open_pairs"][name]
            state["daily_realized_pnl_usd"] = float(state.get("daily_realized_pnl_usd", 0.0)) + realized_estimate
            events.append({"event": "exit_submitted", "pair": name, "reason": reason, "recovery": recovery, "estimated_realized_pnl_usd": realized_estimate, "results": results})
    return events


def enter_pair(exchange: Exchange, info: Info, wallet: str, live_cfg: dict[str, Any], signal: dict[str, Any], pair_cfg: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    dex, slip = live_cfg["exchange"]["dex"], float(live_cfg["exchange"]["max_slippage"])
    if info.open_orders(wallet, dex):
        return {"event": "entry_skipped", "pair": signal["pair"], "reason": "open_order_exists"}
    if signal["pair"] in state.get("open_pairs", {}):
        return {"event": "entry_skipped", "pair": signal["pair"], "reason": "pair_already_open"}
    tracked_coins = {coin for item in state.get("open_pairs", {}).values() for coin in (item["btc_coin"], item["other_coin"])}
    unknown_positions = set(live_positions(info, wallet, dex)) - tracked_coins
    if unknown_positions:
        return {"event": "entry_skipped", "pair": signal["pair"], "reason": f"unknown_existing_position:{sorted(unknown_positions)}"}
    market_mids = mids(info, dex)
    btc_coin, other_coin = "pas:BTC", f"pas:{pair_cfg['symbol']}"
    btc_size = round_size(float(signal["per_leg_notional_usd"]), market_mids[btc_coin], info.asset_to_sz_decimals[info.coin_to_asset[btc_coin]])
    other_size = round_size(float(signal["per_leg_notional_usd"]), market_mids[other_coin], info.asset_to_sz_decimals[info.coin_to_asset[other_coin]])
    if btc_size <= 0 or other_size <= 0:
        return {"event": "entry_skipped", "pair": signal["pair"], "reason": "size_rounds_to_zero"}
    btc_signed = btc_size if signal["btc_side"] == "buy" else -btc_size
    other_signed = other_size if signal["other_side"] == "buy" else -other_size
    candidate = {
        "symbol": pair_cfg["symbol"], "btc_coin": btc_coin, "other_coin": other_coin,
        "btc_side": signal["btc_side"], "other_side": signal["other_side"],
        "btc_entry": market_mids[btc_coin], "other_entry": market_mids[other_coin],
        "btc_leg_usd": abs(btc_signed) * market_mids[btc_coin], "other_leg_usd": abs(other_signed) * market_mids[other_coin],
        "btc_qty_signed": btc_signed, "other_qty_signed": other_signed,
        "entry_gap": signal["gap"], "beta": signal["beta"], "opened_at": signal["timestamp_utc"],
        "take_recovery_fraction": pair_cfg["take_recovery_fraction"], "widen_fraction": pair_cfg["widen_fraction"], "max_hold_hours": pair_cfg["max_hold_hours"]
    }
    # The BTC market is netted by the venue.  Therefore each pair records its signed
    # BTC quantity and opens/closes only its own delta; simultaneous pairs are supported.
    before = live_positions(info, wallet, dex)
    state.setdefault("open_pairs", {})[signal["pair"]] = candidate
    btc_result = submit_delta(exchange, btc_coin, btc_signed, slip)
    other_result = submit_delta(exchange, other_coin, other_signed, slip)
    expected = {btc_coin: btc_signed, other_coin: other_signed}
    ok, _, deltas = wait_for_delta(info, wallet, dex, before, expected, int(read_config(ROOT / live_cfg["strategy_config"])["risk"]["fill_timeout_seconds"]))
    if not ok:
        flatten_known_positions(exchange, info, wallet, dex, slip, state)
        return {"event": "entry_flattened", "pair": signal["pair"], "reason": "ioc_fill_delta_mismatch", "deltas": deltas, "btc_result": btc_result, "other_result": other_result}
    return {"event": "entry_submitted", "pair": signal["pair"], "btc_result": btc_result, "other_result": other_result, "deltas": deltas}


def iteration(live_cfg: dict[str, Any], strategy: dict[str, Any], state: dict[str, Any], *, permit_orders: bool) -> dict[str, Any]:
    exchange, info, wallet, _ = load_client(live_cfg)
    dex = live_cfg["exchange"]["dex"]
    control_word = control(ROOT / live_cfg["control_file"])
    frames = {symbol: fetch_hourly_candles(symbol) for symbol in ("BTC", "ETH", "EWY")}
    data = aligned_hourly(frames)
    candle = data.index[-1].isoformat()
    event: dict[str, Any] = {"at_utc": now_text(), "control": control_word, "candle_utc": candle, "orders_submitted": 0, "events": []}
    tracked_coins = {coin for item in state.get("open_pairs", {}).values() for coin in (item["btc_coin"], item["other_coin"])}
    unknown_positions = set(live_positions(info, wallet, dex)) - tracked_coins
    if unknown_positions:
        raise RuntimeError(f"Unknown PAS position(s) found: {sorted(unknown_positions)}. Refusing to trade.")
    if control_word == "FLATTEN":
        if permit_orders:
            event["events"] = flatten_known_positions(exchange, info, wallet, dex, float(live_cfg["exchange"]["max_slippage"]), state)
            event["orders_submitted"] = len(event["events"])
        event["status"] = "flatten_requested"
        return event
    event["events"] += manage_open_pairs(exchange, info, wallet, live_cfg, strategy, state, data) if permit_orders else []
    if candle == state.get("last_candle_utc"):
        event["status"] = "same_completed_candle"
        return event
    state["last_candle_utc"] = candle
    market_mids = mids(info, dex)
    mark_pnl = sum(pair_mark_pnl(p, market_mids) for p in state.get("open_pairs", {}).values())
    guard = update_daily_guard(state, strategy, mark_pnl)
    candidates = [] if control_word == "PAUSE" or guard else [calc_signal(data, pair, strategy) for pair in strategy["pairs"]]
    for pair_cfg, candidate in zip(strategy["pairs"], candidates):
        if candidate is None:
            continue
        candidate_data = candidate.__dict__
        event["events"].append({"event": "signal", **candidate_data})
        if permit_orders:
            result = enter_pair(exchange, info, wallet, live_cfg, candidate_data, pair_cfg, state)
            event["events"].append(result)
            if result["event"] in {"entry_submitted", "entry_flattened"}:
                event["orders_submitted"] += 2
    event["status"] = "paused" if control_word == "PAUSE" else (guard.lower() if guard else "evaluated_new_candle")
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="PAS competition TESTNET execution runner")
    parser.add_argument("--config", type=Path, default=ROOT / "pas_pairs_live_config.json")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--live-testnet", action="store_true", help="Permit TESTNET order path.")
    parser.add_argument("--arm", action="store_true", help="Second explicit gate for signed TESTNET orders.")
    args = parser.parse_args()
    if args.once == args.loop:
        parser.error("Choose exactly one of --once or --loop.")
    live_cfg = json.loads(args.config.read_text(encoding="utf-8"))
    strategy = read_config(ROOT / live_cfg["strategy_config"])
    state_path, log_path = ROOT / live_cfg["state_file"], ROOT / live_cfg["log_file"]
    state = load_json(state_path, {"open_pairs": {}, "high_water_equity_usd": strategy["account_equity_usd"]})
    permit_orders = args.live_testnet and args.arm
    if not permit_orders:
        print("DRY RUN: signed orders are disabled. Add both --live-testnet and --arm to permit PAS TESTNET orders.")
    while True:
        try:
            event = iteration(live_cfg, strategy, state, permit_orders=permit_orders)
            append_log(log_path, event)
            write_json(state_path, state)
            print(json.dumps(event), flush=True)
            if args.once or event.get("control") == "FLATTEN":
                return
        except Exception as exc:
            event = {"at_utc": now_text(), "event": "error", "error_type": type(exc).__name__, "error": str(exc)}
            append_log(log_path, event)
            write_json(state_path, state)
            print(json.dumps(event), flush=True)
            if args.once:
                raise
        time.sleep(int(live_cfg["poll_seconds"]))


if __name__ == "__main__":
    main()
