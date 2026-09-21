"""TypeSafe AI's Jev — a model that only answers decisions, not text.

Why it is here: the scalper's entry is a deterministic tape read (a burst of
one-sided prints). It fires on the burst and knows nothing about the shape
around it. Jev is asked one yes/no question about the same situation and can
only veto — it never picks a symbol, a side, a size or a moment. The engine
stays the thing that trades.

The call is a single POST with the state as plain text and a `noul` question
(binary, answered as a 0..1 confidence). Measured ~70ms round trip, which is
why it can sit in the ingest loop at all; entries are rare (one per symbol per
cooldown), so it is not on the hot path of every print.

A failure answers None, and None means "no opinion" — the deterministic entry
goes ahead. An outage at the model vendor must not silently stop the bot from
trading; a bad *answer* stops the trade, a missing answer does not.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from settings import get_settings

logger = logging.getLogger(__name__)

_URL = "https://api.typesafe.ai/v1/systemone"
_MODEL = "jev-latest"
# Short on purpose: this runs between a signal and an order. Waiting longer for
# a second opinion than the move itself lasts would be worse than no opinion.
_TIMEOUT_SECONDS = 2.0


async def confirm_entry(state: str) -> float | None:
    """Confidence (0..1) that this entry is worth taking, or None with no answer."""
    settings = get_settings()
    key = settings.jev_api_key
    if key is None:
        return None
    payload: dict[str, Any] = {
        "model": _MODEL,
        "state": state,
        "questions": {
            "entrar": {
                "type": "noul",
                "instructions": "Vale abrir esta operação agora?",
                "criteria": {
                    "true": (
                        "o fluxo recente é claramente de um lado só, a liquidez está "
                        "normal e o preço tem espaço para andar a favor da entrada"
                    ),
                    "false": (
                        "fluxo misto ou já esticado, liquidez fina, spread largo, ou "
                        "o movimento já aconteceu e a entrada seria no fim dele"
                    ),
                },
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _URL,
                json=payload,
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
            )
            response.raise_for_status()
            answer = response.json()["answers"]["entrar"]["noul"]
        return float(answer)
    except Exception:
        logger.warning("Jev nao respondeu; entrada segue pela regra deterministica")
        return None
