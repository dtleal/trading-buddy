"""Turns the Profit tape into the Baleia / Banco / Sardinha read.

Three groups, and they are *not* equally trustworthy — the snapshot says so per
card, because pretending otherwise is how you end up trading a guess:

The three groups are a **closed partition**: every aggression print has a buyer
and a seller, each broker belongs to exactly one group, so the three nets
always add up to zero. That is not decoration — it is the check that says the
model is complete. A residual means somebody is unclassified and the picture is
lying about how much is on each side.

- **Baleia** — foreign desks and the interdealer brokers (Tullett, BGC), where
  bank and non-resident flow goes through.
- **Banco** — the bank *desks* only: Itaú Unibanco, Bradesco, Santander
  Institucional, BB, Safra, Banco BTG.
- **Sardinha** — everything else, which is the retail houses plus the retail
  arms of the banks.

Why the bank's retail arm counts as sardinha, and not as banco: RLP is B3's
Retail Liquidity Provider mechanism and by rule only covers retail clients, so
the share of a broker's flow that comes through RLP measures how retail it is.
Measured on WIN, 16/09/2026: BTG 21%, Itaú (corretora) 26%, Santander
(corretora) 29% — same range as XP at 25%. UBS, Morgan, Goldman and Tullett are
flat 0%. So "Itaú" on the tape is mostly Itaú's customers, not Itaú's desk, and
putting it under BANCO is what made the bank line read +R$ 776 mi when the
reference screen had it near zero.

Alongside the three, the snapshot carries **RLP** on its own: the retail client
side of the internalised prints, which never touch the book. It is the one
number here that B3 itself marks as retail rather than us reading a broker
name, so it is reported separately instead of being folded into the total.

Everything is per session (the tape file is one day). The headline number is
in reais, taken from the financial field the tape already carries (it has B3's
multiplier baked in: ×10 for WDO, ×0,20 for WIN), because money is the only
unit that lets you compare what the whale is doing in the dollar with what it
is doing in the index. Contracts are kept alongside it.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from adapters.profit_tape import (
    TYPE_BUY_AGGRESSION,
    TYPE_RLP,
    TYPE_SELL_AGGRESSION,
    Trade,
)

# Broker codes from Profit's `newagents.dat`. Codes are the stable identity —
# B3 reassigns display names far more often than numbers.
BALEIA_CODES: frozenset[int] = frozenset(
    {
        8, 995,       # UBS
        13,           # Merrill Lynch
        16, 206,      # J.P. Morgan
        40,           # Morgan Stanley
        45, 833,      # Credit Suisse
        77, 298,      # Citi
        238,          # Goldman Sachs
        127,          # Tullett Prebon   (interdealer)
        122,          # BGC Liquidez     (interdealer)
        688,          # ABN AMRO
        363,          # Credit Financier Invest
        262,          # Mirae Asset
    }
)

# Only the bank desks. The banks' own brokerages (Itaú 114, BTG 85, Santander
# 4090, Ágora 39) trade their customers' flow and carry 20-30% RLP, so they sit
# with the retail crowd — see the module docstring.
BANCO_CODES: frozenset[int] = frozenset(
    {
        2028,         # Itaú Unibanco (o banco)
        72,           # Bradesco
        27, 622, 635, # Santander institucional / banco
        59, 304,      # Safra
        254, 2659,    # Banco do Brasil
        1026,         # Banco BTG Pactual
    }
)

# Bucket size for the intraday series the tab draws.
BUCKET_MINUTES = 5

# How long without a new print before we call the tape stale.
#
# Profit does not write the `.trd` print by print — it flushes in bursts, and
# it looks like the trigger is buffer size rather than a timer: measured on
# 16/09/2026, WIN (heavy) was ~30s behind while WDO (thinner) sat 3+ minutes
# without a write. So a short threshold would flash "fita parada" all day on
# the quiet contract. The snapshot also carries `lag_seconds`, which is the
# number that actually tells you how old the read is.
STALE_AFTER_SECONDS = 300

# How far back the "recent" window looks, in minutes. Counted from the last
# print, not as "the last N buckets" — on a thin tape the last three buckets
# can span an hour, and calling that "últimos 15 min" would be a lie.
RECENT_MINUTES = 15

GROUPS = ("baleia", "banco", "sardinha")

# Agressão: um mesmo agressor martelando o mesmo lado dentro de uma janela.
#
# É assim que uma ordem grande de verdade aparece. A B3 fatia: o maior negócio
# único medido foi 1.465 contratos no WIN e 2.232 no WDO, então "a baleia
# mandou 10 mil" nunca é uma linha na fita — são centenas de linhas do mesmo
# agressor em poucos minutos.
#
# Só baleia e banco entram. Uma corretora de varejo agredindo 30.000 contratos
# em 2 min não é um player: é a soma dos clientes dela (a XP fez isso em 18.574
# negócios separados, ~2,9 contratos cada). Só serviria pra empurrar o que
# interessa pra fora da lista.
#
# Os cortes são por ativo, e medidos já com esse filtro: o maior que baleia ou
# banco fez numa janela foi 13.411 no WIN e 7.278 no WDO, ou seja, o corte de
# quando a lista tinha varejo (25.000 no WIN) nunca dispararia. Nos valores
# abaixo dá 12 a 25 por dia em cada ativo, medido em 21/09 e 16/09/2026.
AGGRESSION_SECONDS = 120
AGGRESSION_CONTRACTS: dict[str, int] = {"WIN": 7_000, "WDO": 3_000}
AGGRESSION_KEEP = 20


@dataclass(frozen=True, slots=True)
class PlayerRead:
    key: str
    label: str
    papel: str
    fonte: str  # "rlp" = B3 marking, "corretora" = our reading of the broker
    saldo_rs: float  # net BRL on the session, + bought / - sold
    saldo_recente_rs: float  # net BRL over the last RECENT_MINUTES
    saldo: int  # the same, in contracts
    saldo_recente: int
    volume: int  # gross contracts touched
    volume_rs: float
    forca_pct: float  # |saldo_rs| against the biggest group of the day, 0-100
    agressao_pct: float  # share of its volume where it was the aggressor
    lado: str  # "BUY" | "SELL" | "NEUTRAL", read off saldo_recente


@dataclass(frozen=True, slots=True)
class PlayersSnapshot:
    asset: str
    symbol: str
    session: str  # YYYY-MM-DD of the tape file
    first_trade: datetime | None
    last_trade: datetime | None
    trades: int
    contracts: int
    # Soma dos três grupos. Tem que ser zero; qualquer resto é bug de mapeamento.
    residual_rs: float
    last_price: float | None
    lag_seconds: int | None  # how far behind the last print is, in seconds
    players: list[PlayerRead]
    series: list[dict[str, object]]
    top_brokers: list[dict[str, object]]
    # Agressões de AGGRESSION_SECONDS, mais nova primeiro (janela aberta inclusa).
    aggressions: list[dict[str, object]]
    stale: bool


def _side(saldo_recente: int, volume_recente: int) -> str:
    """Side from the recent window, not the whole session.

    A group that bought all morning and sold all afternoon ends the day flat;
    what a scalper needs is what it is doing now. The floor is 5% of what the
    group traded *in that same window*, so a thin late-afternoon bucket does
    not get called a side on a handful of contracts.
    """
    if volume_recente == 0 or abs(saldo_recente) < max(10, volume_recente * 0.05):
        return "NEUTRAL"
    return "BUY" if saldo_recente > 0 else "SELL"


class PlayersAccumulator:
    """Running totals for one contract, fed the tape in order.

    Live reading tails a file that only grows, so re-parsing and re-summing a
    whole 24 MB session every few seconds would be pure waste. The accumulator
    keeps the per-group totals and the 5-minute buckets, and `feed` takes only
    what Profit appended since the last poll. `snapshot` is cheap.
    """

    __slots__ = (
        "net", "net_rs", "gross", "gross_rs", "aggressive", "broker_net",
        "broker_vol", "buckets", "_previous_price", "_retail_sign",
        "last_price", "contracts", "trades", "first_trade", "last_trade",
        "asset", "_cut", "_window", "_open", "aggressions",
    )

    def __init__(self, asset: str = "") -> None:
        # O corte é por ativo, e a janela é montada negócio a negócio, então o
        # acumulador precisa saber de quem ele é desde o começo. Ativo fora da
        # tabela simplesmente não gera agressão.
        self.asset = asset
        self._cut = AGGRESSION_CONTRACTS.get(asset.upper(), 0)
        self._window: int | None = None
        self._open: dict[tuple[int, int], _Aggression] = {}
        self.aggressions: deque[_Aggression] = deque(maxlen=AGGRESSION_KEEP)
        self.net: dict[str, int] = defaultdict(int)
        self.net_rs: dict[str, float] = defaultdict(float)
        self.gross: dict[str, int] = defaultdict(int)
        self.gross_rs: dict[str, float] = defaultdict(float)
        self.aggressive: dict[str, int] = defaultdict(int)
        self.broker_net: dict[int, int] = defaultdict(int)
        self.broker_vol: dict[int, int] = defaultdict(int)
        self.buckets: dict[datetime, dict[str, float]] = {}
        self._previous_price: float | None = None
        self._retail_sign = 0
        self.last_price: float | None = None
        self.contracts = 0
        self.trades = 0
        self.first_trade: datetime | None = None
        self.last_trade: datetime | None = None

    def feed(self, trades: list[Trade]) -> None:
        for trade in trades:
            self.trades += 1
            if self.first_trade is None:
                self.first_trade = trade.at
            self.last_trade = trade.at
            self.last_price = trade.price
            bucket = self._bucket(trade.at)
            bucket["price"] = trade.price

            if trade.kind == TYPE_RLP:
                # Internalised: the broker is the counterparty to its own retail
                # client, so it never reaches the book and stays out of the
                # partition. Tracked on its own because it is the only retail
                # marking that comes from B3 instead of from reading a name.
                self.contracts += trade.qty
                if self._previous_price is not None and trade.price != self._previous_price:
                    self._retail_sign = 1 if trade.price > self._previous_price else -1
                if self._retail_sign:
                    self.net["rlp"] += self._retail_sign * trade.qty
                    self.net_rs["rlp"] += self._retail_sign * trade.financial
                    bucket["rlp"] += self._retail_sign * trade.qty
                    bucket["rlp_rs"] += self._retail_sign * trade.financial
                self.gross["rlp"] += trade.qty
                self.gross_rs["rlp"] += trade.financial
                bucket["rlp_v"] += trade.qty
                # The client's order is the one taking liquidity.
                self.aggressive["rlp"] += trade.qty
            elif trade.kind in (TYPE_BUY_AGGRESSION, TYPE_SELL_AGGRESSION):
                self.contracts += trade.qty
                self.broker_net[trade.buyer] += trade.qty
                self.broker_net[trade.seller] -= trade.qty
                self.broker_vol[trade.buyer] += trade.qty
                self.broker_vol[trade.seller] += trade.qty
                buyer_aggressed = trade.kind == TYPE_BUY_AGGRESSION
                self._aggression(trade, buyer_aggressed)
                for code, side, aggressed in (
                    (trade.buyer, 1, buyer_aggressed),
                    (trade.seller, -1, not buyer_aggressed),
                ):
                    group = _group_of(code)
                    self.net[group] += side * trade.qty
                    self.net_rs[group] += side * trade.financial
                    self.gross[group] += trade.qty
                    self.gross_rs[group] += trade.financial
                    bucket[group] += side * trade.qty
                    bucket[group + "_rs"] += side * trade.financial
                    bucket[group + "_v"] += trade.qty
                    if aggressed:
                        self.aggressive[group] += trade.qty

            if trade.price != self._previous_price:
                self._previous_price = trade.price

    def _aggression(self, trade: Trade, buyer_aggressed: bool) -> None:
        """Soma o negócio na janela do seu agressor, e fecha a janela anterior.

        Só o agressor entra: o passivo estava parado no book, quem repetiu a
        ordem foi quem cruzou o spread. E só baleia ou banco — ver a nota em
        AGGRESSION_CONTRACTS.
        """
        if not self._cut:
            return
        window = (trade.at.toordinal() * 86400 + _seconds(trade.at)) // AGGRESSION_SECONDS
        if window != self._window:
            self._close_window()
            self._window = window
        code = trade.buyer if buyer_aggressed else trade.seller
        if _group_of(code) == "sardinha":
            return
        key = (code, 1 if buyer_aggressed else -1)
        current = self._open.get(key)
        if current is None:
            current = self._open[key] = _Aggression(
                code=code,
                side=key[1],
                at=trade.at,
                price_from=trade.price,
                price_to=trade.price,
            )
        current.qty += trade.qty
        current.trades += 1
        current.notional += trade.price * trade.qty
        current.price_to = trade.price

    def _close_window(self) -> None:
        """Guarda as janelas que bateram o corte e joga o resto fora."""
        for item in self._open.values():
            if item.qty >= self._cut:
                self.aggressions.append(item)
        self._open = {}

    def _bucket(self, at: datetime) -> dict[str, float]:
        key = at.replace(
            minute=(at.minute // BUCKET_MINUTES) * BUCKET_MINUTES, second=0, microsecond=0
        )
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = {
                "baleia": 0, "banco": 0, "sardinha": 0, "rlp": 0,
                "baleia_v": 0, "banco_v": 0, "sardinha_v": 0, "rlp_v": 0,
                "baleia_rs": 0.0, "banco_rs": 0.0, "sardinha_rs": 0.0, "rlp_rs": 0.0,
                "price": 0.0,
            }
        return bucket

    def snapshot(
        self, agents: dict[int, str], asset: str, symbol: str, session: str, now: datetime
    ) -> PlayersSnapshot:
        ordered = sorted(self.buckets.items())
        cutoff = (
            self.last_trade - timedelta(minutes=RECENT_MINUTES)
            if self.last_trade is not None
            else None
        )
        tail = [item for item in ordered if cutoff is None or item[0] >= cutoff]
        keys = (*GROUPS, "rlp")
        recent = {g: sum(int(v[g]) for _, v in tail) for g in keys}
        recent_rs = {g: sum(float(v[g + "_rs"]) for _, v in tail) for g in keys}
        recent_volume = {g: sum(int(v[g + "_v"]) for _, v in tail) for g in keys}
        biggest = max((abs(self.net_rs[g]) for g in GROUPS), default=0.0)
        stats = _Stats(
            net=self.net,
            net_rs=self.net_rs,
            gross=self.gross,
            gross_rs=self.gross_rs,
            aggressive=self.aggressive,
            recent=recent,
            recent_rs=recent_rs,
            recent_volume=recent_volume,
            biggest=biggest,
        )

        players = [
            _read("baleia", "BALEIA", "estrangeiro", "corretora", stats),
            _read("banco", "BANCO", "institucional", "corretora", stats),
            _read("sardinha", "SARDINHA", "varejo", "corretora", stats),
            _read("rlp", "RLP", "varejo internalizado", "rlp", stats),
        ]
        series = [
            {
                "at": key.isoformat(),
                # The chart speaks reais too, so both panels can be read the
                # same way even though a WDO and a WIN contract are not the
                # same size.
                "baleia": round(value["baleia_rs"]),
                "banco": round(value["banco_rs"]),
                "sardinha": round(value["sardinha_rs"]),
                "rlp": round(value["rlp_rs"]),
                "price": value["price"],
            }
            for key, value in ordered
        ]
        top = sorted(self.broker_vol.items(), key=lambda item: item[1], reverse=True)[:12]
        top_brokers = [
            {
                "code": code,
                "name": agents.get(code, str(code)),
                "volume": volume,
                "saldo": self.broker_net[code],
                "grupo": _group_of(code) or "outros",
            }
            for code, volume in top
        ]
        # A janela aberta entra junto: uma agressão que só aparece dois minutos
        # depois de acontecer não serve pra nada em tela.
        open_now = [item for item in self._open.values() if item.qty >= self._cut]
        aggressions = [
            _aggression_row(item, agents)
            for item in sorted((*open_now, *self.aggressions), key=lambda i: i.at, reverse=True)
        ]
        residual = sum(self.net_rs[g] for g in GROUPS)
        lag = None if self.last_trade is None else int((now - self.last_trade).total_seconds())
        stale = lag is None or lag > STALE_AFTER_SECONDS
        return PlayersSnapshot(
            asset=asset,
            symbol=symbol,
            session=session,
            first_trade=self.first_trade,
            last_trade=self.last_trade,
            trades=self.trades,
            contracts=self.contracts,
            residual_rs=round(residual, 2),
            last_price=self.last_price,
            lag_seconds=lag,
            players=players,
            series=series,
            top_brokers=top_brokers,
            aggressions=aggressions,
            stale=stale,
        )


def aggregate_players(
    trades: list[Trade],
    agents: dict[int, str],
    asset: str,
    symbol: str,
    session: str,
    now: datetime,
) -> PlayersSnapshot:
    """One-shot read of a whole tape. Used by replays and tests."""
    accumulator = PlayersAccumulator(asset)
    accumulator.feed(trades)
    return accumulator.snapshot(agents, asset, symbol, session, now)


@dataclass(slots=True)
class _Aggression:
    """Uma janela de AGGRESSION_SECONDS de um agressor num lado só."""

    code: int
    side: int  # 1 = comprando, -1 = vendendo
    at: datetime  # primeiro negócio da janela
    price_from: float
    price_to: float
    qty: int = 0
    trades: int = 0
    # Preço x quantidade somado, pra sair o preço médio ponderado no fim. A
    # média simples dos negócios mentiria: um print de 1 contrato pesaria o
    # mesmo que um de 500.
    notional: float = 0.0


def _seconds(at: datetime) -> int:
    return at.hour * 3600 + at.minute * 60 + at.second


def _aggression_row(item: _Aggression, agents: dict[int, str]) -> dict[str, object]:
    return {
        "at": item.at.isoformat(),
        "qty": item.qty,
        "trades": item.trades,
        "lado": "COMPRA" if item.side > 0 else "VENDA",
        "agressor": agents.get(item.code, str(item.code)),
        "grupo": _group_of(item.code),
        "price_from": item.price_from,
        "price_avg": round(item.notional / item.qty, 2) if item.qty else item.price_from,
        "price_to": item.price_to,
    }


def _group_of(code: int) -> str:
    """Every broker lands somewhere. A default of "sardinha" is what keeps the
    three nets adding up to zero — an "outros" bucket would silently drop flow
    (it was hiding 3% of WIN's volume, all of it Santander's brokerage)."""
    if code in BALEIA_CODES:
        return "baleia"
    if code in BANCO_CODES:
        return "banco"
    return "sardinha"


@dataclass(frozen=True, slots=True)
class _Stats:
    """Everything `_read` needs, named — the tuple version had nine positions
    and was one reorder away from a silent bug."""

    net: dict[str, int]
    net_rs: dict[str, float]
    gross: dict[str, int]
    gross_rs: dict[str, float]
    aggressive: dict[str, int]
    recent: dict[str, int]
    recent_rs: dict[str, float]
    recent_volume: dict[str, int]
    biggest: float


def _read(key: str, label: str, papel: str, fonte: str, stats: _Stats) -> PlayerRead:
    volume = stats.gross[key]
    saldo_rs = stats.net_rs[key]
    return PlayerRead(
        key=key,
        label=label,
        papel=papel,
        fonte=fonte,
        saldo_rs=round(saldo_rs, 2),
        saldo_recente_rs=round(stats.recent_rs[key], 2),
        saldo=stats.net[key],
        saldo_recente=stats.recent[key],
        volume=volume,
        volume_rs=round(stats.gross_rs[key], 2),
        forca_pct=round(100 * abs(saldo_rs) / stats.biggest, 1) if stats.biggest else 0.0,
        agressao_pct=round(100 * stats.aggressive[key] / volume, 1) if volume else 0.0,
        lado=_side(stats.recent[key], stats.recent_volume[key]),
    )
