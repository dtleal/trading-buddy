"""Anthropic Claude adapter.

Implements `core.interfaces.LLMGateway`. Uses prompt caching on the system
prompt so repeated calls with the same context are cheap, and hashes the
combined prompt to enable a higher-level idempotency cache (see use cases).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from anthropic import AsyncAnthropic

from day_trading_buddy.core.enums import LLMOutputKind
from day_trading_buddy.core.models import LLMOutput

logger = logging.getLogger(__name__)


def prompt_hash(system_prompt: str, user_prompt: str, model: str) -> str:
    payload = f"{model}\n---\n{system_prompt}\n---\n{user_prompt}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AnthropicLLMGateway:
    """Async Anthropic client wired to our domain `LLMOutput` DTO."""

    def __init__(
        self,
        api_key: str,
        *,
        default_briefing_model: str,
        default_classifier_model: str,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._default_briefing_model = default_briefing_model
        self._default_classifier_model = default_classifier_model

    def _pick_model(self, kind: LLMOutputKind, override: str | None) -> str:
        if override:
            return override
        if kind == LLMOutputKind.BRIEFING:
            return self._default_briefing_model
        return self._default_classifier_model

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        kind: LLMOutputKind,
        model: str | None = None,
        max_tokens: int = 1500,
    ) -> LLMOutput:
        chosen_model = self._pick_model(kind, model)
        cache_hash = prompt_hash(system_prompt, user_prompt, chosen_model)

        response = await self._client.messages.create(
            model=chosen_model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )

        content_parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                content_parts.append(text)
        content = "\n".join(content_parts).strip()

        usage = getattr(response, "usage", None)
        meta: dict[str, Any] = {}
        if usage is not None:
            meta = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            }

        return LLMOutput(
            kind=kind,
            model=chosen_model,
            prompt_hash=cache_hash,
            content=content,
            created_at=datetime.now(timezone.utc),
            metadata=meta,
        )
