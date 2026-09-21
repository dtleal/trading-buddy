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
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from adapters.profit_rtd import multiplier_for, name_to_code, parse_trade
from adapters.profit_tape import (
    TapeFile,
    Trade,
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
    live: bool


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


@dataclass
class _Live:
    """One asset fed by the RTD collector instead of by the file.

    `cut` is the timestamp the file reader had already reached when the live
    feed took over. The RTD window carries the last 500 prints, so the first
    batch is partly stuff the file already counted; anything at or before the
    cut is dropped so the session is not counted twice at the seam.
    """

    symbol: str
    day: date
    accumulator: PlayersAccumulator
    cut: datetime | None = None
    dropped: int = 0
    duplicates: int = 0
    # Set once the session the file already read has been adopted (or given up
    # on). Until then prints wait in `pending` instead of being counted, so the
    # two sources are never mixed in the wrong order.
    seeded: bool = False
    pending: list[Trade] = field(default_factory=list)
    # Hard stop on the wait: if the file never shows up, the tab still fills.
    deadline: float = field(default_factory=lambda: monotonic() + _SEED_TIMEOUT)


_readers: dict[str, _Reader] = {}
_agents: dict[int, str] = {}
_codes: dict[str, int] = {}
_live: dict[str, _Live] = {}
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
        if prefix in _live and _live[prefix].seeded:
            # The RTD collector owns this contract now, and its numbers are the
            # ones on screen. Parsing the file anyway costs a 32 MB read every
            # 3s for a snapshot nobody looks at, and that read is heavy enough
            # to stall the event loop — which showed up as the ingest socket
            # timing out while the collector was mid-send.
            continue
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
            reader.accumulator.snapshot(_agents, prefix, tape.symbol, tape.day.isoformat(), now)
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


def _model(snapshot: PlayersSnapshot, live: bool) -> AssetPlayersModel:
    """Snapshot to wire model. `live` says the numbers came from the RTD feed."""
    return AssetPlayersModel(**asdict(snapshot), live=live)


@router.get("", response_model=PlayersResponse)
async def players() -> PlayersResponse:
    directory = get_settings().profit_data_dir.strip()
    if not directory or not Path(directory).is_dir():
        return PlayersResponse(source="", loading=False, assets=[])
    now = datetime.now(B3_TZ).replace(tzinfo=None)
    # The live feed wins over the file for the same contract: the file stopped
    # growing the moment Profit finished its download, so mixing them would
    # show a stale number next to a fresh one on the same screen.
    # Only a seeded contract is served live: until the file reader hands over,
    # its prints are still waiting in the buffer and the file snapshot is the
    # one with real numbers in it.
    ready = {prefix: live for prefix, live in _live.items() if live.seeded}
    assets = [
        _model(
            live.accumulator.snapshot(_agents, prefix, live.symbol, live.day.isoformat(), now),
            live=True,
        )
        for prefix, live in ready.items()
    ]
    assets.extend(
        _model(snapshot, live=False) for snapshot in _snapshots if snapshot.asset not in ready
    )
    assets.sort(key=lambda asset: asset.asset)
    return PlayersResponse(
        source=directory,
        loading=_loading and not ready,
        assets=assets,
    )


# --- ingest (RTD collector → backend) ---------------------------------------


@router.websocket("/ws/ingest/b3tape")
async def ingest_b3_tape(websocket: WebSocket) -> None:
    """Receive live B3 prints from the Profit RTD collector.

    Auth: ``?token=<ORDERFLOW_INGEST_TOKEN>`` — the same secret as the MT5
    ingest, because it is the same machine on the same LAN and a second secret
    would only be one more thing to get wrong.
    """
    global _agents, _codes
    token = get_settings().orderflow_ingest_token
    if token is None or websocket.query_params.get("token", "") != token.get_secret_value():
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("B3 tape ingest recusado: token ausente ou errado")
        return
    directory = get_settings().profit_data_dir.strip()
    if not directory or not Path(directory).is_dir():
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("B3 tape ingest recusado: PROFIT_DATA_DIR nao aponta pra pasta do Profit")
        return

    if not _agents:
        _agents = load_agents(Path(directory))
    if not _codes:
        _codes = name_to_code(_agents)

    await websocket.accept()
    logger.info("Collector RTD conectado: %s", websocket.client)
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "b3_trades":
                continue
            _feed_live(message)
    except WebSocketDisconnect:
        logger.info("Collector RTD desconectado: %s", websocket.client)
    except Exception:
        logger.exception("B3 tape ingest quebrou para %s", websocket.client)
        try:
            await websocket.close(code=1011)
        except Exception:  # pragma: no cover - already closed
            pass


# How long the live feed waits for its contract's file before giving up.
_SEED_TIMEOUT = 180.0

# Cap on prints held while the file reader finishes. A 200 MB WIN cold start
# took ~50s, which at the busiest measured pace is well under this; past it the
# seed is not worth the memory and the live feed starts on its own.
_MAX_PENDING = 400_000


def _try_seed(prefix: str, live: _Live) -> None:
    """Adopt the session the file reader already parsed, once it is done.

    The collector only knows the last 500 prints, so a session it joins at
    10:30 would otherwise show "the day" starting at 10:30. The file does not
    have that problem: Profit downloads the session up to the moment the Times
    & Trades window opens, and the reader parses all of it at startup. So the
    live feed adopts that accumulator and carries on from its last print.

    While the reader is still working, prints wait in `pending` rather than
    being counted — the socket keeps being drained either way, which an earlier
    version got wrong by making the handler wait and timing the collector out.

    Skipped when the file is from another day: yesterday's totals under today's
    label would be worse than an honest late start, which the tab already shows
    as a later "first trade".
    """
    reader = _readers.get(prefix)
    not_ready = reader is None or reader.pending_bytes > 0
    if not_ready and len(live.pending) < _MAX_PENDING and monotonic() < live.deadline:
        return  # the reader is still working on this contract; keep holding
    live.seeded = True
    if reader is None or reader.pending_bytes > 0 or reader.file.day != live.day:
        logger.info("%s: ao vivo comeca do zero (sem arquivo de hoje)", prefix)
        return
    live.accumulator = reader.accumulator
    live.cut = reader.accumulator.last_trade
    logger.info(
        "%s: ao vivo continua do arquivo (%d negocios ate %s)",
        prefix,
        reader.accumulator.trades,
        live.cut,
    )


def _feed_live(message: dict[str, Any]) -> None:
    """Parse one batch and push it into the contract's accumulator."""
    symbol = str(message.get("asset", "")).upper()
    multiplier = multiplier_for(symbol)
    if multiplier is None:
        return  # a window on something other than WIN/WDO: not this tab's business
    prefix = symbol[:3]
    today = datetime.now(B3_TZ).date()
    live = _live.get(prefix)
    if live is None or live.day != today or live.symbol != symbol:
        # A new session (or a contract roll) starts from zero — carrying
        # yesterday's totals into today would be worse than showing nothing.
        live = _Live(symbol=symbol, day=today, accumulator=PlayersAccumulator())
        _live[prefix] = live

    trades = []
    rejected: dict[str, object] | None = None
    for raw in message.get("trades", []):
        trade = parse_trade(raw, live.day, multiplier, _codes)
        if trade is None:
            live.dropped += 1
            rejected = raw
        else:
            trades.append(trade)

    if not live.seeded:
        live.pending.extend(trades)
        _try_seed(prefix, live)
        if not live.seeded:
            return
        trades = live.pending
        live.pending = []
    if live.cut is not None:
        kept = [t for t in trades if t.at > live.cut]
        live.duplicates += len(trades) - len(kept)
        trades = kept

    if rejected is not None:
        # A dropped print is silent on screen — the tab just shows a smaller
        # number — so the log has to carry an actual rejected row. On day one
        # this is what says whether the aggressor column or a broker name is
        # spelled differently from what the parser expects.
        _warn_dropped(prefix, live.dropped, rejected)
    if trades:
        live.accumulator.feed(trades)


# One line per contract per minute: at 8.900 prints/s a per-print log would
# drown the container and hide the very thing it is there to show.
_DROP_LOG_SECONDS = 60.0
_last_drop_log: dict[str, float] = {}


def _warn_dropped(prefix: str, total: int, sample: dict[str, object]) -> None:
    now = monotonic()
    if now - _last_drop_log.get(prefix, 0.0) < _DROP_LOG_SECONDS:
        return
    _last_drop_log[prefix] = now
    logger.warning(
        "%s: %d negocios descartados no ao vivo; exemplo do que nao foi lido: %r",
        prefix,
        total,
        sample,
    )
