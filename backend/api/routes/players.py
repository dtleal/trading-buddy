"""REST endpoint: Baleia / Banco / Sardinha read off the Profit tape.

Reading strategy: a background loop owns the parsing and the endpoint only
hands back the last snapshot it produced. Two reasons it is not done inside the
request:

- A cold start is expensive. The `.trd` is read over a bind mount from the
  Windows side, and a big WIN session (~200 MB, 9M prints) took ~50s the first
  time. No request should ever wait on that.
- The accumulators are plain mutable state. One loop touching them means no
  locking and no half-updated snapshot going out.

The loop reads at most `_SLICE_BYTES` per pass, so a cold start catches up over
a few seconds with flat memory instead of one huge allocation, and the tab
fills in as it goes (`loading` says so). After that each pass only sees what
Profit appended since the last one, which is a few kilobytes.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import anyio
from fastapi import APIRouter
from pydantic import BaseModel

from adapters.profit_tape import (
    TapeFile,
    archive_tape,
    find_tape_files,
    load_agents,
    read_trades,
)
from settings import get_settings
from use_cases.aggregate_players import PlayersAccumulator, PlayersSnapshot

logger = logging.getLogger(__name__)

# B3 trades and stamps its tape in São Paulo local time, so "is the tape live?"
# has to be asked in that clock, not the server's.
B3_TZ = ZoneInfo("America/Sao_Paulo")

# Per-pass read budget. Reading off the Windows bind mount is the slow part
# (~3 MB/s measured), so this is sized to roughly fill one poll interval:
# 32 MB ≈ 745k prints ≈ 2s, all of it in a worker thread.
_SLICE_BYTES = 32 * 1024 * 1024
_POLL_SECONDS = 3.0

router = APIRouter(prefix="/api/players", tags=["players"])


class PlayerModel(BaseModel):
    key: str
    label: str
    papel: str
    fonte: str
    saldo_rs: float
    saldo_recente_rs: float
    saldo: int
    saldo_recente: int
    volume: int
    volume_rs: float
    forca_pct: float
    agressao_pct: float
    lado: str


class AssetPlayersModel(BaseModel):
    asset: str
    symbol: str
    session: str
    first_trade: datetime | None
    last_trade: datetime | None
    trades: int
    contracts: int
    residual_rs: float
    last_price: float | None
    lag_seconds: int | None
    players: list[PlayerModel]
    series: list[dict[str, Any]]
    top_brokers: list[dict[str, Any]]
    stale: bool


class PlayersResponse(BaseModel):
    """`source` is empty when PROFIT_DATA_DIR is unset or the folder is gone —
    the tab renders an explicit "sem fonte" state instead of fake zeros.
    `loading` means the reader is still catching up with the session file, so
    the numbers are the day *so far* and will keep growing for a few seconds."""

    source: str
    loading: bool
    assets: list[AssetPlayersModel]


@dataclass
class _Reader:
    """Where we are inside one asset's tape file."""

    file: TapeFile
    offset: int
    accumulator: PlayersAccumulator
    pending_bytes: int = 0


_readers: dict[str, _Reader] = {}
_agents: dict[int, str] = {}
_snapshots: list[PlayersSnapshot] = []
_loading = True


def _read_once(
    profit_dir: Path, prefixes: tuple[str, ...], archive_dir: Path | None
) -> tuple[list[PlayersSnapshot], bool]:
    global _agents
    if not _agents:
        _agents = load_agents(profit_dir)
    now = datetime.now(B3_TZ).replace(tzinfo=None)
    snapshots: list[PlayersSnapshot] = []
    catching_up = False
    for prefix, tape in find_tape_files(profit_dir, prefixes).items():
        reader = _readers.get(prefix)
        if reader is None or reader.file.path != tape.path:
            reader = _Reader(file=tape, offset=0, accumulator=PlayersAccumulator())
            _readers[prefix] = reader
        trades, reader.offset, reader.pending_bytes = read_trades(
            tape.path, reader.offset, _SLICE_BYTES
        )
        if archive_dir is not None:
            archive_tape(tape, archive_dir)
        if trades:
            reader.accumulator.feed(trades)
        if reader.pending_bytes > 0:
            catching_up = True
        snapshots.append(
            reader.accumulator.snapshot(
                _agents, prefix, tape.symbol, tape.day.isoformat(), now
            )
        )
    return snapshots, catching_up


async def refresh_loop() -> None:
    """Owns the readers. Started from the app lifespan, cancelled on shutdown."""
    global _snapshots, _loading
    settings = get_settings()
    prefixes = tuple(p.strip().upper() for p in settings.players_assets.split(",") if p.strip())
    archive = Path(settings.players_archive_dir) if settings.players_archive_dir.strip() else None
    while True:
        directory = settings.profit_data_dir.strip()
        if directory and Path(directory).is_dir():
            try:
                _snapshots, _loading = await anyio.to_thread.run_sync(
                    _read_once, Path(directory), prefixes, archive
                )
            except Exception:  # a bad file must not kill the loop
                logger.exception("players: falha lendo o tape do Profit")
        await asyncio.sleep(_POLL_SECONDS)


@router.get("", response_model=PlayersResponse)
async def players() -> PlayersResponse:
    directory = get_settings().profit_data_dir.strip()
    if not directory or not Path(directory).is_dir():
        return PlayersResponse(source="", loading=False, assets=[])
    return PlayersResponse(
        source=directory,
        loading=_loading,
        assets=[AssetPlayersModel(**asdict(snapshot)) for snapshot in _snapshots],
    )
