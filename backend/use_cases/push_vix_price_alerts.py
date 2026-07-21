"""Push VIX×price stance changes to the user's phone via ntfy.sh.

Two kinds of push, each with its own dedup so neither spams:

- **Stance change** — the standing playbook for an asset flipped (e.g. neutral
  → "só venda em repique", or a caution to close positions appeared). Dedup is
  the last-pushed `stance:caution` state per asset in Redis; only actionable
  states (non-neutral stance or a caution) push.
- **Trigger** — price just reached the actionable Bollinger zone while a
  directional stance is on (the "zona de venda AGORA" moment). %B hovers
  around the zone edge, so triggers re-arm on a 30-minute TTL per asset+stance
  instead of on state change.

Never raises — a push outage must not break the tick loop.
"""

from __future__ import annotations

import logging

from adapters.ntfy_notifier import NtfyNotifier
from core.enums import AssetSymbol
from core.interfaces import CacheStore
from core.models import VixPriceSignal

logger = logging.getLogger(__name__)

STATE_KEY = "ntfy:pushed:vix_price:{asset}"  # value = "stance:caution"
STATE_TTL_SECONDS = 12 * 3600
TRIGGER_KEY = "ntfy:pushed:vix_price_trigger:{asset}"  # value = stance
TRIGGER_TTL_SECONDS = 30 * 60

_STANCE_LABEL = {
    "sell_rallies": "só VENDA em repique",
    "buy_dips": "COMPRE recuos",
    "stay_out": "fique de FORA",
    "neutral": "neutro",
}
_STANCE_EMOJI = {
    "sell_rallies": "🔻",
    "buy_dips": "🟢",
    "stay_out": "⏸️",
    "neutral": "•",
}
_CAUTION_LABEL = {
    "exit_longs": "considere ENCERRAR compras",
    "exit_shorts": "considere ENCERRAR vendas",
}


class PushVixPriceAlertsUseCase:
    """Decides which per-asset VIX×price reads warrant a phone push."""

    def __init__(self, notifier: NtfyNotifier, cache: CacheStore) -> None:
        self._notifier = notifier
        self._cache = cache

    async def execute(self, signals: dict[AssetSymbol, VixPriceSignal]) -> int:
        """Returns the number of notifications sent."""
        if not self._notifier.enabled:
            return 0
        sent = 0
        for asset, sig in signals.items():
            sent += await self._push_state_change(asset, sig)
            sent += await self._push_trigger(asset, sig)
        return sent

    async def _push_state_change(self, asset: AssetSymbol, sig: VixPriceSignal) -> int:
        state = f"{sig.stance}:{sig.caution or '-'}"
        key = STATE_KEY.format(asset=asset.value)
        if await self._cache.get(key) == state:
            return 0
        # Remember even non-actionable states so a genuine flip back to
        # actionable re-pushes, but stay silent about "neutral, no caution".
        await self._cache.set(key, state, ttl_seconds=STATE_TTL_SECONDS)
        if sig.stance == "neutral" and sig.caution is None:
            return 0

        title = f"{_STANCE_EMOJI[sig.stance]} {asset.value}: {_STANCE_LABEL[sig.stance]}"
        if sig.caution:
            title = f"⚠️ {asset.value}: {_CAUTION_LABEL[sig.caution]}"
        body = " | ".join([sig.headline, *sig.rationale[:3]])
        ok = await self._notifier.push(
            title=title,
            message=body,
            priority=4 if sig.caution else 3,
            tags=["chart_with_downwards_trend"] if sig.stance == "sell_rallies" else ["chart"],
        )
        if ok:
            logger.info("ntfy: pushed vix_price state (%s → %s)", asset.value, state)
        return int(ok)

    async def _push_trigger(self, asset: AssetSymbol, sig: VixPriceSignal) -> int:
        if not sig.trigger or sig.stance not in ("sell_rallies", "buy_dips"):
            return 0
        key = TRIGGER_KEY.format(asset=asset.value)
        if await self._cache.get(key) == sig.stance:
            return 0

        zone = "zona de VENDA" if sig.stance == "sell_rallies" else "zona de COMPRA"
        ok = await self._notifier.push(
            title=f"🎯 {asset.value}: {zone} agora",
            message=" | ".join([sig.headline, *sig.rationale[:3]]),
            priority=4,
            tags=["dart"],
        )
        if ok:
            await self._cache.set(key, sig.stance, ttl_seconds=TRIGGER_TTL_SECONDS)
            logger.info("ntfy: pushed vix_price trigger (%s, %s)", asset.value, sig.stance)
        return int(ok)


__all__ = ["PushVixPriceAlertsUseCase"]
