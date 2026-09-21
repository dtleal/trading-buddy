"""REST endpoint: who is carrying the Ibovespa today.

The Players tab reads the WIN tape, and the WIN is the index. Ten names make
up about half of it, so when the index moves it is almost always one of them
moving — this is the panel that says which.

`contrib_pct` is the number to read: weight × move, i.e. how many percent of
the index that single name is responsible for today. The move on its own is
noise (a 3% jump on a 0,5% weight is nothing).

Alongside it, `niveis` counts the whole index by how far each name has moved.
That is the other half of the question: the top 10 says what is pulling, the
count says whether the rest of the market came along or the index is being
carried by three names.
"""

from __future__ import annotations

from time import monotonic

import anyio
from fastapi import APIRouter
from pydantic import BaseModel

from adapters.ibov import fetch_changes, load_weights

router = APIRouter(prefix="/api/ibov", tags=["ibov"])

# How many names the panel carries. Ten is where the reference screen stops and
# where the curve flattens: the top 10 is ~54% of the index, the next 10 adds
# 21%, the remaining 56 share the rest.
TOP = 10

# Yahoo is delayed ~15 minutes, so a faster poll would only re-fetch the same
# number and burn the rate limit.
_TTL_SECONDS = 60.0


class IbovStockModel(BaseModel):
    cod: str
    nome: str
    peso: float
    var_pct: float | None
    contrib_pct: float | None


class IbovLevelModel(BaseModel):
    nivel: float
    sobe: int
    cai: int


class IbovResponse(BaseModel):
    """`carteira` is the date of the B3 portfolio the weights come from, so an
    old file is visible on screen instead of quietly wrong. `abertas` is how
    many of `universo` names the quote source answered for — a name missing a
    quote is left out of the counts rather than counted as flat."""

    carteira: str
    peso: float
    contrib_pct: float | None
    acoes: list[IbovStockModel]
    universo: int
    abertas: int
    pct_sobe: float | None
    niveis: list[IbovLevelModel]


_cache: tuple[float, IbovResponse] | None = None


# Rows of the breadth panel, in percent. Cumulative: the 1% row counts every
# name past 1%, so it includes the ones on the rows above it.
_LEVELS = (0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0)


def _build() -> IbovResponse:
    carteira, index = load_weights()
    changes = fetch_changes([stock.cod for stock in index])
    stocks = index[:TOP]
    moves = list(changes.values())
    niveis = [
        IbovLevelModel(
            nivel=level,
            sobe=sum(1 for move in moves if move > level),
            cai=sum(1 for move in moves if move < -level),
        )
        for level in _LEVELS
    ]
    up = niveis[0].sobe if niveis else 0
    down = niveis[0].cai if niveis else 0
    acoes = [
        IbovStockModel(
            cod=stock.cod,
            nome=stock.nome,
            peso=stock.peso,
            var_pct=changes.get(stock.cod),
            contrib_pct=(
                None if stock.cod not in changes else stock.peso * changes[stock.cod] / 100.0
            ),
        )
        for stock in stocks
    ]
    contributions = [a.contrib_pct for a in acoes if a.contrib_pct is not None]
    return IbovResponse(
        carteira=carteira,
        peso=round(sum(stock.peso for stock in stocks), 2),
        contrib_pct=round(sum(contributions), 3) if contributions else None,
        acoes=acoes,
        universo=len(index),
        abertas=len(changes),
        pct_sobe=round(100.0 * up / (up + down), 1) if up + down else None,
        niveis=niveis,
    )


@router.get("", response_model=IbovResponse)
async def ibov() -> IbovResponse:
    global _cache
    if _cache is not None and monotonic() - _cache[0] < _TTL_SECONDS:
        return _cache[1]
    payload = await anyio.to_thread.run_sync(_build)
    _cache = (monotonic(), payload)
    return payload
