"""Unit tests for the raw order-flow tape recorder (backtest input).

The recorder feeds the scalper's replay/backtest pipeline, so what matters is
pinned here: data messages land verbatim as JSONL, non-data messages are
skipped, and a write failure pauses recording instead of breaking the caller.
"""

from __future__ import annotations

import json
from pathlib import Path

from adapters.tape_recorder import TapeRecorder


def _lines(directory: Path) -> list[dict]:
    files = sorted(directory.glob("tape-*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text().splitlines()]


def test_records_data_messages_verbatim(tmp_path: Path) -> None:
    rec = TapeRecorder(tmp_path)
    msg = {"type": "trades", "symbol": "USTEC", "trades": [{"price": 20000.5}]}
    rec.record(msg)
    rec.close()

    (line,) = _lines(tmp_path)
    assert line["msg"] == msg
    assert "rx" in line  # backend receive time stamped alongside


def test_skips_non_data_messages(tmp_path: Path) -> None:
    rec = TapeRecorder(tmp_path)
    rec.record({"type": "positions", "symbol": "USTEC", "positions": []})
    rec.record({"type": "open_result", "ok": True})
    rec.record({"type": "account_pnl", "day": 1.0})
    rec.close()

    assert list(tmp_path.glob("*.jsonl")) == []


def test_appends_in_arrival_order(tmp_path: Path) -> None:
    rec = TapeRecorder(tmp_path)
    rec.record({"type": "hello", "source": "FTMO"})
    rec.record({"type": "book", "symbol": "GOLD", "bids": [], "asks": []})
    rec.record({"type": "liquidity", "symbol": "GOLD", "ratio": 1.2})
    rec.close()

    kinds = [line["msg"]["type"] for line in _lines(tmp_path)]
    assert kinds == ["hello", "book", "liquidity"]


def test_write_failure_pauses_instead_of_raising(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("")  # a FILE where the recorder expects its directory
    rec = TapeRecorder(blocker / "sub")

    rec.record({"type": "book", "symbol": "USTEC", "bids": [], "asks": []})  # must not raise
    rec.record({"type": "book", "symbol": "USTEC", "bids": [], "asks": []})  # paused, silent
    assert rec._failed_day is not None
