"""Reads the Nelogica Profit local tape (`.trd`) — B3 times & trades with the
broker code on both sides of every print.

Why this file exists: B3 is the only feed we have that names *who* traded.
Profit stores every print it received on disk, and each record carries the
buying broker, the selling broker and the trade type. That is what makes the
Baleia/Banco/Sardinha split real data instead of a guess from lot sizes.

Record layout (45 bytes, no header, little-endian) — decoded and checked
against a full session (534,719 prints, zero leftover bytes, every broker code
resolving against `newagents.dat`):

    0-7    double   Delphi TDateTime (days since 1899-12-30, already to the ms)
    8-11   uint32   sequence number, steps of 10 within the session
    12-19  double   price
    20-23  uint32   quantity (contracts)
    24-27  uint32   unused so far (always 0)
    28-35  double   financial volume in BRL (already carries B3's multiplier:
                    ×10 for WDO, ×0,20 for WIN — checked against live prints)
    36-39  uint32   buying broker code
    40-43  uint32   selling broker code
    44     uint8    trade type

Trade types seen: 2 = buy aggression, 3 = sell aggression, 4 = auction,
13 = RLP, 1 = broker crossing its own orders ("direto").

RLP matters most. It is B3's Retail Liquidity Provider mechanism: the broker
itself is the counterparty to its own *retail* client's order. Both sides of an
RLP print carry the same broker code (verified: 100% of 119,270 prints), and
the rule only covers retail. So an RLP print is retail flow by regulation, not
by our reading of who the broker is.

The file only holds what Profit downloaded while it was open. A short session
gives a short file; that is not an error, and `stale` on the snapshot says so.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RECORD = struct.Struct("<dIdIIdIIB")
RECORD_SIZE = RECORD.size  # 45

# Delphi epoch: TDateTime 0 is 1899-12-30.
_DELPHI_EPOCH = datetime(1899, 12, 30)

TYPE_BUY_AGGRESSION = 2
TYPE_SELL_AGGRESSION = 3
TYPE_AUCTION = 4
TYPE_RLP = 13
TYPE_CROSS = 1


@dataclass(frozen=True, slots=True)
class Trade:
    at: datetime
    seq: int
    price: float
    qty: int
    financial: float  # BRL for the whole print, straight from the file
    buyer: int
    seller: int
    kind: int


@dataclass(frozen=True, slots=True)
class TapeFile:
    """One `.trd` on disk: which asset it belongs to and which session day."""

    path: Path
    symbol: str  # contract as Profit names it, e.g. "WDOV26"
    day: date


def load_agents(profit_dir: Path) -> dict[int, str]:
    """Broker code -> short name, from Profit's own `newagents.dat`.

    Line format: ``code:legal name:short name:date:flag:markets``. The first
    line is a timestamp comment. Anything unparseable is skipped rather than
    raising — a bad line must not take the whole tab down.
    """
    table: dict[int, str] = {}
    path = profit_dir / "newagents.dat"
    try:
        raw = path.read_text(encoding="latin-1")
    except OSError as exc:
        logger.warning("broker table unreadable at %s: %s", path, exc)
        return table
    for line in raw.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        table[int(parts[0])] = parts[2]
    return table


def find_tape_files(profit_dir: Path, prefixes: tuple[str, ...]) -> dict[str, TapeFile]:
    """Newest `.trd` per asset prefix (e.g. "WDO", "WIN").

    Profit keeps one folder per contract (`WDOV26_F_0`) and one file per
    session inside it. Contracts roll, so we pick by session day across every
    folder that starts with the prefix instead of hardcoding the contract.
    """
    assets = profit_dir / "database" / "assets"
    newest: dict[str, TapeFile] = {}
    if not assets.is_dir():
        logger.warning("Profit assets folder not found at %s", assets)
        return newest
    for prefix in prefixes:
        for folder in assets.glob(f"{prefix}*_F_0"):
            symbol = folder.name.removesuffix("_F_0")
            for file in folder.glob("*.trd"):
                stamp = file.stem.rsplit("_", 1)[-1]
                if len(stamp) != 8 or not stamp.isdigit():
                    continue
                day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
                current = newest.get(prefix)
                if current is None or day > current.day:
                    newest[prefix] = TapeFile(path=file, symbol=symbol, day=day)
    return newest


def archive_tape(tape: TapeFile, archive_dir: Path) -> None:
    """Keep our own copy of a session tape, refreshed while it still grows.

    Profit only writes the sessions whose Times & Trades window was opened, and
    a contract roll leaves the old folder sitting there until it is cleaned up.
    The tape is the only raw material for testing whether trading against the
    retail flow pays, so losing a day is losing a day that cannot be recovered.

    Copying is skipped whenever our copy is already the same size, which is the
    common case — a session file changes a couple of times a day, not every
    poll.
    """
    try:
        source_size = tape.path.stat().st_size
    except OSError:
        return
    target = archive_dir / f"{tape.symbol}_{tape.day.isoformat()}.trd"
    try:
        if target.exists() and target.stat().st_size >= source_size:
            return
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Write beside the target first so a crash mid-copy never leaves a
        # truncated file looking like a complete session.
        staging = target.with_suffix(".part")
        staging.write_bytes(tape.path.read_bytes())
        staging.replace(target)
        logger.info("tape arquivado: %s (%s bytes)", target.name, source_size)
    except OSError as exc:
        logger.warning("nao consegui arquivar %s: %s", tape.path.name, exc)


def read_trades(
    path: Path, offset: int = 0, max_bytes: int | None = None
) -> tuple[list[Trade], int, int]:
    """Parse from `offset` onwards. Returns trades, the new offset and how many
    bytes are still unread.

    The offset lets a caller re-read only what Profit appended since the last
    poll, which is what keeps the live path cheap: a full session is 24 MB, a
    5-second slice is a few kilobytes. A partial record at the end of the file
    (Profit mid-write) is left for the next read.

    `max_bytes` caps one call. It matters on a cold start: a big WIN session is
    ~200 MB / 9M prints, and turning all of that into objects at once would
    blow past a sane memory budget and freeze the loop for a minute. Reading it
    in slices keeps memory flat and lets the tab fill in as it catches up.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset, 0
    if size < offset:  # file was replaced (new session) — start over
        offset = 0
    usable = ((size - offset) // RECORD_SIZE) * RECORD_SIZE
    if max_bytes is not None:
        usable = min(usable, (max_bytes // RECORD_SIZE) * RECORD_SIZE)
    if usable <= 0:
        return [], offset, 0
    with path.open("rb") as handle:
        handle.seek(offset)
        blob = handle.read(usable)
    trades = [
        Trade(
            at=_DELPHI_EPOCH + timedelta(days=stamp),
            seq=seq,
            price=price,
            qty=qty,
            financial=financial,
            buyer=buyer,
            seller=seller,
            kind=kind,
        )
        for stamp, seq, price, qty, _unused, financial, buyer, seller, kind in RECORD.iter_unpack(blob)
    ]
    new_offset = offset + usable
    return trades, new_offset, max(0, size - new_offset - (size - new_offset) % RECORD_SIZE)
