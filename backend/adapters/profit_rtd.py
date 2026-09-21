"""Turns a live RTD row from Profit's Times & Trades into a tape `Trade`.

The `.trd` file and the RTD window carry the same prints, but not the same
fields, so the live feed has to be rebuilt into the record the accumulator
already knows. Three differences matter:

- **Broker name instead of code.** The file carries the numeric code, which is
  the stable identity; the window shows the short name. Eleven short names in
  `newagents.dat` belong to more than one code, and two of those straddle
  groups: `BTG` is 85 (the brokerage, sardinha) and 1026 (the bank, banco),
  `Santander` is 622/635 (bank) and 4090 (brokerage). Measured on the WIN
  session of 18/09/2026, only one of each pair actually trades — BTG 85 did
  3.505.111 contracts against zero for 1026, Santander 4090 did 726.866
  against zero for 622 and 635 — so the name resolves to the code that trades.

- **Fewer trade types.** The file marks RLP (13), auction (4) and cross (1);
  the aggressor column carries only `Comprador`, `Vendedor` and `RLP`. So the
  retail line survives, but an auction print and a broker crossing its own
  orders are not marked and simply do not resolve — they are dropped and
  counted rather than guessed at.

- **No financial.** The file carries the value in reais with B3's multiplier
  already applied; here it is rebuilt from price × quantity × multiplier.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from adapters.profit_tape import (
    TYPE_BUY_AGGRESSION,
    TYPE_RLP,
    TYPE_SELL_AGGRESSION,
    Trade,
)

logger = logging.getLogger(__name__)

# BRL per point, per contract, as B3 defines it — the same multipliers the
# `.trd` has baked into its financial field.
MULTIPLIERS: dict[str, float] = {"WIN": 0.20, "WDO": 10.0}

# Short names that map to several codes where the codes fall in different
# groups. Resolved by which one actually trades — see the module docstring.
_AMBIGUOUS: dict[str, int] = {"BTG": 85, "Santander": 4090}


def name_to_code(agents: dict[int, str]) -> dict[str, int]:
    """Broker short name -> code, the reverse of `load_agents`.

    Names are matched case-folded because the window and the table do not
    always agree on capitalisation.
    """
    table: dict[str, int] = {}
    for code, name in agents.items():
        key = name.strip().casefold()
        if not key:
            continue
        table.setdefault(key, code)
    for name, code in _AMBIGUOUS.items():
        table[name.casefold()] = code
    return table


def parse_time(stamp: str, day: date) -> datetime | None:
    """`HH:MM:SS.mmm` from the window plus the session day.

    The window only carries the clock, so the day has to come from outside.
    """
    try:
        clock = datetime.strptime(stamp.strip(), "%H:%M:%S.%f").time()
    except ValueError:
        try:
            clock = datetime.strptime(stamp.strip(), "%H:%M:%S").time()
        except ValueError:
            return None
    return datetime.combine(day, clock)


def aggressor_kind(aggressor: str) -> int | None:
    """Trade type from the window's aggressor column.

    Measured against a replay of the WIN session of 18/09/2026 (8.503 prints):
    the column only ever holds `Comprador`, `Vendedor` or `RLP`. RLP being in
    there is what lets the live feed carry the retail line — it is B3's own
    marking, not a reading of a broker name.

    Only the first letter is keyed on, because the column is narrow and Profit
    shortens the text when it has to. Anything unrecognised returns None so the
    caller can report it instead of silently picking a side.
    """
    text = aggressor.strip().casefold()
    if text.startswith("r"):
        return TYPE_RLP
    if text.startswith("c"):
        return TYPE_BUY_AGGRESSION
    if text.startswith("v"):
        return TYPE_SELL_AGGRESSION
    return None


def parse_trade(
    raw: dict[str, object],
    day: date,
    multiplier: float,
    codes: dict[str, int],
) -> Trade | None:
    """One wire row to a `Trade`, or None when it cannot be trusted.

    A row is dropped when the clock, the aggressor or either broker name does
    not resolve. Dropping is the honest outcome: a print counted on the wrong
    side is worse for the partition than a print not counted at all, and the
    caller counts the drops.
    """
    at = parse_time(str(raw.get("at", "")), day)
    if at is None:
        return None
    kind = aggressor_kind(str(raw.get("aggressor", "")))
    if kind is None:
        return None
    buyer = codes.get(str(raw.get("buyer", "")).strip().casefold())
    seller = codes.get(str(raw.get("seller", "")).strip().casefold())
    if buyer is None or seller is None:
        return None
    try:
        price = float(str(raw["price"]))
        qty = int(str(raw["qty"]))
    except (KeyError, TypeError, ValueError):
        return None
    if price <= 0 or qty <= 0:
        return None
    return Trade(
        at=at,
        seq=0,  # the window has no sequence number; nothing downstream reads it
        price=price,
        qty=qty,
        financial=price * qty * multiplier,
        buyer=buyer,
        seller=seller,
        kind=kind,
    )


def multiplier_for(symbol: str) -> float | None:
    """B3 multiplier for a contract as Profit names it (`WINV26`, `WDOV26`)."""
    for prefix, value in MULTIPLIERS.items():
        if symbol.upper().startswith(prefix):
            return value
    return None
