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
import json
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
    append_trades,
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
    aggressions: list[dict[str, Any]]
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
    """Where we are inside one asset's tape file, and inside our own recording.

    Two files, read in that order: Profit's `.trd` holds the session up to the
    moment the Times & Trades window opened, and our recording holds what the
    live feed saw after that (see `_record_path`). Both are tailed by offset,
    so a poll only parses what was appended since the last one.
    """

    file: TapeFile
    # Session the accumulator stands for. Normally the file's own day; today's
    # date when the newest file is old and our recording is all there is.
    day: date
    offset: int
    accumulator: PlayersAccumulator
    pending_bytes: int = 0
    record_offset: int = 0
    record_pending: int = 0
    # A brand new reader has read nothing yet, and "nothing read" looks exactly
    # like "nothing left to read". The live feed must not adopt an accumulator
    # that is empty only because the first pass has not run, so the reader is
    # born busy and clears the flag once a pass has been through it.
    read_once: bool = False

    @property
    def busy(self) -> bool:
        """True while either file still has bytes we have not read."""
        return not self.read_once or self.pending_bytes > 0 or self.record_pending > 0


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
        # Which session to build: Profit's file when it is from today, and
        # otherwise our own recording — a file from last week next to prints
        # recorded this morning means the window was never reopened, so the
        # recording is the only account of today there is.
        day = _session_day(prefix, tape, now.date())
        reader = _readers.get(prefix)
        if reader is None or reader.file.path != tape.path or reader.day != day:
            reader = _Reader(file=tape, day=day, offset=0, accumulator=PlayersAccumulator(prefix))
            _readers[prefix] = reader
        if reader.day == tape.day:
            trades, reader.offset, reader.pending_bytes = read_trades(
                tape.path, reader.offset, _SLICE_BYTES
            )
            if trades:
                reader.accumulator.feed(trades)
        if archive_dir is not None:
            archive_tape(tape, archive_dir)
        if reader.pending_bytes == 0 and reader.day == now.date():
            _replay_record(prefix, reader)
        reader.read_once = True
        if reader.busy:
            catching_up = True
        snapshots.append(
            reader.accumulator.snapshot(_agents, prefix, tape.symbol, reader.day.isoformat(), now)
        )
    return snapshots, catching_up


def _session_day(prefix: str, tape: TapeFile, today: date) -> date:
    """The day the reader should build: the tape's, or today's when only our
    recording has today in it."""
    if tape.day == today:
        return today
    path = _record_path(prefix, today)
    return today if path is not None and path.exists() else tape.day


def _record_path(prefix: str, day: date) -> Path | None:
    """Our own recording of one session, or None when recording is off."""
    directory = get_settings().players_live_dir.strip()
    return Path(directory) / f"{prefix}_{day.isoformat()}.trd" if directory else None


def _replay_record(prefix: str, reader: _Reader) -> None:
    """Fold our recording of the live feed back in, on top of the file.

    Profit stops writing the `.trd` right after the Times & Trades window
    opens, so a backend started at 14h reads a file that ends at 10h and the
    middle of the day would simply be missing. The recording holds exactly that
    gap (`_feed_live` writes it), and reading it here — in the reader's own
    thread, right behind the file — means the live feed later adopts a session
    that already runs up to the last print seen before the restart.

    Prints at or before what the file already counted are dropped, the same
    seam rule the live feed uses for its own first batch.
    """
    path = _record_path(prefix, reader.day)
    if path is None:
        return
    trades, reader.record_offset, reader.record_pending = read_trades(
        path, reader.record_offset, _SLICE_BYTES
    )
    cut = reader.accumulator.last_trade
    fresh = [trade for trade in trades if cut is None or trade.at > cut]
    if fresh:
        reader.accumulator.feed(fresh)
        logger.info(
            "%s: %d negocios recuperados da gravacao (ate %s)",
            prefix,
            len(fresh),
            reader.accumulator.last_trade,
        )


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


class PlayersTickModel(BaseModel):
    """The three numbers that move on every print. Everything else on the card
    (series, corretoras, os saldos por grupo) changes slowly enough to ride the
    full poll."""

    asset: str
    last_price: float | None
    last_trade: datetime | None
    trades: int


# How often the stream looks for something new. The collector lands a print
# ~100ms after it happened, so looking faster would only find the same numbers.
_STREAM_SECONDS = 0.1


def _ticks() -> list[PlayersTickModel]:
    """Price and print count per contract, straight off the accumulators. The
    live feed wins over the file for the same contract, same rule as the card."""
    ticks = [
        PlayersTickModel(
            asset=prefix,
            last_price=state.accumulator.last_price,
            last_trade=state.accumulator.last_trade,
            trades=state.accumulator.trades,
        )
        for prefix, state in _live.items()
        if state.seeded
    ]
    seen = {item.asset for item in ticks}
    ticks.extend(
        PlayersTickModel(
            asset=snapshot.asset,
            last_price=snapshot.last_price,
            last_trade=snapshot.last_trade,
            trades=snapshot.trades,
        )
        for snapshot in _snapshots
        if snapshot.asset not in seen
    )
    ticks.sort(key=lambda item: item.asset)
    return ticks


@router.websocket("/ws/tick")
async def tick_stream(websocket: WebSocket) -> None:
    """Streams the price to the browser instead of being asked for it.

    The card used to poll, and a poll can only be as fresh as its interval —
    at 3s the price visibly trailed the Profit window, and asking ten times a
    second to fix that is a request per print. Here the socket stays open and
    the payload goes out when it changes, which is the shape the rest of the
    live data already uses (see the order-flow channel).

    Only the three fields that move on every print travel this way. The series,
    the corretoras and the group totals keep riding the full REST read, which
    changes slowly enough for it.
    """
    await websocket.accept()
    last: str | None = None
    try:
        while True:
            payload = json.dumps([item.model_dump(mode="json") for item in _ticks()])
            if payload != last:
                await websocket.send_text(payload)
                last = payload
            await asyncio.sleep(_STREAM_SECONDS)
    except WebSocketDisconnect:
        return


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
    not_ready = reader is None or reader.busy
    if not_ready and len(live.pending) < _MAX_PENDING and monotonic() < live.deadline:
        return  # the reader is still working on this contract; keep holding
    live.seeded = True
    if reader is None or reader.busy or reader.day != live.day:
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
        live = _Live(symbol=symbol, day=today, accumulator=PlayersAccumulator(prefix))
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
        path = _record_path(prefix, live.day)
        if path is not None:
            # Only what was actually counted goes to disk, so reading the file
            # back is the same as having received the batch again.
            append_trades(path, trades)


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
