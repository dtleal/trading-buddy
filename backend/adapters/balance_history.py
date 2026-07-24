"""Account balance/equity data for the UI balance chart.

Two time-lines, from two collector messages:

- **balance steps** (`balance_history` message) — the per-trade balance curve,
  reconstructed from the broker's DEAL history (all closed trades of the month,
  manual + bot). Replaced wholesale on each push (it's cheap to re-derive and
  always authoritative), so no persistence is needed.
- **equity samples** (`account_pnl` message) — live equity, forward-only,
  sampled every ~30s. Persisted to a per-UTC-day JSONL so the intraday equity
  wiggle survives a backend restart. Idle samples (unchanged) are coalesced.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.models import BalanceStep, EquityPoint

logger = logging.getLogger(__name__)

_MAXLEN = 5760  # ~2 days of equity at one sample / 30s
_ANCHOR_SECONDS = 300.0  # keep >=1 equity point per 5 min even when idle
_EPS = 0.01  # money resolution: below this, treat equity as unchanged


class BalanceHistory:
    """Balance steps (in-memory, replaced per push) + equity samples (persisted).

    `directory=None` disables equity persistence (in-memory only). On construction
    it reloads yesterday's + today's equity files so the line isn't empty on boot.
    """

    def __init__(self, directory: Path | None, maxlen: int = _MAXLEN) -> None:
        self._dir = directory
        self._equity: deque[EquityPoint] = deque(maxlen=maxlen)
        self._steps: list[BalanceStep] = []
        self.currency: str | None = None
        self.balance: float = 0.0
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._load_recent()

    # --- balance steps (deal-history reconstruction) ------------------------

    def set_steps(self, steps: list[BalanceStep], balance: float, currency: str | None) -> None:
        """Replace the per-trade balance curve (latest push wins)."""
        self._steps = steps
        self.balance = balance
        if currency:
            self.currency = currency

    # --- equity samples (live, forward-only) --------------------------------

    def record_equity(
        self, balance: float, equity: float, currency: str | None, ts: datetime
    ) -> None:
        """Append a live equity sample, coalescing idle (unchanged) ones. Also
        refreshes the latest balance so the header is fresh before the first
        `balance_history` push arrives."""
        if currency:
            self.currency = currency
        self.balance = balance
        last = self._equity[-1] if self._equity else None
        if last is not None:
            unchanged = abs(last.equity - equity) < _EPS
            fresh = (ts - last.ts).total_seconds() < _ANCHOR_SECONDS
            if unchanged and fresh:
                return
        point = EquityPoint(ts=ts, equity=equity)
        self._equity.append(point)
        self._append_disk(point)

    # --- persistence (equity only) ------------------------------------------

    def _file_for(self, ts: datetime) -> Path:
        assert self._dir is not None
        return self._dir / f"equity-{ts.strftime('%Y%m%d')}.jsonl"

    def _load_recent(self) -> None:
        now = datetime.now(timezone.utc)
        for day in (now - timedelta(days=1), now):
            path = self._file_for(day)
            if not path.exists():
                continue
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    raw = json.loads(line)
                    self._equity.append(
                        EquityPoint(
                            ts=datetime.fromisoformat(raw["ts"]),
                            equity=float(raw["equity"]),
                        )
                    )
            except Exception as exc:  # corrupt / partial line — best effort
                logger.warning("equity history load failed (%s): %s", path, exc)

    def _append_disk(self, point: EquityPoint) -> None:
        if self._dir is None:
            return
        try:
            line = json.dumps({"ts": point.ts.isoformat(), "equity": point.equity})
            with self._file_for(point.ts).open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # never let persistence break ingest
            logger.warning("equity history append failed: %s", exc)

    # --- read ----------------------------------------------------------------

    def snapshot(self) -> tuple[list[BalanceStep], list[EquityPoint]]:
        return list(self._steps), list(self._equity)
