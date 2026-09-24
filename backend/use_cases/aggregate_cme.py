"""Baleia / Banco / Sardinha on the CME tape (gold, Nasdaq, S&P futures).

The CME tape is anonymous: there is no broker on either side of a print, only
the price, the size and who aggressed. So the groups here come from the size of
the print, not from who sent it:

- baleia: a big print (at least `whale` mini contracts)
- banco: a medium print (at least `bank`)
- sardinha: everything smaller

Only the aggressor is known, so a group's saldo is what it *bought by
aggression* minus what it *sold by aggression*. Unlike the B3 partition, the
three saldos do not add up to zero: the passive side sat in the book and has
no size class of its own.

Micro contracts (MGC, MNQ, MES) are one tenth of the mini and count as 0.1 of
it, so one tape per market carries both.

THE CUTS BELOW ARE A FIRST GUESS. Calibrate them on two weeks of recorded tape
(`data/cme_tape`) before trusting the groups.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from use_cases.aggregate_players import (
    AGGRESSION_KEEP,
    AGGRESSION_SECONDS,
    BUCKET_MINUTES,
    GROUPS,
    RECENT_MINUTES,
    STALE_AFTER_SECONDS,
    PlayerRead,
    PlayersSnapshot,
    _side,
)


@dataclass(frozen=True, slots=True)
class CmeMarket:
    asset: str  # what the tab shows: GC, NQ, ES
    usd_per_point: float  # for one mini contract
    whale: float  # min print size (mini contracts) for baleia
    bank: float  # min print size for banco
    aggression: float  # contracts in AGGRESSION_SECONDS that make an aggression


MARKETS: dict[str, CmeMarket] = {
    "GC": CmeMarket("GC", 100.0, whale=10, bank=3, aggression=150),
    "NQ": CmeMarket("NQ", 20.0, whale=10, bank=3, aggression=150),
    "ES": CmeMarket("ES", 50.0, whale=25, bank=5, aggression=400),
}

# Profit symbol root -> (market, how many minis one contract is).
ROOTS: dict[str, tuple[str, float]] = {
    "MGC": ("GC", 0.1),
    "MNQ": ("NQ", 0.1),
    "MES": ("ES", 0.1),
    "GC": ("GC", 1.0),
    "NQ": ("NQ", 1.0),
    "ES": ("ES", 1.0),
}


def market_of(symbol: str) -> tuple[CmeMarket, float] | None:
    """`GCZ26`, `MNQZ26`, `@ES`… -> its market and mini factor, or None."""
    text = symbol.strip().upper().lstrip("@")
    for root in sorted(ROOTS, key=len, reverse=True):  # MGC before GC
        if text.startswith(root):
            market, factor = ROOTS[root]
            return MARKETS[market], factor
    return None


@dataclass(frozen=True, slots=True)
class CmePrint:
    at: datetime
    price: float
    qty: float  # in mini contracts
    buy: bool  # True = the buyer aggressed


@dataclass(slots=True)
class _Window:
    group: str
    side: int
    at: datetime
    price_from: float
    price_to: float
    qty: float = 0.0
    trades: int = 0
    notional: float = 0.0


class CmeAccumulator:
    """Running totals for one market, fed the tape in order."""

    def __init__(self, market: CmeMarket) -> None:
        self.market = market
        self.symbol = market.asset
        self.net: dict[str, float] = defaultdict(float)
        self.net_usd: dict[str, float] = defaultdict(float)
        self.gross: dict[str, float] = defaultdict(float)
        self.gross_usd: dict[str, float] = defaultdict(float)
        self.bought: dict[str, float] = defaultdict(float)
        self.buckets: dict[datetime, dict[str, float]] = {}
        self._window: int | None = None
        self._open: dict[tuple[str, int], _Window] = {}
        self.aggressions: deque[_Window] = deque(maxlen=AGGRESSION_KEEP)
        self.trades = 0
        self.contracts = 0.0
        self.last_price: float | None = None
        self.first_trade: datetime | None = None
        self.last_trade: datetime | None = None

    def group_of(self, qty: float) -> str:
        if qty >= self.market.whale:
            return "baleia"
        if qty >= self.market.bank:
            return "banco"
        return "sardinha"

    def feed(self, prints: list[CmePrint]) -> None:
        for p in prints:
            self.trades += 1
            self.contracts += p.qty
            if self.first_trade is None:
                self.first_trade = p.at
            self.last_trade = p.at
            self.last_price = p.price
            group = self.group_of(p.qty)
            side = 1 if p.buy else -1
            usd = p.price * p.qty * self.market.usd_per_point
            self.net[group] += side * p.qty
            self.net_usd[group] += side * usd
            self.gross[group] += p.qty
            self.gross_usd[group] += usd
            if p.buy:
                self.bought[group] += p.qty
            bucket = self._bucket(p.at)
            bucket["price"] = p.price
            bucket[group] += side * p.qty
            bucket[group + "_usd"] += side * usd
            bucket[group + "_v"] += p.qty
            self._aggression(p, group, side)

    def _aggression(self, p: CmePrint, group: str, side: int) -> None:
        """Same group, same side, inside AGGRESSION_SECONDS. Sardinha is left
        out: many small prints in a row are many people, not one order."""
        window = int(p.at.timestamp()) // AGGRESSION_SECONDS
        if window != self._window:
            for item in self._open.values():
                if item.qty >= self.market.aggression:
                    self.aggressions.append(item)
            self._open = {}
            self._window = window
        if group == "sardinha":
            return
        current = self._open.get((group, side))
        if current is None:
            current = self._open[(group, side)] = _Window(group, side, p.at, p.price, p.price)
        current.qty += p.qty
        current.trades += 1
        current.notional += p.price * p.qty
        current.price_to = p.price

    def _bucket(self, at: datetime) -> dict[str, float]:
        key = at.replace(minute=(at.minute // BUCKET_MINUTES) * BUCKET_MINUTES, second=0, microsecond=0)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = defaultdict(float)
        return bucket

    def snapshot(self, session: str, now: datetime) -> PlayersSnapshot:
        ordered = sorted(self.buckets.items())
        cutoff = self.last_trade - timedelta(minutes=RECENT_MINUTES) if self.last_trade else None
        tail = [v for k, v in ordered if cutoff is None or k >= cutoff]
        biggest = max((abs(self.net_usd[g]) for g in GROUPS), default=0.0)
        m = self.market
        papel = {
            "baleia": f"lote {m.whale:g}+",
            "banco": f"lote {m.bank:g}-{m.whale - 1:g}",
            "sardinha": f"lote < {m.bank:g}",
        }
        players = []
        for group in GROUPS:
            recent = sum(v[group] for v in tail)
            volume = self.gross[group]
            players.append(
                PlayerRead(
                    key=group,
                    label=group.upper(),
                    papel=papel[group],
                    fonte="lote",
                    saldo_rs=round(self.net_usd[group], 2),
                    saldo_recente_rs=round(sum(v[group + "_usd"] for v in tail), 2),
                    saldo=round(self.net[group]),
                    saldo_recente=round(recent),
                    volume=round(volume),
                    volume_rs=round(self.gross_usd[group], 2),
                    forca_pct=round(100 * abs(self.net_usd[group]) / biggest, 1) if biggest else 0.0,
                    # Share of its volume that was buying (the CME tape only
                    # has the aggressor, so everyone here aggressed).
                    agressao_pct=round(100 * self.bought[group] / volume, 1) if volume else 0.0,
                    lado=_side(round(recent), round(sum(v[group + "_v"] for v in tail))),
                )
            )
        series = [
            {
                "at": key.isoformat(),
                **{g: round(value[g + "_usd"]) for g in GROUPS},
                "rlp": 0,
                "price": value["price"],
            }
            for key, value in ordered
        ]
        open_now = [w for w in self._open.values() if w.qty >= m.aggression]
        aggressions = [
            {
                "at": w.at.isoformat(),
                "qty": round(w.qty),
                "trades": w.trades,
                "lado": "COMPRA" if w.side > 0 else "VENDA",
                "agressor": w.group.upper(),
                "grupo": w.group,
                "price_from": w.price_from,
                "price_avg": round(w.notional / w.qty, 2) if w.qty else w.price_from,
                "price_to": w.price_to,
            }
            for w in sorted((*open_now, *self.aggressions), key=lambda w: w.at, reverse=True)
        ]
        lag = None if self.last_trade is None else int((now - self.last_trade).total_seconds())
        return PlayersSnapshot(
            asset=m.asset,
            symbol=self.symbol,
            session=session,
            first_trade=self.first_trade,
            last_trade=self.last_trade,
            trades=self.trades,
            contracts=round(self.contracts),
            residual_rs=0.0,
            last_price=self.last_price,
            lag_seconds=lag,
            players=players,
            series=series,
            top_brokers=[],
            aggressions=aggressions,
            stale=lag is None or lag > STALE_AFTER_SECONDS,
        )
