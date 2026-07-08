"""Deterministic in-trade signals for open scalps.

Pure, side-effect-free logic (no I/O, no LLM): for each open position it reads
the *current* order-flow lean and emits at most one alert. Recomputed on every
order-flow broadcast (~10×/s), so it reacts inside the seconds-long life of a
scalp — an LLM round-trip never could.

Two rules, both driven by the short-window pressure lean (buy vs sell volume in
the last `RECENT_WINDOW` tape prints), expressed *relative to the position*:

- **pressure_against** — the flow has clearly turned against your side (sellers
  taking over a long, or buyers a short). Fires regardless of P&L; the louder
  the lean, the higher the severity.
- **take_profit** — you are in profit AND the favourable push has faded to
  roughly neutral (momentum dying). A nudge to bank it before it gives back.

The two are mutually exclusive per position: a clear "against" pre-empts the
softer "take profit". Below a minimum sample of directional prints we stay
silent rather than fire on noise.

CAVEAT: the lean is a share of directional VOLUME. When the collector has a
real tape (broker trade ticks) that volume is real contracts; on quote-only CFD
feeds it synthesizes the tape and each print's volume falls back to 1 (a tick
count) unless the tick carries a size. Either way the fraction normalizes, but
on the count-proxy feeds these remain a directional proxy — decision support,
not a guarantee.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.models import OrderFlowSnapshot, Position, TapeTrade, TradeSignal

# Last N tape prints that define "right now" pressure. The synthesized tape runs
# fast, so this is a short, responsive window suited to a seconds-long scalp.
RECENT_WINDOW = 50
# Need at least this many directional prints in the window before judging — below
# it the lean is statistical noise and we stay silent.
MIN_PRINTS = 8
# Favourable-lean thresholds (buy/sell volume fraction offset from 0.5, so the
# range is [-0.5, +0.5]; positive = flow supports the position):
#   lean <= -AGAINST       → pressure turning against (warn)
#   lean <= -AGAINST_STRONG → strongly against (urgent)
#   0 < profit and lean <= STALL → in profit but momentum stalled (take profit)
AGAINST = 0.15
AGAINST_STRONG = 0.30
STALL = 0.05


def _buy_fraction(trades: Sequence[TapeTrade]) -> tuple[float, int]:
    """Buy share of directional volume in the window, and the directional count.

    Returns (0.5, 0) when there is no directional volume, so callers can gate on
    the count without tripping a divide-by-zero.
    """
    window = trades[-RECENT_WINDOW:]
    buy = sell = 0.0
    count = 0
    for t in window:
        if t.side == "buy":
            buy += t.volume
            count += 1
        elif t.side == "sell":
            sell += t.volume
            count += 1
    total = buy + sell
    if total <= 0:
        return 0.5, count
    return buy / total, count


def assess_trade_signals(
    snapshot: OrderFlowSnapshot, positions: Sequence[Position]
) -> list[TradeSignal]:
    """Emit at most one signal per open position from the current flow lean."""
    if not positions:
        return []
    buy_pct, count = _buy_fraction(snapshot.recent_trades)
    if count < MIN_PRINTS:
        return []  # not enough flow to judge — stay silent

    out: list[TradeSignal] = []
    for p in positions:
        # Favourable lean: how much the flow supports THIS position's side.
        lean = (buy_pct - 0.5) if p.side == "buy" else (0.5 - buy_pct)

        if lean <= -AGAINST:
            taker = "Vendedores" if p.side == "buy" else "Compradores"
            out.append(
                TradeSignal(
                    symbol=p.symbol,
                    ticket=p.ticket,
                    code="pressure_against",
                    severity="urgent" if lean <= -AGAINST_STRONG else "warn",
                    stance="against",
                    message=f"Fluxo virou contra: {taker.lower()} assumindo o controle",
                )
            )
        elif p.profit > 0 and lean <= STALL:
            out.append(
                TradeSignal(
                    symbol=p.symbol,
                    ticket=p.ticket,
                    code="take_profit",
                    severity="warn",
                    stance="caution",
                    message="Em lucro e o momentum esfriou — considere realizar",
                )
            )
    return out


__all__ = ["assess_trade_signals"]
