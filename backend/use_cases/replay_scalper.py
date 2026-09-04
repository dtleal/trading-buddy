"""Replay a recorded ingest tape through the explosion scalper (backtest).

Feeds the JSONL files written by `adapters/tape_recorder.py` through the SAME
code the live bot runs — `OrderFlowAggregator` for snapshots, `orderflow_wire`
for parsing, `compute_flow_signal` for decisions, and the policy constants from
`use_cases/scalper.py` — mirroring the decision ORDER of
`api/routes/orderflow.py::_run_bot` step by step. What is simulated (because a
recording has no broker) is execution only:

- Market opens fill at the current top-of-book ask (buy) / bid (sell).
- Grid limit orders fill at their limit price when the tape prints at/through it.
- Closes fill at the current bid (long) / ask (short); "instant" — the live
  close-lag settling states collapse to immediate banking.
- P&L = price move × `usd_per_point` × lots. The USD-based thresholds (profit
  target, loss stop, profit lock) are only as faithful as `usd_per_point`, so
  check it against the broker's contract spec before trusting absolute numbers.

The clock is the tape's own `rx` timestamp (backend receive time) — cooldowns
and re-arm delays elapse in recorded market time, never wall time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from core.enums import AssetSymbol
from core.models import Position, SessionLiquidity

# Policy constants are read via the MODULE (scalper.LOCK_MIN_USD, …), never
# imported by value: a `tuned()` sweep overrides the module globals, and an
# import-time copy would silently ignore the override.
from use_cases import scalper
from use_cases.aggregate_orderflow import OrderFlowAggregator
from use_cases.orderflow_wire import (
    parse_book,
    parse_dt,
    parse_liquidity,
    parse_symbol,
    parse_trade,
)
from use_cases.scalper import (
    Direction,
    grid_breach_price,
    grid_levels,
    region_broken,
    should_open,
    symbol_stopped,
)
from use_cases.trade_signal import (
    compute_flow_signal,
    held_side,
    signal_entry_direction,
    signal_says_reverse,
)

# USD gained per 1.0 price-unit move per 1.0 lot. MUST match the broker's
# contract spec for absolute P&L (and thus the USD thresholds) to be right.
# ActivTrades defaults (the Sep26 forward index CFDs, contract size read from
# MT5): USTEC 20, USA500 50, US30 5, GER40 25 (pays in EUR, close enough to 1
# USD for sizing). Gold is quoted per ounce and 1 lot = 100 oz, so 100 USD per
# 1.00 move; EURUSD 1 lot = 100,000 euros, so 100,000 USD per 1.00 move (10 USD
# per pip). These are 5x-50x the old FTMO .cash values (1 USD per index point),
# so lots had to shrink by the same factor — see DEFAULT_LOTS. Re-check the
# contract spec when the forward contract rolls to the next quarter.
DEFAULT_USD_PER_POINT: dict[AssetSymbol, float] = {
    AssetSymbol.USTEC: 20.0,
    AssetSymbol.SPX: 50.0,
    AssetSymbol.GOLD: 100.0,
    AssetSymbol.US30: 5.0,
    AssetSymbol.GER40: 25.0,
    AssetSymbol.EURUSD: 100_000.0,
}

# Live per-symbol sizes (mirrors _DEFAULT_LOTS in the bot route).
DEFAULT_LOTS: dict[AssetSymbol, float] = {
    AssetSymbol.USTEC: 0.1,
    AssetSymbol.SPX: 0.04,
    AssetSymbol.GOLD: 0.12,
    AssetSymbol.US30: 0.2,
    AssetSymbol.GER40: 0.04,
    AssetSymbol.EURUSD: 0.5,
}


@dataclass
class ReplayParams:
    """Bot knobs for one replay run — defaults are the live bot's defaults."""

    profit_target: float = 350.0
    loss_stop: float = 900.0
    cooldown_s: float = 2.0
    max_per_symbol: int = 6
    rearm: bool = True
    symbol_stop_usd: float = 0.0  # per-symbol hard USD stop (0 = off, live default)
    lots: dict[AssetSymbol, float] = field(default_factory=lambda: dict(DEFAULT_LOTS))
    usd_per_point: dict[AssetSymbol, float] = field(
        default_factory=lambda: dict(DEFAULT_USD_PER_POINT)
    )


@dataclass
class SimPosition:
    side: Direction
    lots: float
    entry: float
    opened_at: float  # replay-clock epoch seconds
    ticket: int


@dataclass
class CloseEvent:
    """One banked close (symbol lock/reverse, or account target/stop)."""

    at: str  # rx ISO timestamp
    scope: str  # symbol value, or "ACCOUNT"
    reason: str  # lock | reverse | target | stop
    pnl: float


@dataclass
class ReplayReport:
    total_pnl: float = 0.0
    entries: int = 0  # market opens + grid limit fills
    closes: list[CloseEvent] = field(default_factory=list)
    max_drawdown: float = 0.0  # worst peak-to-trough of session equity, USD
    pnl_by_symbol: dict[str, float] = field(default_factory=dict)
    events: int = 0  # tape messages replayed
    halted: bool = False  # daily loss stop fired

    @property
    def wins(self) -> int:
        return sum(1 for c in self.closes if c.pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for c in self.closes if c.pnl < 0)

    @property
    def profit_factor(self) -> float | None:
        gross_up = sum(c.pnl for c in self.closes if c.pnl > 0)
        gross_down = -sum(c.pnl for c in self.closes if c.pnl < 0)
        if gross_down <= 0:
            return None  # undefined without a losing close
        return gross_up / gross_down

    def summary(self) -> str:
        pf = self.profit_factor
        pf_text = f"{pf:.2f}" if pf is not None else "n/a (sem perda fechada)"
        lines = [
            f"P&L total: {self.total_pnl:+.2f} USD" + ("  [STOP DIÁRIO]" if self.halted else ""),
            f"Entradas: {self.entries}   Fechamentos: {len(self.closes)} "
            f"({self.wins}W/{self.losses}L)   PF: {pf_text}",
            f"Drawdown máx: {self.max_drawdown:.2f} USD",
        ]
        by_reason: dict[str, float] = {}
        for c in self.closes:
            by_reason[c.reason] = by_reason.get(c.reason, 0.0) + c.pnl
        if by_reason:
            lines.append(
                "Por motivo: " + "  ".join(f"{r}: {v:+.2f}" for r, v in sorted(by_reason.items()))
            )
        if self.pnl_by_symbol:
            lines.append(
                "Por símbolo: "
                + "  ".join(f"{s}: {v:+.2f}" for s, v in sorted(self.pnl_by_symbol.items()))
            )
        return "\n".join(lines)


class ScalperReplay:
    """One simulated bot session over a recorded tape (see module docstring)."""

    def __init__(self, params: ReplayParams | None = None) -> None:
        self.params = params or ReplayParams()
        symbols = list(self.params.lots)
        self.aggregator = OrderFlowAggregator(symbols=symbols)
        self.liquidity: dict[AssetSymbol, SessionLiquidity] = {}
        self.positions: dict[AssetSymbol, list[SimPosition]] = {s: [] for s in symbols}
        # Unfilled grid limit orders: (side, limit price, lots).
        self.pending: dict[AssetSymbol, list[tuple[Direction, float, float]]] = {
            s: [] for s in symbols
        }
        self.grid: dict[AssetSymbol, dict[str, Any]] = {}
        self.peak: dict[AssetSymbol, float] = {}
        self.cooldown_until: dict[AssetSymbol, float] = {}
        self.quotes: dict[AssetSymbol, tuple[float, float]] = {}  # (bid, ask)
        self.realized = 0.0
        self.armed = True
        self.flattening = False
        self.resume_at = 0.0
        self.report = ReplayReport()
        self._ticket = 0
        self._equity_peak = 0.0
        self._last_rx = ""

    # --- P&L ------------------------------------------------------------------

    def _pos_pnl(self, symbol: AssetSymbol, p: SimPosition) -> float:
        quote = self.quotes.get(symbol)
        if quote is None:
            return 0.0
        bid, ask = quote
        move = (bid - p.entry) if p.side == "buy" else (p.entry - ask)
        return move * self.params.usd_per_point.get(symbol, 1.0) * p.lots

    def _symbol_pnl(self, symbol: AssetSymbol) -> float:
        return sum(self._pos_pnl(symbol, p) for p in self.positions[symbol])

    def _floating(self) -> float:
        return sum(self._symbol_pnl(s) for s in self.positions)

    # --- execution (the simulated broker) --------------------------------------

    def _open_market(self, symbol: AssetSymbol, side: Direction, now: float) -> None:
        bid, ask = self.quotes[symbol]
        self._ticket += 1
        self.positions[symbol].append(
            SimPosition(
                side=side,
                lots=self.params.lots[symbol],
                entry=ask if side == "buy" else bid,
                opened_at=now,
                ticket=self._ticket,
            )
        )
        self.report.entries += 1

    def _fill_pending(self, symbol: AssetSymbol, price: float, now: float) -> None:
        """Fill grid limits the tape just printed through, at their limit price."""
        still: list[tuple[Direction, float, float]] = []
        for side, level, lots in self.pending[symbol]:
            hit = price <= level if side == "buy" else price >= level
            if hit and len(self.positions[symbol]) < self.params.max_per_symbol:
                self._ticket += 1
                self.positions[symbol].append(
                    SimPosition(
                        side=side, lots=lots, entry=level, opened_at=now, ticket=self._ticket
                    )
                )
                self.report.entries += 1
            else:
                still.append((side, level, lots))
        self.pending[symbol] = still

    def _close_symbol(self, symbol: AssetSymbol, reason: str) -> None:
        pnl = self._symbol_pnl(symbol)
        self.realized += pnl
        self.report.pnl_by_symbol[symbol.value] = (
            self.report.pnl_by_symbol.get(symbol.value, 0.0) + pnl
        )
        self.report.closes.append(
            CloseEvent(at=self._last_rx, scope=symbol.value, reason=reason, pnl=pnl)
        )
        self.positions[symbol] = []
        self.pending[symbol] = []
        self.peak.pop(symbol, None)
        self.grid.pop(symbol, None)

    def _close_all(self, reason: str) -> None:
        pnl = 0.0
        for symbol in list(self.positions):
            sym_pnl = self._symbol_pnl(symbol)
            pnl += sym_pnl
            self.report.pnl_by_symbol[symbol.value] = (
                self.report.pnl_by_symbol.get(symbol.value, 0.0) + sym_pnl
            )
            self.positions[symbol] = []
            self.pending[symbol] = []
            self.peak.pop(symbol, None)
            self.grid.pop(symbol, None)
        self.realized += pnl
        self.report.closes.append(
            CloseEvent(at=self._last_rx, scope="ACCOUNT", reason=reason, pnl=pnl)
        )

    def _as_positions(self, symbol: AssetSymbol, now: float) -> list[Position]:
        """Sim positions as the read-only `Position` mirror the signal reads."""
        quote = self.quotes.get(symbol)
        mid = (quote[0] + quote[1]) / 2.0 if quote else 0.0
        return [
            Position(
                symbol=symbol,
                ticket=p.ticket,
                side=p.side,
                volume=p.lots,
                price_open=p.entry,
                price_current=mid,
                profit=self._pos_pnl(symbol, p),
                seconds_open=max(0.0, now - p.opened_at),
            )
            for p in self.positions[symbol]
        ]

    # --- one tape message -------------------------------------------------------

    def feed(self, record: dict[str, Any]) -> None:
        """Replay one recorded line: update market state, then run the bot tick
        in the exact order of the live `_run_bot`."""
        msg = record["msg"]
        self._last_rx = str(record.get("rx", ""))
        now = parse_dt(record["rx"]).timestamp()
        self.report.events += 1

        mtype = msg.get("type")
        symbol = parse_symbol(msg.get("symbol")) if "symbol" in msg else None
        if symbol is None or not self.aggregator.tracks(symbol):
            return

        if mtype == "book":
            book = parse_book(msg, symbol)
            if book.bids and book.asks:
                self.quotes[symbol] = (book.bids[0].price, book.asks[0].price)
            self.aggregator.ingest_book(book)
        elif mtype == "trades":
            trades = [parse_trade({**raw, "symbol": symbol}, symbol) for raw in msg["trades"]]
            if not trades:
                return
            self.aggregator.ingest_trades(symbol, trades)
            for t in trades:
                self._fill_pending(symbol, t.price, now)
        elif mtype == "trade":
            trade = parse_trade(msg, symbol)
            self.aggregator.ingest_trade(trade)
            self._fill_pending(symbol, trade.price, now)
        elif mtype == "liquidity":
            self.liquidity[symbol] = parse_liquidity(msg, symbol)
        else:
            return

        self._bot_tick(symbol, now)
        # Session equity drawdown, marked after every event.
        equity = self.realized + self._floating()
        self._equity_peak = max(self._equity_peak, equity)
        self.report.max_drawdown = max(self.report.max_drawdown, self._equity_peak - equity)

    # --- the bot tick (mirrors _run_bot's order) ---------------------------------

    def _bot_tick(self, symbol: AssetSymbol, now: float) -> None:
        if not self.armed:
            return
        if self.flattening:
            # Sim closes are instant, so only the re-arm cooldown remains.
            if now >= self.resume_at:
                self.flattening = False
            return

        floating = self._floating()
        session = self.realized + floating

        if session <= -self.params.loss_stop:
            self._close_all("stop")
            self.armed = False
            self.report.halted = True
            return

        if floating >= self.params.profit_target:
            self._close_all("target")
            if self.params.rearm:
                self.flattening = True
                self.resume_at = now + scalper.REARM_COOLDOWN_S
            else:
                self.armed = False
            return

        snapshot = self.aggregator.snapshot(symbol)
        positions = self._as_positions(symbol, now)
        signal = compute_flow_signal(snapshot, positions)

        if not positions and now >= self.cooldown_until.get(symbol, 0.0):
            self.peak.pop(symbol, None)
            self.grid.pop(symbol, None)
            self.pending[symbol] = []

        current_side = held_side(positions)
        sym_pnl = sum(p.profit for p in positions)

        # Per-symbol hard stop — same order as the live tick: before lock/reverse.
        if current_side is not None and symbol_stopped(sym_pnl, self.params.symbol_stop_usd):
            self._close_symbol(symbol, "stop")
            self.cooldown_until[symbol] = now + self.params.cooldown_s
            return

        # Trailing profit lock (same constants the live bot imports).
        if current_side is not None:
            peak = max(self.peak.get(symbol, 0.0), sym_pnl)
            self.peak[symbol] = peak
            if peak >= scalper.LOCK_MIN_USD and 0 < sym_pnl <= peak * (1.0 - scalper.LOCK_GIVEBACK):
                self._close_symbol(symbol, "lock")
                self.cooldown_until[symbol] = now + self.params.cooldown_s
                return

        # Hybrid reverse: grid-region breach first, flow-signal fallback.
        if current_side is not None:
            grid = self.grid.get(symbol)
            quote = self.quotes.get(symbol)
            mid = (quote[0] + quote[1]) / 2.0 if quote else None
            broke = (
                grid is not None
                and mid is not None
                and region_broken(mid, current_side, grid["breach"])
            )
            if broke or (grid is None and signal_says_reverse(signal)):
                self._close_symbol(symbol, "reverse")
                self.cooldown_until[symbol] = now + self.params.cooldown_s
                return

        # Entry: flat, no grid pending, thin-session gate, explosion signal.
        if self.positions[symbol] or symbol in self.grid:
            return
        liq = self.liquidity.get(symbol)
        liquidity_ok = liq is None or liq.ratio >= scalper.THIN_RATIO
        direction = signal_entry_direction(signal)
        cooldown_ok = now >= self.cooldown_until.get(symbol, 0.0)
        if not should_open(
            direction=direction,
            open_on_symbol=0,
            max_per_symbol=self.params.max_per_symbol,
            cooldown_ok=cooldown_ok,
            daily_halted=False,
            liquidity_ok=liquidity_ok,
        ):
            return
        assert direction is not None
        quote = self.quotes.get(symbol)
        rpb = snapshot.live_activity.range_per_bar if snapshot.live_activity else 0.0
        if quote is None or rpb <= 0:
            return
        bid, ask = quote
        entry = ask if direction == "buy" else bid
        lots = self.params.lots[symbol]
        levels = grid_levels(entry, direction, rpb)
        self.grid[symbol] = {
            "side": direction,
            "breach": grid_breach_price(entry, direction, rpb),
        }
        self.cooldown_until[symbol] = now + self.params.cooldown_s
        self._open_market(symbol, direction, now)
        self.pending[symbol] = [(direction, level, lots) for level in levels]

    # --- finishing ---------------------------------------------------------------

    def finish(self) -> ReplayReport:
        """Close any still-open positions at the last quote (an end-of-tape
        mark-to-market, not a live-bot behavior) and total the books."""
        if any(self.positions.values()):
            self._close_all("eod")
        self.report.total_pnl = self.realized
        return self.report


def iter_tape(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    """Yield recorded lines from tape JSONL files in the given order.

    Skips lines that are not valid JSON — a collector restart can truncate the
    line it was writing, and one bad line must not kill a whole replay.
    """
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def replay(paths: Iterable[Path], params: ReplayParams | None = None) -> ReplayReport:
    """Run one full replay over the given tape files and return the report."""
    sim = ScalperReplay(params)
    for record in iter_tape(paths):
        sim.feed(record)
    return sim.finish()


__all__ = [
    "DEFAULT_LOTS",
    "DEFAULT_USD_PER_POINT",
    "CloseEvent",
    "ReplayParams",
    "ReplayReport",
    "ScalperReplay",
    "iter_tape",
    "replay",
]
