"""ONE deterministic entry/exit trade signal per symbol, from the live flow.

This is a CONSOLIDATION, not a new strategy. The decision logic already exists
in two places:

- `use_cases.scalper` — the bot's brain: explosion entries
  (`detect_explosion` / `decide_entry`) and the stop-and-reverse
  (`should_reverse`), on the recent tape window (WINDOW_SECONDS of market time).
- `use_cases.assess_trade_signals` — the in-trade exit alerts: pressure
  turned *against* the position and profit + momentum *stall* (take profit),
  on the 50-print window.

`compute_flow_signal` reuses those exact functions/constants (imported, never
re-declared) to produce a single `FlowSignal` per symbol. It is stamped onto
every `OrderFlowSnapshot` broadcast to the UI, and the armed scalper bot reads
the SAME object for its enter/reverse decisions (see
`api/routes/orderflow.py`), so the signal shown can never diverge from the
signal acted on.

Action mapping, faithful to what the bot already does:

- flat  + explosion                  → `enter_long` / `enter_short` (basis
  `explosion`) — exactly `decide_entry(..., open_on_symbol=0)`.
- held  + `should_reverse`           → `exit` (basis `reversal`) — the bot's
  stop-and-reverse. THIS is the only exit the bot executes on.
- held  + against / stall (assess)   → `exit` (basis `against` / `exhaustion`)
  — advisory, mirrors the existing per-position alerts; the bot does NOT act
  on these (it never did), keeping its behavior unchanged.
- held  + flow still leans held side → `enter_*` (basis `lean`) — the
  continuation read from `decide_entry`; the bot scales via its grid limits
  instead of market adds, so this too is advisory while holding.
- otherwise                          → `hold`.

Strength is a 0..1 UI conviction cue: the lean's distance from neutral,
normalized by 0.5 (the mathematical maximum of a volume fraction's offset from
50/50 — a bound, not a tuned constant). The bot ignores it.

CAVEAT (same as the sibling use cases): on quote-only CFD feeds the tape is
synthesized from tick direction and volume falls back to a count. The signal
is decision support, not advice.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.models import FlowSignal, OrderFlowSnapshot, Position
from use_cases.assess_trade_signals import AGAINST as ASSESS_AGAINST
from use_cases.assess_trade_signals import MIN_PRINTS as ASSESS_MIN_PRINTS
from use_cases.assess_trade_signals import STALL as ASSESS_STALL
from use_cases.assess_trade_signals import _buy_fraction as _assess_buy_fraction
from use_cases.scalper import (
    Direction,
)
from use_cases.scalper import _buy_fraction as _scalper_buy_fraction
from use_cases.scalper import (
    decide_entry,
    should_reverse,
)


def held_side(positions: Sequence[Position]) -> Direction | None:
    """Net side held on a symbol: 'buy'/'sell', or None when flat or tied.

    A tie (long+short hedge) should not happen with direction-consistent
    entries; it is treated as "no judgeable side" for safety. This is the same
    rule the bot route uses to pick the side it manages.
    """
    buys = sum(1 for p in positions if p.side == "buy")
    sells = sum(1 for p in positions if p.side == "sell")
    if buys > sells:
        return "buy"
    if sells > buys:
        return "sell"
    return None


def _strength(lean: float) -> float:
    """Map a lean (offset from the 0.5 neutral fraction) to a 0..1 cue.

    0.5 is the maximum possible offset of a volume fraction from 50/50, so this
    is a pure normalization — no tuning threshold involved.
    """
    return max(0.0, min(1.0, abs(lean) / 0.5))


def _enter_action(direction: Direction) -> str:
    return "enter_long" if direction == "buy" else "enter_short"


def compute_flow_signal(snapshot: OrderFlowSnapshot, positions: Sequence[Position]) -> FlowSignal:
    """The single per-symbol signal for this snapshot (see module docstring)."""
    symbol = snapshot.symbol
    side = held_side(positions)

    # Scalper window (WINDOW_SECONDS of tape): entries and the stop-and-reverse.
    buy30, _count30 = _scalper_buy_fraction(snapshot.recent_trades)

    if positions and side is None:
        # Held but tied (long+short) — the bot refuses to judge this; so do we.
        return FlowSignal(
            symbol=symbol,
            action="hold",
            basis="none",
            strength=0.0,
            reason="Posição ambígua (long+short no mesmo ativo) — sem leitura",
        )

    if side is not None:
        lean30 = (buy30 - 0.5) if side == "buy" else (0.5 - buy30)

        # 1) Stop-and-reverse — the exit the armed bot executes on.
        if should_reverse(snapshot, side):
            taker = "vendedores" if side == "buy" else "compradores"
            return FlowSignal(
                symbol=symbol,
                action="exit",
                basis="reversal",
                strength=_strength(lean30),
                reason=f"Fluxo virou forte contra a posição ({taker} no controle) — sair",
            )

        # 2) Softer in-trade exits, mirroring assess_trade_signals (50-print
        #    window). Advisory: the bot never acted on these and still doesn't.
        buy50, count50 = _assess_buy_fraction(snapshot.recent_trades)
        lean50 = (buy50 - 0.5) if side == "buy" else (0.5 - buy50)
        if count50 >= ASSESS_MIN_PRINTS:
            if lean50 <= -ASSESS_AGAINST:
                taker = "vendedores" if side == "buy" else "compradores"
                return FlowSignal(
                    symbol=symbol,
                    action="exit",
                    basis="against",
                    strength=_strength(lean50),
                    reason=f"Pressão contrária: {taker} assumindo — considere reduzir/sair",
                )
            symbol_profit = sum(p.profit for p in positions)
            if symbol_profit > 0 and lean50 <= ASSESS_STALL:
                # How far the favourable push has faded across the stall→against
                # band: 0 at lean == STALL, 1 at lean == −AGAINST. Reuses only
                # the existing STALL/AGAINST constants (no new thresholds).
                faded = (ASSESS_STALL - lean50) / (ASSESS_STALL + ASSESS_AGAINST)
                return FlowSignal(
                    symbol=symbol,
                    action="exit",
                    basis="exhaustion",
                    strength=max(0.0, min(1.0, faded)),
                    reason="Em lucro e o momentum esfriou — considere realizar",
                )

        # 3) Continuation: the flow still leans the held side (>= ADD_LEAN).
        #    Advisory while holding — the bot scales via its grid limits.
        add = decide_entry(snapshot, current_side=side, open_on_symbol=len(positions))
        if add is not None:
            lado = "comprado" if add == "buy" else "vendido"
            return FlowSignal(
                symbol=symbol,
                action=_enter_action(add),  # type: ignore[arg-type]
                basis="lean",
                strength=_strength(lean30),
                reason=f"Fluxo ainda sustenta o lado {lado} — manter a posição",
            )
        return FlowSignal(
            symbol=symbol,
            action="hold",
            basis="none",
            strength=0.0,
            reason="Fluxo sem definição — manter o plano da posição",
        )

    # Flat: entry requires a full explosion — exactly the bot's initial entry.
    direction = decide_entry(snapshot, current_side=None, open_on_symbol=0)
    if direction is not None:
        frac = buy30 if direction == "buy" else (1.0 - buy30)
        lado = "compradora" if direction == "buy" else "vendedora"
        return FlowSignal(
            symbol=symbol,
            action=_enter_action(direction),  # type: ignore[arg-type]
            basis="explosion",
            strength=_strength(frac - 0.5),
            reason=f"Explosão {lado}: fluxo forte + range em expansão",
        )
    return FlowSignal(
        symbol=symbol,
        action="hold",
        basis="none",
        strength=0.0,
        reason="Sem explosão: fluxo neutro ou sem expansão — aguardar",
    )


# --- bot-side mapping (part of the single source of truth) --------------------


def signal_entry_direction(signal: FlowSignal | None) -> Direction | None:
    """The direction the bot should OPEN from this signal, or None.

    Only `enter_long`/`enter_short` map to an open. When flat these can only
    have come from a full explosion (see `compute_flow_signal`), so this is
    exactly the bot's previous `detect_explosion` gate.
    """
    if signal is None:
        return None
    if signal.action == "enter_long":
        return "buy"
    if signal.action == "enter_short":
        return "sell"
    return None


def signal_says_reverse(signal: FlowSignal | None) -> bool:
    """True when the signal is the bot-grade stop-and-reverse exit.

    Deliberately keyed on basis == 'reversal' (== `should_reverse`): the softer
    `against`/`exhaustion` exits are advisory alerts the bot never traded on,
    and consolidating the signal must not change the bot's behavior.
    """
    return signal is not None and signal.action == "exit" and signal.basis == "reversal"


__all__ = [
    "compute_flow_signal",
    "held_side",
    "signal_entry_direction",
    "signal_says_reverse",
]
