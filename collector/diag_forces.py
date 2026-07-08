"""Diagnostic probe: does this broker feed expose a REAL tape (times&trades)?

Answers, per configured symbol, the question behind the buy/sell "force" read:
should the collector classify aggressor pressure from real trade ticks
(TICK_FLAG_BUY/SELL + volume_real) or synthesize it from quote-tick direction?
It samples the live feed for N seconds and prints, side by side, what the
current synthesized rule says vs what the real tape says (when one exists),
ending with a per-symbol verdict:

    REAL TAPE AVAILABLE      → the collector's auto-detect will use flags+volume
    QUOTE-ONLY (synthesize)  → no usable times&trades; quote-tick synthesis it is

Copy-paste the whole output when reporting what your broker exposes.

USAGE (Windows, next to the running + logged-in MT5 terminal):
    python diag_forces.py --config config.json --seconds 45

Read-only: it never sends orders, it only reads ticks.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Import the collector's init/config/classification machinery so the probe sees
# EXACTLY what the collector will see (same terminal priority list, same rules).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mt5_orderflow_collector as col  # noqa: E402
from mt5_orderflow_collector import (  # noqa: E402
    _TAPE_PROBE_MIN_PRINTS,
    _TICK_FLAG_BUY,
    _TICK_FLAG_LAST,
    _TICK_FLAG_SELL,
    _classify_quote_tick,
    _quote_tick_volume,
    _tick_side,
    _usable_trade_tick,
)


def _pct(part: float, whole: float) -> str:
    return f"{100.0 * part / whole:5.1f}%" if whole > 0 else "  n/a"


def _fetch(broker: str, from_dt: datetime, flags: int) -> list:
    """One copy_ticks_from call, robust: None/errors become an empty list."""
    try:
        ticks = col.mt5.copy_ticks_from(broker, from_dt, 100000, flags)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"  copy_ticks_from error: {exc}")
        return []
    return [] if ticks is None else list(ticks)


def _report_symbol(backend: str, broker: str, from_dt: datetime, seconds: float) -> None:
    print("=" * 72)
    print(f"SYMBOL {broker}  (backend: {backend})  — sample window: {seconds:.0f}s")
    print("=" * 72)

    trade_ticks = _fetch(broker, from_dt, col.mt5.COPY_TICKS_TRADE)
    all_ticks = _fetch(broker, from_dt, col.mt5.COPY_TICKS_ALL)

    # --- 1+2: the real tape (COPY_TICKS_TRADE) -------------------------------
    n_trade = len(trade_ticks)
    print(f"[1] COPY_TICKS_TRADE ticks:            {n_trade}")
    if n_trade:
        flag_buy = sum(1 for t in trade_ticks if int(t["flags"]) & _TICK_FLAG_BUY)
        flag_sell = sum(1 for t in trade_ticks if int(t["flags"]) & _TICK_FLAG_SELL)
        flag_last = sum(1 for t in trade_ticks if int(t["flags"]) & _TICK_FLAG_LAST)
        vol_real = sum(1 for t in trade_ticks if float(t["volume_real"]) > 0.0)
        vol_int = sum(1 for t in trade_ticks if float(t["volume"]) > 0.0)
        usable = sum(
            1
            for t in trade_ticks
            if _usable_trade_tick(
                int(t["flags"]), float(t["last"]), float(t["volume_real"]), float(t["volume"])
            )
        )
        print(f"[2] with TICK_FLAG_BUY:                {flag_buy:6d}  ({_pct(flag_buy, n_trade)})")
        print(f"    with TICK_FLAG_SELL:               {flag_sell:6d}  ({_pct(flag_sell, n_trade)})")
        print(f"    with TICK_FLAG_LAST:               {flag_last:6d}  ({_pct(flag_last, n_trade)})")
        print(f"    with volume_real > 0:              {vol_real:6d}  ({_pct(vol_real, n_trade)})")
        print(f"    with volume > 0:                   {vol_int:6d}  ({_pct(vol_int, n_trade)})")
        print(f"    usable prints (price+flags/size):  {usable:6d}  ({_pct(usable, n_trade)})")
    else:
        usable = 0
        print("[2] (no trade ticks — nothing to flag-count)")

    # --- 3: the quote stream (COPY_TICKS_ALL) --------------------------------
    n_all = len(all_ticks)
    print(f"[3] COPY_TICKS_ALL ticks:              {n_all}")
    if n_all:
        q_last = sum(1 for t in all_ticks if float(t["last"]) > 0.0)
        q_buy = sum(1 for t in all_ticks if int(t["flags"]) & _TICK_FLAG_BUY)
        q_sell = sum(1 for t in all_ticks if int(t["flags"]) & _TICK_FLAG_SELL)
        q_vr = sum(1 for t in all_ticks if float(t["volume_real"]) > 0.0)
        q_v = sum(1 for t in all_ticks if float(t["volume"]) > 0.0)
        print(f"    with nonzero last:                 {q_last:6d}  ({_pct(q_last, n_all)})")
        print(f"    with TICK_FLAG_BUY / SELL:         {q_buy:6d} / {q_sell:d}")
        print(f"    with volume_real > 0 / volume > 0: {q_vr:6d} / {q_v:d}")

    # --- 4: side-by-side buy% ------------------------------------------------
    # (a) CURRENT synthesized rule: mid-price direction, every print vol=1.
    prev_mid: float | None = None
    old_buy = old_sell = 0.0
    # (b) IMPROVED synthesized rule: flags → last vs bid/ask → mid tick test,
    #     volume-weighted when the tick carries volume.
    prev_mid2: float | None = None
    new_buy = new_sell = 0.0
    for t in all_ticks:
        bid, ask = float(t["bid"]), float(t["ask"])
        if bid <= 0.0 or ask <= 0.0:
            continue
        mid = (bid + ask) / 2.0
        if prev_mid is not None and mid != prev_mid:
            if mid > prev_mid:
                old_buy += 1.0
            else:
                old_sell += 1.0
        prev_mid = mid
        side = _classify_quote_tick(int(t["flags"]), float(t["last"]), bid, ask, prev_mid2, mid)
        vol = _quote_tick_volume(float(t["volume_real"]), float(t["volume"]))
        if side == "buy":
            new_buy += vol
        elif side == "sell":
            new_sell += vol
        prev_mid2 = mid
    # (c) REAL tape classification: broker flags (else last vs bid/ask), real volume.
    real_buy = real_sell = 0.0
    for t in trade_ticks:
        last = float(t["last"]) or float(t["bid"] or t["ask"] or 0.0)
        if last <= 0.0:
            continue
        vol = float(t["volume_real"]) if t["volume_real"] else float(t["volume"]) or 1.0
        side = _tick_side(int(t["flags"]), last, float(t["bid"]), float(t["ask"]))
        if side == "buy":
            real_buy += vol
        elif side == "sell":
            real_sell += vol

    print("[4] buy% side-by-side (share of directional volume):")
    print(
        f"    current synth rule (mid-dir, vol=1):  buy {_pct(old_buy, old_buy + old_sell)}"
        f"   (buy {old_buy:.0f} / sell {old_sell:.0f} prints)"
    )
    print(
        f"    improved synth rule (Lee-Ready):      buy {_pct(new_buy, new_buy + new_sell)}"
        f"   (buy vol {new_buy:.2f} / sell vol {new_sell:.2f})"
    )
    if real_buy + real_sell > 0:
        print(
            f"    REAL tape (flags + volume_real):      buy {_pct(real_buy, real_buy + real_sell)}"
            f"   (buy vol {real_buy:.2f} / sell vol {real_sell:.2f})"
        )
    else:
        print("    REAL tape:                            n/a (no directional trade ticks)")

    # --- verdict ---------------------------------------------------------------
    if usable >= _TAPE_PROBE_MIN_PRINTS:
        print(f"VERDICT {broker}: REAL TAPE AVAILABLE — collector auto-detect will use flags+volume")
    else:
        print(f"VERDICT {broker}: QUOTE-ONLY (synthesize) — no usable times&trades on this feed")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe MT5 feed: real tape vs quote-only")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--seconds", type=float, default=45.0, help="Sample window (seconds)")
    args = parser.parse_args()
    # Same UTF-8 guard as the collector: the Windows console defaults to cp1252.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover
            pass
    logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")

    cfg = col._load_config(args.config)
    source, account = col._init_mt5(cfg)
    for m in cfg["symbols"]:
        if not col.mt5.symbol_select(m["mt5"], True):
            print(f"WARNING: symbol_select({m['mt5']}) failed: {col.mt5.last_error()}")

    start = datetime.now(timezone.utc)
    print()
    print(f"diag_forces — source={source} account={account} window={args.seconds:.0f}s")
    print(f"sampling live feed... (aguarde ~{args.seconds:.0f}s)")
    time.sleep(max(args.seconds, 1.0))

    for m in cfg["symbols"]:
        _report_symbol(m["backend"], m["mt5"], start, args.seconds)

    col.mt5.shutdown()


if __name__ == "__main__":
    main()
