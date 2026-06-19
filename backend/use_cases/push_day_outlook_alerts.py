"""Push the daily "Perfil do Dia" verdict to the user's phone via ntfy.sh.

Fires at most once per UTC day, on the first tick that produces a non-NORMAL
outlook (the trader only needs the heads-up when the day is unusually thin or
unusually expansive — an ordinary day is the silent default). Dedup is keyed on
the UTC date in Redis so a backend restart mid-day does not re-spam.

Never raises — a push outage must not break the tick loop.
"""

from __future__ import annotations

import logging

from adapters.ntfy_notifier import NtfyNotifier
from core.enums import DayRegime
from core.interfaces import CacheStore
from core.models import DayOutlook

logger = logging.getLogger(__name__)

CACHE_KEY = "ntfy:pushed:day_outlook"  # value = last pushed UTC date (YYYY-MM-DD)
CACHE_TTL_SECONDS = 36 * 3600  # comfortably longer than a day


class PushDayOutlookAlertsUseCase:
    """Decides whether to push today's day-outlook and fires it."""

    def __init__(self, notifier: NtfyNotifier, cache: CacheStore) -> None:
        self._notifier = notifier
        self._cache = cache

    async def execute(self, outlook: DayOutlook) -> bool:
        """Push the verdict once per day for non-NORMAL regimes. Returns True
        when a notification was sent."""
        if not self._notifier.enabled:
            return False
        # Ordinary sessions are the silent default — only warn/cheer on the
        # days that change how the user should trade.
        if outlook.regime is DayRegime.NORMAL:
            return False

        # Dedup on (UTC date, regime): one push per regime per day, but a genuine
        # regime change during the session (e.g. THIN early → EXPANSION after a
        # catalyst) re-pushes so the user isn't stuck with the stale early read.
        stamp = f"{outlook.asof.date().isoformat()}:{outlook.regime.value}"
        if await self._cache.get(CACHE_KEY) == stamp:
            return False

        ok = await self._notifier.push(
            title=_title(outlook),
            message=_body(outlook),
            priority=_priority(outlook),
            tags=_tags(outlook),
        )
        if ok:
            await self._cache.set(CACHE_KEY, stamp, ttl_seconds=CACHE_TTL_SECONDS)
            logger.info("ntfy: pushed day-outlook (%s, score=%.0f)", outlook.regime.value, outlook.score)
        return ok


# -------- message formatters --------

_REGIME_EMOJI = {DayRegime.THIN: "⚠️", DayRegime.EXPANSION: "🚀", DayRegime.NORMAL: "•"}


def _title(o: DayOutlook) -> str:
    label = {DayRegime.THIN: "Dia FRACO", DayRegime.EXPANSION: "Dia de EXPANSÃO", DayRegime.NORMAL: "Dia normal"}
    return f"{_REGIME_EMOJI[o.regime]} {label[o.regime]} · potencial {o.score:.0f}/100"


def _body(o: DayOutlook) -> str:
    # Lead with the headline, then the top few rationale lines (the push UX is
    # scanned fast, so cap it).
    parts = [o.headline]
    parts.extend(o.rationale[:4])
    return " | ".join(parts)


def _priority(o: DayOutlook) -> int:
    # A thin day is the one the user most needs warned about → higher priority.
    if o.regime is DayRegime.THIN:
        return 4
    if o.regime is DayRegime.EXPANSION:
        return 4
    return 3


def _tags(o: DayOutlook) -> list[str]:
    if o.regime is DayRegime.THIN:
        return ["warning", "chart_with_downwards_trend"]
    return ["rocket", "chart_with_upwards_trend"]


__all__ = ["PushDayOutlookAlertsUseCase"]
