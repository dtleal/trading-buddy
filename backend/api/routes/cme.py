"""REST endpoint: Baleia / Banco / Sardinha on the CME tape (GC, NQ, ES).

Same source as the B3 tab: the Profit RTD collector streams every linked Times &
Trades window, and the B3 ingest hands the CME ones here (`feed`). Needs the
Nelogica "Sinal CME Level 2" plugin, without it Profit has no CME tape.

Every counted print is also written to `cme_tape_dir` (one JSON line per print,
one file per market per day), so a backend restart rebuilds the day and the
size cuts in `aggregate_cme` can be calibrated on real tape later.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from adapters.profit_rtd import parse_time
from api.routes.players import B3_TZ, PlayersResponse, PlayersTickModel, AssetPlayersModel
from settings import get_settings
from use_cases.aggregate_cme import CmeAccumulator, CmePrint, market_of

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cme", tags=["cme"])

_books: dict[str, CmeAccumulator] = {}  # market -> today's accumulator
_days: dict[str, date] = {}
_cuts: dict[str, datetime | None] = {}  # drop prints up to here on the first batch
_dropped: dict[str, int] = {}
_last_drop_log: dict[str, float] = {}


def _tape_path(asset: str, day: date) -> Path | None:
    directory = get_settings().cme_tape_dir.strip()
    return Path(directory) / f"{asset}_{day.isoformat()}.jsonl" if directory else None


def _book(asset: str, market: Any, today: date) -> CmeAccumulator:
    """Today's accumulator, rebuilt from our own recording when it is new."""
    if asset in _books and _days[asset] == today:
        return _books[asset]
    book = CmeAccumulator(market)
    path = _tape_path(asset, today)
    if path is not None and path.exists():
        prints = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                prints.append(CmePrint(datetime.fromisoformat(raw["at"]), raw["price"], raw["qty"], raw["buy"]))
            except (ValueError, KeyError, TypeError):
                continue
        book.feed(prints)
        logger.info("CME %s: %d negocios recuperados da gravacao", asset, len(prints))
    _books[asset], _days[asset] = book, today
    _cuts[asset] = book.last_trade
    return book


def _parse(raw: dict[str, Any], day: date, factor: float) -> CmePrint | None:
    """One wire row from the collector, or None when it cannot be trusted."""
    at = parse_time(str(raw.get("at", "")), day)
    side = str(raw.get("aggressor", "")).strip().casefold()[:1]
    if at is None or side not in ("c", "b", "v", "s"):  # comprador/buy, vendedor/sell
        return None
    try:
        price, qty = float(str(raw["price"])), float(str(raw["qty"]))
    except (KeyError, TypeError, ValueError):
        return None
    if price <= 0 or qty <= 0:
        return None
    return CmePrint(at=at, price=price, qty=qty * factor, buy=side in ("c", "b"))


def is_cme(symbol: str) -> bool:
    return market_of(symbol) is not None


def feed(message: dict[str, Any]) -> None:
    """One batch from the collector, for a CME window."""
    symbol = str(message.get("asset", ""))
    found = market_of(symbol)
    if found is None:
        return
    market, factor = found
    today = datetime.now(B3_TZ).date()
    book = _book(market.asset, market, today)
    book.symbol = symbol.upper()
    prints, rejected = [], None
    for raw in message.get("trades", []):
        p = _parse(raw, today, factor)
        if p is None:
            _dropped[market.asset] = _dropped.get(market.asset, 0) + 1
            rejected = raw
        else:
            prints.append(p)
    cut = _cuts.get(market.asset)
    if cut is not None:
        # The first batch after a restart repeats what the recording already has.
        prints = [p for p in prints if p.at > cut]
        _cuts[market.asset] = None
    if rejected is not None and monotonic() - _last_drop_log.get(market.asset, 0.0) > 60:
        _last_drop_log[market.asset] = monotonic()
        logger.warning(
            "CME %s: %d negocios descartados; exemplo: %r", market.asset, _dropped[market.asset], rejected
        )
    if not prints:
        return
    book.feed(prints)
    path = _tape_path(market.asset, today)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for p in prints:
                handle.write(json.dumps({"at": p.at.isoformat(), "price": p.price, "qty": p.qty, "buy": p.buy}) + "\n")


@router.get("", response_model=PlayersResponse)
async def cme_players() -> PlayersResponse:
    now = datetime.now(B3_TZ).replace(tzinfo=None)
    assets = [
        AssetPlayersModel(**asdict(book.snapshot(_days[asset].isoformat(), now)), live=True)
        for asset, book in sorted(_books.items())
    ]
    return PlayersResponse(source="profit-rtd", loading=False, assets=assets)


@router.websocket("/ws/tick")
async def cme_tick_stream(websocket: WebSocket) -> None:
    """Price and print count per market, pushed when they change (same as B3)."""
    await websocket.accept()
    last: str | None = None
    try:
        while True:
            ticks = [
                PlayersTickModel(
                    asset=asset, last_price=book.last_price, last_trade=book.last_trade, trades=book.trades
                ).model_dump(mode="json")
                for asset, book in sorted(_books.items())
            ]
            payload = json.dumps(ticks)
            if payload != last:
                await websocket.send_text(payload)
                last = payload
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return
