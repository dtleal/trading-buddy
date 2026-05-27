"""Push fresh breakout signals to the user's phone via ntfy.sh.

Dedup strategy:
- Redis key `ntfy:pushed:breakouts` is a Set of Breakout.id strings.
- 24h TTL refresh on every push — keeps the set bounded.
- On first start, primes with breakouts older than `freshness_minutes`
  so a fresh container/restart does NOT spam the user with a day's
  worth of historic signals.

The pushed-id store lives in Redis (not in memory) so a backend restart
or container rebuild does not re-spam the user.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from adapters.ntfy_notifier import NtfyNotifier
from core.interfaces import CacheStore
from core.models import Breakout

logger = logging.getLogger(__name__)

CACHE_KEY = "ntfy:pushed:breakouts"
CACHE_TTL_SECONDS = 24 * 3600
DEFAULT_FRESHNESS_MINUTES = 5


class PushBreakoutAlertsUseCase:
    """Decides which breakouts to push and fires them via the notifier."""

    def __init__(
        self,
        notifier: NtfyNotifier,
        cache: CacheStore,
        *,
        freshness_minutes: int = DEFAULT_FRESHNESS_MINUTES,
    ) -> None:
        self._notifier = notifier
        self._cache = cache
        self._freshness_minutes = freshness_minutes
        self._primed = False

    async def execute(self, breakouts: list[Breakout]) -> int:
        """Push any breakout we have not seen yet. Returns the count pushed."""
        if not self._notifier.enabled or not breakouts:
            return 0

        pushed_ids = await self._load_pushed_ids()

        # First run after backend boot: silently mark stale signals as pushed.
        # Anything fresh (within freshness window) still alerts the user —
        # matches the frontend hook's behavior for consistency.
        if not self._primed:
            cutoff_ms = self._freshness_minutes * 60_000
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            stale_ids = {
                b.id for b in breakouts if (now_ms - b.signal_bar_at.timestamp() * 1000) > cutoff_ms
            }
            if stale_ids:
                pushed_ids = pushed_ids | stale_ids
                await self._save_pushed_ids(pushed_ids)
            self._primed = True

        # Fire on the newest first so the most recent signal arrives first.
        to_push = sorted(
            (b for b in breakouts if b.id not in pushed_ids),
            key=lambda b: b.signal_bar_at,
        )

        sent = 0
        for breakout in to_push:
            ok = await self._notifier.push(
                title=_title(breakout),
                message=_body(breakout),
                priority=_priority(breakout),
                tags=_tags(breakout),
            )
            if ok:
                pushed_ids.add(breakout.id)
                sent += 1

        if sent > 0:
            await self._save_pushed_ids(pushed_ids)
            logger.info("ntfy: pushed %d breakout alert(s)", sent)
        return sent

    async def _load_pushed_ids(self) -> set[str]:
        raw = await self._cache.get(CACHE_KEY)
        if not raw:
            return set()
        # Stored as a newline-separated list — simpler than picking JSON for
        # what is essentially a string set.
        return {line.strip() for line in raw.splitlines() if line.strip()}

    async def _save_pushed_ids(self, ids: set[str]) -> None:
        if not ids:
            return
        # Cap the stored set so it never grows unbounded across long-lived
        # backends. 1000 ids is months of breakouts.
        capped = list(ids)
        if len(capped) > 1000:
            capped = capped[-1000:]
        await self._cache.set(CACHE_KEY, "\n".join(capped), ttl_seconds=CACHE_TTL_SECONDS)


# -------- message formatters --------


# Direction labels are intentionally explicit: phone-notification UX is
# scanned in a hurry, so we lead with COMPRA/VENDA rather than a tiny arrow
# that could be confused.
_SIDE_LABEL = {"up": "COMPRA", "down": "VENDA"}
_SIDE_EMOJI = {"up": "🟢", "down": "🔴"}
_BREAKOUT_LABEL = {"up": "Rompimento de ALTA", "down": "Rompimento de BAIXA"}
_TAG_ARROW = {"up": "chart_with_upwards_trend", "down": "chart_with_downwards_trend"}


def _title(b: Breakout) -> str:
    # Lead with COMPRA/VENDA so the lock-screen banner is unambiguous.
    return (
        f"{_SIDE_EMOJI[b.direction.value]} {_SIDE_LABEL[b.direction.value]} · "
        f"{b.asset.value} {b.timeframe.value} @ {b.close:.2f}"
    )


def _body(b: Breakout) -> str:
    side = b.direction.value
    above_below = "acima de" if side == "up" else "abaixo de"
    parts = [
        f"{_BREAKOUT_LABEL[side]} — fechou {above_below} {b.level:.2f}",
        f"Expansao: {b.expansion_ratio:.2f}x ATR",
        f"Strength: {b.strength:.0f}/100",
    ]
    if b.squeeze:
        parts.append("Pos-squeeze (alta qualidade)")
    parts.append(f"Bar: {b.signal_bar_at.strftime('%H:%M UTC')}")
    return " | ".join(parts)


def _priority(b: Breakout) -> int:
    # Map strength score → ntfy priority (1=min, 5=max/urgent).
    if b.strength >= 90:
        return 5
    if b.strength >= 70:
        return 4
    if b.strength >= 50:
        return 3
    return 2


def _tags(b: Breakout) -> list[str]:
    return [_TAG_ARROW[b.direction.value], b.asset.value.lower()]
