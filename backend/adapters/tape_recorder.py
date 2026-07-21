"""Append-only JSONL recorder for the raw order-flow ingest stream.

Purpose: make the scalper backtestable. The collector's messages are recorded
verbatim (in arrival order) so a whole session can later be replayed through
the same aggregator + scalper code that ran live, reproducing the exact
snapshots the bot saw. Without this file there is no historical tape at all —
MT5 CFD feeds can't rewind synthesized ticks.

Only data messages are kept (see _RECORDED_TYPES): command echoes and the live
position/P&L mirrors are execution-state, which a replay simulates itself.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)

# The replayable data stream: quotes/DOM, tape prints and the liquidity gauge
# (the entry gate reads it). hello is kept so a replay knows the feed/broker.
_RECORDED_TYPES = {"hello", "book", "trade", "trades", "liquidity"}


class TapeRecorder:
    """Appends raw collector messages to one JSONL file per UTC day.

    Line format: ``{"rx": "<UTC ISO>", "msg": <message verbatim>}`` — ``rx`` is
    the backend's receive time, kept alongside the collector's own timestamps
    so clock skew is visible in the recording.

    Files roll at the UTC day boundary (``tape-YYYY-MM-DD.jsonl``). Line
    buffering keeps every print on disk even if the process dies mid-session.
    A write failure (disk full, bad mount) pauses recording until the next UTC
    day instead of logging once per message — recording must never break or
    spam the live ingest stream.
    """

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._day: str | None = None
        self._file: TextIO | None = None
        self._failed_day: str | None = None

    def record(self, msg: dict[str, Any]) -> None:
        if msg.get("type") not in _RECORDED_TYPES:
            return
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        if day == self._failed_day:
            return
        try:
            if self._file is None or day != self._day:
                self._roll(day)
            assert self._file is not None
            line = json.dumps({"rx": now.isoformat(), "msg": msg}, separators=(",", ":"))
            self._file.write(line + "\n")
        except Exception:
            logger.exception("Tape recording failed — paused until the next UTC day")
            self._failed_day = day
            self.close()

    def _roll(self, day: str) -> None:
        self.close()
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"tape-{day}.jsonl"
        self._file = path.open("a", buffering=1, encoding="utf-8")
        self._day = day
        logger.info("Recording order-flow tape to %s", path)

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:  # pragma: no cover - close on a dead handle
                pass
        self._file = None
        self._day = None


__all__ = ["TapeRecorder"]
