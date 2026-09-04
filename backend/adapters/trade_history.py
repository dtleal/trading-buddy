"""Closed-trade history for the Performance tab.

The collector rebuilds every round-trip trade of the last N days from the
broker's DEAL history and pushes them on the `trade_history` message. This
store folds each push into what it already holds, keyed by the MT5 position id,
so:

- re-pushes of the same trades are idempotent (no duplicates),
- trades that fall out of the collector's window are KEPT — the history only
  grows, which is what a performance page wants,
- a backend restart doesn't lose the older trades: the whole set is written to
  one JSON file after each push and reloaded on construction.

`directory=None` keeps everything in memory (used by the tests).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from core.models import ClosedTrade

logger = logging.getLogger(__name__)

_FILE_NAME = "closed_trades.json"


class TradeHistory:
    """All closed trades known to the backend, newest last."""

    def __init__(self, directory: Path | None) -> None:
        self._dir = directory
        self._trades: dict[int, ClosedTrade] = {}
        self.currency: str | None = None
        self.balance: float = 0.0
        self.asof: str | None = None  # ISO timestamp of the last push
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._load()

    # --- write ---------------------------------------------------------------

    def merge(
        self,
        trades: list[ClosedTrade],
        *,
        balance: float | None = None,
        currency: str | None = None,
        asof: str | None = None,
    ) -> int:
        """Fold a push into the store. Returns how many trades were new."""
        new = 0
        for trade in trades:
            if trade.id not in self._trades:
                new += 1
            self._trades[trade.id] = trade  # latest wins (a re-read may correct swap)
        if balance is not None:
            self.balance = balance
        if currency:
            self.currency = currency
        if asof:
            self.asof = asof
        self._save()
        return new

    # --- read ----------------------------------------------------------------

    def snapshot(self) -> list[ClosedTrade]:
        """Every closed trade held, oldest first (by close time)."""
        return sorted(self._trades.values(), key=lambda t: (t.close_ts, t.id))

    # --- persistence ---------------------------------------------------------

    def _path(self) -> Path:
        assert self._dir is not None
        return self._dir / _FILE_NAME

    def _load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for item in raw.get("trades", ()):
                trade = ClosedTrade.model_validate(item)
                self._trades[trade.id] = trade
            self.balance = float(raw.get("balance", 0.0) or 0.0)
            self.currency = raw.get("currency") or None
            self.asof = raw.get("asof") or None
        except Exception as exc:  # corrupt file — start empty rather than crash
            logger.warning("closed-trade history load failed (%s): %s", path, exc)

    def _save(self) -> None:
        if self._dir is None:
            return
        payload = {
            "balance": self.balance,
            "currency": self.currency,
            "asof": self.asof,
            "trades": [t.model_dump(mode="json") for t in self.snapshot()],
        }
        path = self._path()
        tmp = path.with_suffix(".json.tmp")
        try:
            # Write-then-rename so a crash mid-write can't truncate the history.
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:  # never let persistence break ingest
            logger.warning("closed-trade history save failed: %s", exc)
